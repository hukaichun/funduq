from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from funduq.kyok import kyok_forwarded_props
from funduq.models import AgentRef


INTERJECTION_EXTENSION_URI = "https://github.com/hukaichun/funduq/ext/interjection/v1"
"""The A2A extension under which a caller declares an *interjection*: a run that asks to join another run's turn already in flight."""

ADDRESSED_RUN_METADATA_KEY = f"{INTERJECTION_EXTENSION_URI}/addressedRunId"


OBSERVED_METADATA_KEY = "funduq"
"""The one key under a run's metadata that holds what **funduq itself observed**, as opposed to what a caller said."""


RESERVED_METADATA_KEYS = frozenset(
    {"interrupts", "pendingToolCalls", "failureReason", OBSERVED_METADATA_KEY}
)
"""Metadata keys funduq itself writes into a run's record (plus "funduq", held in reserve)."""


def build_forwarded_props(
    signing_secret: str,
    run_id: str,
    agent: AgentRef,
    kyok_enabled: bool,
    caller_forwarded_props: Any,
    actor_chain: Any = None,
    addressed_run_id: str | None = None,
) -> Any:
    """The `forwardedProps` the agent receives: the caller's, with funduq's additions on top — a KYOK grant if `kyok_enabled`, the actor chain relayed verbatim if present, and the interjection target the caller declared at the door.

    `addressedRunId` is funduq's own annotation and is owned unconditionally:
    written when declared, removed when not, so its presence in the record
    means funduq verified it — never that the caller typed it.
    """
    extra: dict[str, Any] = {}
    if kyok_enabled:
        extra["kyok"] = kyok_forwarded_props(run_id, agent, signing_secret)
    if addressed_run_id is not None:
        # The caller's declared interjection intent (see INTERJECTION_EXTENSION_URI), verified at the door.
        extra["addressedRunId"] = addressed_run_id
    if actor_chain:
        extra["actorChain"] = actor_chain
    if isinstance(caller_forwarded_props, dict):
        theirs = {k: v for k, v in caller_forwarded_props.items() if k != "addressedRunId"}
        merged = {**theirs, **extra}
        return merged if (merged or not caller_forwarded_props) else None
    return extra or caller_forwarded_props
