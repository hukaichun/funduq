from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from pydantic import ValidationError

from funduq.kyok import KyokForwardedProps, kyok_forwarded_props
from funduq.models import AgentRef


INTERJECTION_EXTENSION_URI = "https://github.com/hukaichun/funduq/ext/interjection/v1"
"""The A2A extension under which a caller declares an *interjection*: a run that asks to join another run's turn already in flight."""

ADDRESSED_RUN_METADATA_KEY = f"{INTERJECTION_EXTENSION_URI}/addressedRunId"


OBSERVED_METADATA_KEY = "funduq"
"""The one key funduq writes under somebody else's metadata: what **funduq itself observed or added**, as opposed to what a caller said. The same key on every surface — a run's record, the `forwardedProps` an agent receives, an A2A task or status update."""


RESERVED_METADATA_KEYS = frozenset({OBSERVED_METADATA_KEY})
"""Caller-supplied metadata keys stripped at the doors: only funduq's own. Everything else is the caller's and is relayed verbatim."""


def observed(**fields: Any) -> dict[str, Any]:
    """`metadata` for a status write: `fields` (None dropped) under funduq's own key, and nothing at the top level."""
    return {OBSERVED_METADATA_KEY: {k: v for k, v in fields.items() if v is not None}}


def observed_of(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """What funduq wrote under `metadata`, or `{}`."""
    ours = (metadata or {}).get(OBSERVED_METADATA_KEY)
    return ours if isinstance(ours, dict) else {}


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
    ours: dict[str, Any] = {}
    if kyok_enabled:
        ours["kyok"] = kyok_forwarded_props(run_id, agent, signing_secret)
    if addressed_run_id is not None:
        # The caller's declared interjection intent (see INTERJECTION_EXTENSION_URI), verified at the door.
        ours["addressedRunId"] = addressed_run_id
    if actor_chain:
        ours["actorChain"] = actor_chain
    if isinstance(caller_forwarded_props, dict):
        theirs = {k: v for k, v in caller_forwarded_props.items() if k != OBSERVED_METADATA_KEY}
        return {**theirs, OBSERVED_METADATA_KEY: ours} if ours else theirs
    return {OBSERVED_METADATA_KEY: ours} if ours else caller_forwarded_props


def read_kyok_forwarded_props(forwarded_props: Any) -> KyokForwardedProps | None:
    """The KYOK grant funduq put under `forwardedProps.funduq.kyok`, or None if absent or invalid."""
    raw = observed_of(forwarded_props if isinstance(forwarded_props, dict) else None).get("kyok")
    if raw is None:
        return None
    try:
        return KyokForwardedProps.model_validate(raw)
    except ValidationError:
        return None
