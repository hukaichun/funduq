from __future__ import annotations

import os
import tempfile
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from funduq.config import CoreSettings
from funduq.identity import FunduqIdentity
from funduq.core import Funduq
from funduq.models import AgentRef
from funduq.migrate import migrate as funduq_migrate
from funduq_provider_sdk import InProcessLink, ProviderIdentity, ProviderRuntime
from funduq_contract import Registration


TEST_SIGNING_SECRET = "test-signing-secret"

DATABASE_URL = os.environ.get(
    "FUNDUQ_DATABASE_URL", f"sqlite+aiosqlite:///{Path(tempfile.gettempdir()) / 'funduq_pytest.db'}"
)

_TABLES_CHILD_FIRST = (
    "run_events",
    "thread_messages",
    "runs",
    "threads",
    "agents",
    "llm_providers",
    "providers",
)


@pytest.fixture(scope="session")
def settings() -> CoreSettings:
    return CoreSettings(
        database_url=DATABASE_URL,
        token_signing_secret=TEST_SIGNING_SECRET,
        identity_private_key=FunduqIdentity.generate_hex(),
    )


@pytest.fixture(scope="session")
def funduq(settings: CoreSettings) -> Funduq:
    return Funduq(settings)


@pytest.fixture(scope="session", autouse=True)
def _schema(settings: CoreSettings) -> None:
    url = make_url(settings.database_url)
    if url.get_backend_name() == "sqlite" and url.database:
        for suffix in ("", "-wal", "-shm"):
            Path(url.database + suffix).unlink(missing_ok=True)
    os.environ["FUNDUQ_DATABASE_URL"] = settings.database_url
    funduq_migrate(settings.database_url)


@pytest.fixture(autouse=True)
async def _dispatching(funduq: Funduq) -> AsyncIterator[None]:
    funduq.broker.start()
    try:
        yield
    finally:
        funduq.broker.stop()


@pytest.fixture(autouse=True)
async def _clean_db(funduq: Funduq) -> AsyncIterator[None]:
    is_postgres = funduq.engine.sync_engine.dialect.name == "postgresql"
    async with funduq.engine.begin() as conn:
        if is_postgres:
            await conn.exec_driver_sql(
                "TRUNCATE providers, agents, threads, runs, thread_messages, run_events, "
                "llm_providers RESTART IDENTITY CASCADE"
            )
        else:
            for table in _TABLES_CHILD_FIRST:
                await conn.exec_driver_sql(f"DELETE FROM {table}")
    yield


@pytest.fixture
async def session(funduq: Funduq) -> AsyncIterator[AsyncSession]:
    async with funduq.session() as s:
        yield s


class Identity(ProviderIdentity):

    def __init__(self) -> None:
        super().__init__(Ed25519PrivateKey.generate())

    def sign_chain_hop(self, prev_token: str | None = None) -> str:
        return self.sign_hop(prev_token)



async def publish_agents(funduq: Funduq, link, names: list[str]):
    """Open `link` and publish `names` on it — the two acts the handshake now
    separates, in the order it requires."""
    await funduq.attach_provider(link)
    return await funduq.register_agents(link, [Registration(name=n) for n in names])


async def publish_llm(funduq: Funduq, link, names: list[str], metadata=None):
    """The LLM-offering mirror of `publish_agents`."""
    await funduq.attach_llm_provider(link)
    return await funduq.register_llm_providers(link, names, metadata)


async def publish_offline(funduq: Funduq, identity, agents: list[Registration], provider_name=None):
    """Register `agents` under `identity` and leave them registered-but-offline.

    That state has one road to it now: open a link, publish on it, close the
    link. Nothing can be published without one, which is the point — you
    cannot advertise an agent you were never able to serve.
    """
    runtime = ProviderRuntime(identity, EchoAgent())
    runtime.start()
    link = InProcessLink(funduq, runtime)
    await funduq.attach_provider(link)
    registration = await funduq.register_agents(link, agents, provider_name=provider_name)
    funduq.detach_provider(identity.public_key, link)
    await runtime.aclose()
    return registration


@pytest.fixture
def new_identity() -> type[Identity]:
    return Identity


@pytest.fixture
async def attach(funduq: Funduq):
    """Open a link and publish `names` on it — the order the handshake now has.

    Returns `(runtime, link)`: the link is the credential for anything else
    this provider does to its roster, so tests that register more or delete
    need it.
    """
    started: list[ProviderRuntime] = []

    async def _attach(identity: ProviderIdentity, provider, names, **kwargs):
        runtime = ProviderRuntime(identity, provider, **kwargs)
        started.append(runtime)
        runtime.start()
        link = InProcessLink(funduq, runtime)
        await funduq.attach_provider(link)
        if names:
            await funduq.register_agents(link, [Registration(name=n) for n in names])
        return runtime, link

    yield _attach
    for runtime in started:
        await runtime.aclose(cancel_in_flight=True)


class EchoAgent:

    def __init__(self) -> None:
        self.seen_chain: list | None = None

    async def run_stream(self, agent_name: str, run_input):
        self.seen_chain = (run_input.forwarded_props or {}).get("actorChain")
        ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
        yield {"type": "RUN_STARTED", **ids}
        yield {"type": "TEXT_MESSAGE_START", "messageId": "m1", "role": "assistant"}
        yield {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "done"}
        yield {"type": "TEXT_MESSAGE_END", "messageId": "m1"}
        yield {"type": "RUN_FINISHED", **ids}


@dataclass
class Served:

    identity: Identity
    provider: Any
    runtime: ProviderRuntime
    agents: dict
    link: Any = None


@pytest.fixture
async def serve(funduq: Funduq, attach):

    async def _serve(provider=None, *names: str, **kwargs) -> Served:
        provider = EchoAgent() if provider is None else provider
        names = names or ("agent",)
        identity = Identity()
        runtime, link = await attach(identity, provider, names, **kwargs)
        agents = {
            name: AgentRef(provider_key=identity.public_key, name=name) for name in names
        }
        return Served(identity, provider, runtime, agents, link)

    return _serve


@pytest.fixture
async def register(funduq: Funduq):

    async def _register(*names: str) -> Served:
        """Registered and then offline — which is now reached the only way it can
        be: publish on an open link, then close the link. Nothing can be
        published without one."""
        identity = Identity()
        runtime = ProviderRuntime(identity, EchoAgent())
        runtime.start()
        link = InProcessLink(funduq, runtime)
        await funduq.attach_provider(link)
        await funduq.register_agents(link, [Registration(name=n) for n in names])
        funduq.detach_provider(identity.public_key, link)
        await runtime.aclose()
        agents = {
            name: AgentRef(provider_key=identity.public_key, name=name) for name in names
        }
        return Served(identity, None, None, agents)

    return _register
