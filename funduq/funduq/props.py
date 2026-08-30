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
    delegation: dict | None = None,
) -> Any:
    """Merges funduq-added forwarded-props extras (a KYOK grant if `kyok_enabled`, the caller's actor chain relayed verbatim if present) into the caller-supplied `forwarded_props`, returning the caller's value unchanged if there is nothing to add."""
    extra: dict[str, Any] = {}
    if kyok_enabled:
        extra["kyok"] = kyok_forwarded_props(run_id, agent, signing_secret)
    if addressed_run_id is not None:
        # The caller's declared interjection intent (see INTERJECTION_EXTENSION_URI).
        extra["addressedRunId"] = addressed_run_id
    if actor_chain:
        extra["actorChain"] = actor_chain
    if delegation is not None:
        # The session delegation certificate, relayed so the agent can resolve the chain's head to its durable authority itself.
        extra["delegation"] = delegation
    if not extra:
        return caller_forwarded_props
    if isinstance(caller_forwarded_props, dict):
        return {**caller_forwarded_props, **extra}
    return extra
