from __future__ import annotations

from typing import TYPE_CHECKING, Any

from funduq import repo
from funduq.errors import LlmProviderNotFound
from funduq.identity import verify_actor_chain, verify_delegation
from funduq.kyok import KyokOptIn, parse_kyok_opt_in, strip_kyok_context
from funduq.props import RESERVED_METADATA_KEYS

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["verify_caller", "resolve_kyok"]


async def verify_caller(session: "AsyncSession", metadata: dict) -> tuple[dict, str | None, Any]:
    """Verifies `metadata["actorChain"]` if present and returns
    `(metadata stripped of funduq's reserved keys, the chain's head key, the raw chain)` —
    `(metadata, None, None)` when no chain is attached. Raises `InvalidActorChain` if the
    chain is tampered: a bad chain is refused at the door, never carried.

    funduq's whole part in caller identity is four verbs — verify, copy the
    head, relay, refuse — and this is the verify. No summary is produced:
    the chain reaches the agent verbatim (`forwardedProps.actorChain`) and
    the agent verifies for itself; the head key is what funduq copies onto
    the records that need an authority (a thread's binding, a paused ask).

    A session delegation certificate under `metadata["delegation"]` resolves
    the head: when the certificate's named delegate signed the chain's first
    hop, the certificate's authority is the effective head — rights attach to
    the durable key; the session key is a glove.

    Every door funnels caller metadata through here, which also makes it the
    one place to strip funduq's reserved keys from the caller's input. It
    lives outside `protocols/` because nothing about it is any protocol's:
    which door the metadata arrived by does not change a single line of it.
    """
    metadata = {k: v for k, v in metadata.items() if k not in RESERVED_METADATA_KEYS}
    actor_chain = metadata.get("actorChain")
    if not actor_chain:
        return metadata, None, None
    head = verify_actor_chain(actor_chain).head
    delegation = metadata.get("delegation")
    if delegation is not None:
        authority = verify_delegation(delegation)
        if delegation.get("delegatePublicKey") == head:
            head = authority
    return metadata, head, actor_chain


async def resolve_kyok(
    session: "AsyncSession", metadata: dict
) -> tuple[dict, KyokOptIn | None]:
    """Reads a KYOK opt-in out of `metadata` and returns
    `(metadata with the caller's KYOK context removed, the opt-in or None)`.

    Raises `LlmProviderNotFound` if the opt-in names an offering that is not
    registered — refused at the door, so a run is never created bound to an
    offering that does not exist.

    The context is stripped from what gets stored because it is the caller's
    to relay, not funduq's to keep: it travels to the LLM provider through
    the binding and is never persisted (see `mechanisms/kyok.md`).
    """
    opt_in = parse_kyok_opt_in(metadata)
    if opt_in is not None and opt_in.llm_provider is not None:
        if await repo.get_llm_provider(session, opt_in.llm_provider) is None:
            raise LlmProviderNotFound(f"unknown KYOK LLM provider '{opt_in.llm_provider}'")
    return strip_kyok_context(metadata), opt_in
