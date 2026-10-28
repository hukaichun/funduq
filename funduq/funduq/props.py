from __future__ import annotations

from typing import Any

from funduq_contract import OBSERVED_METADATA_KEY, FunduqProps, KyokForwardedProps

from funduq.kyok import kyok_forwarded_props
from funduq.models import AgentRef


INTERJECTION_EXTENSION_URI = "https://github.com/hukaichun/funduq/ext/interjection/v1"
"""The A2A extension under which a caller declares an *interjection*: a run that asks to join another run's turn already in flight."""

ADDRESSED_RUN_METADATA_KEY = f"{INTERJECTION_EXTENSION_URI}/addressedRunId"


RESERVED_METADATA_KEYS = frozenset({OBSERVED_METADATA_KEY})
"""Caller-supplied metadata keys stripped at the doors: only funduq's own. Everything else is the caller's and is relayed verbatim."""


def observed(**fields: Any) -> dict[str, Any]:
    """`metadata` for a status write: `fields` (None dropped) under funduq's own key, and nothing at the top level."""
    return {OBSERVED_METADATA_KEY: {k: v for k, v in fields.items() if v is not None}}


def build_forwarded_props(
    signing_secret: str,
    run_id: str,
    agent: AgentRef,
    kyok_enabled: bool,
    caller_forwarded_props: Any,
    actor_chain: Any = None,
    addressed_run_id: str | None = None,
) -> Any:
    """The `forwardedProps` the agent receives: the caller's, verbatim, plus one key of funduq's own.

    Everything funduq adds lives under `forwardedProps.funduq` — a KYOK grant
    if `kyok_enabled`, the actor chain relayed verbatim if present, the
    interjection target the caller declared at the door — and that key is
    funduq's unconditionally: written when there is something to say,
    absent when there is not, and never the caller's value. So an agent
    reading it knows funduq put it there.
    """
    ours = FunduqProps(
        kyok=kyok_forwarded_props(run_id, agent, signing_secret) if kyok_enabled else None,
        # The caller's declared interjection intent (see INTERJECTION_EXTENSION_URI), verified at the door.
        addressed_run_id=addressed_run_id,
        actor_chain=actor_chain or None,
    ).model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(caller_forwarded_props, dict):
        theirs = {k: v for k, v in caller_forwarded_props.items() if k != OBSERVED_METADATA_KEY}
        return {**theirs, OBSERVED_METADATA_KEY: ours} if ours else theirs
    return {OBSERVED_METADATA_KEY: ours} if ours else caller_forwarded_props


def read_kyok_forwarded_props(forwarded_props: Any) -> KyokForwardedProps | None:
    """The KYOK grant funduq put under `forwardedProps.funduq.kyok`, or None if absent or invalid."""
    return FunduqProps.of(forwarded_props).kyok
