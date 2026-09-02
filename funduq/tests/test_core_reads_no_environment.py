from __future__ import annotations

import ast
from pathlib import Path

import pytest

from funduq.config import CoreSettings
from funduq.core import Funduq

_CORE = Path(__file__).resolve().parent.parent / "funduq"

# alembic/env.py is the one exception and an honest one: it is a script the
# alembic CLI executes, the CLI has no other way to be told, and it already
# prefers `config.attributes` with the environment only as a fallback.
_ALLOWED = {"alembic/env.py"}


def test_no_core_module_reads_the_process_environment():
    """Reading `os.environ` is a process's act, and core is a library that does
    not own one. The same call must not produce a different object because of
    ambient state its caller never mentioned.

    Scanned rather than trusted to review: `CoreSettings` was a `BaseSettings`
    for a long time and nothing said so at the call site — `Funduq()` quietly
    configured itself from the environment, and no test noticed because every
    test happened to set the variables it wanted.
    """
    offenders = []
    for module in sorted(_CORE.rglob("*.py")):
        relative = module.relative_to(_CORE).as_posix()
        if relative in _ALLOWED or "__pycache__" in relative:
            continue
        source = module.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            reads_environ = (
                isinstance(node, ast.Attribute)
                and node.attr in {"environ", "getenv"}
                and isinstance(node.value, ast.Name)
                and node.value.id == "os"
            )
            # `config.py` is where the named act lives, so it is the one file
            # allowed to touch os.environ — inside `from_env` and nowhere else.
            if reads_environ and relative != "config.py":
                offenders.append(f"{relative}:{node.lineno}")

    assert not offenders, (
        f"core modules reading the environment: {offenders}. Configuration is an "
        "argument; a deployment that wants the environment asks for it by name with "
        "CoreSettings.from_env()."
    )


def test_settings_do_not_absorb_the_environment_on_construction(monkeypatch):
    monkeypatch.setenv("FUNDUQ_DATABASE_URL", "postgresql+psycopg://ambient/state")

    settings = CoreSettings(token_signing_secret="s", identity_private_key="a" * 64)

    assert "ambient" not in settings.database_url, (
        "constructing settings picked up an environment variable nobody passed"
    )


def test_from_env_is_the_named_act(monkeypatch):
    monkeypatch.setenv("FUNDUQ_DATABASE_URL", "sqlite+aiosqlite:///named.db")
    monkeypatch.setenv("FUNDUQ_TOKEN_SIGNING_SECRET", "s")
    monkeypatch.setenv("FUNDUQ_IDENTITY_PRIVATE_KEY", "a" * 64)

    settings = CoreSettings.from_env()

    assert settings.database_url == "sqlite+aiosqlite:///named.db"


def test_an_empty_variable_counts_as_unset():
    """What a declared-but-unset variable looks like in a shell or a compose
    file. Treating it as a value would override a default with nothing."""
    settings = CoreSettings.from_env(
        {
            "FUNDUQ_TOKEN_SIGNING_SECRET": "s",
            "FUNDUQ_IDENTITY_PRIVATE_KEY": "a" * 64,
            "FUNDUQ_DATABASE_URL": "",
        }
    )

    assert settings.database_url, "an empty variable emptied the default"


def test_funduq_cannot_be_built_without_being_told():
    """`Funduq()` used to mean "read the environment". Nothing at that call
    site said so, which is the whole objection."""
    with pytest.raises(TypeError):
        Funduq()


def test_the_brokers_waits_are_settings_and_reach_the_broker():
    """The three waits are embedder policy: set in `CoreSettings` (or its
    environment mirror), they must arrive on the broker `Funduq` builds."""
    from funduq.config import CoreSettings
    from funduq.core import Funduq

    settings = CoreSettings.from_env(
        {
            "FUNDUQ_TOKEN_SIGNING_SECRET": "s",
            "FUNDUQ_IDENTITY_PRIVATE_KEY": "a" * 64,
            "FUNDUQ_DELIVER_TIMEOUT_SECONDS": "0.5",
            "FUNDUQ_UNSERVED_TIMEOUT_SECONDS": "9",
            "FUNDUQ_UNDELIVERED_WINDOW_SECONDS": "60",
        }
    )
    funduq = Funduq(settings)

    assert funduq.broker.deliver_timeout_seconds == 0.5
    assert funduq.broker.unserved_timeout_seconds == 9.0
    assert funduq.broker.undelivered_window_seconds == 60.0


def test_a_bare_broker_and_a_settings_built_one_agree_on_the_defaults():
    """One definition: `RunBroker()`'s keyword defaults are the same names
    `CoreSettings` carries, so nothing has to be kept in sync by hand."""
    from funduq.broker import RunBroker
    from funduq.config import CoreSettings

    bare = RunBroker()
    fields = CoreSettings.model_fields
    assert bare.deliver_timeout_seconds == fields["deliver_timeout_seconds"].default
    assert bare.unserved_timeout_seconds == fields["unserved_timeout_seconds"].default
    assert bare.undelivered_window_seconds == fields["undelivered_window_seconds"].default
