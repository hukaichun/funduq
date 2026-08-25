from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from funduq.kyok import kyok_forwarded_props
from funduq.models import AgentRef


INTERJECTION_EXTENSION_URI = "https://github.com/hukaichun/funduq/ext/interjection/v1"
"""The A2A extension under which a caller declares an *interjection*: a run
that asks to join another run's turn already in flight. This is intent, not
state — `parentRunId` (AG-UI's own field, relayed untouched) says "this
follows that, next turn"; `addressedRunId` says "this wants *into* that turn
now". The two are different verbs and the caller chooses one; liveness of
the target is never used to guess intent. A2A v1.0 has no carrier for
unprompted speech into a working task (its only mid-task verb is cancel), so
this rides A2A's extension convention: the caller puts the target's id in
message metadata under `f"{INTERJECTION_EXTENSION_URI}/addressedRunId"`.
funduq relays it to the agent as `forwardedProps.addressedRunId` and holds
no opinion about the target's state — the agent running it judges whether
there is still a turn to join, and an ask that comes too late degrades to an
ordinary next turn. Yields to whatever carrier A2A ships for this."""

ADDRESSED_RUN_METADATA_KEY = f"{INTERJECTION_EXTENSION_URI}/addressedRunId"


OBSERVED_METADATA_KEY = "funduq"
"""The one key under a run's metadata that holds what **funduq itself
observed**, as opposed to what a caller said. Everything under it is written
by funduq and stripped from caller metadata at the doors, which is what lets
a reader tell the two apart without trusting either — the party that answered
a paused run sits here, and no caller can plant one."""


RESERVED_METADATA_KEYS = frozenset(
    {"interrupts", "pendingToolCalls", "failureReason", OBSERVED_METADATA_KEY}
)
"""Metadata keys funduq itself writes into a run's record (plus "funduq", held in
reserve). A caller-supplied value under any of these is stripped at the doors
before anything reads or stores the metadata — otherwise a caller could plant
a fake failure reason that would sit in the record wearing funduq's
handwriting. The strip happens in one place, `doors.verify_caller`, because
every door funnels caller metadata through it — and that place is outside
`protocols/` because nothing about it is any protocol's. (`verifiedActorChain`
left this list when funduq stopped summarizing chains: with no funduq-authored
digest there is no digest to forge — the chain reaches the agent verbatim and
the agent verifies for itself.)"""


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
    """Merges funduq-added forwarded-props extras (a KYOK grant if `kyok_enabled`, the caller's
    actor chain relayed verbatim if present) into the caller-supplied `forwarded_props`,
    returning the caller's value unchanged if there is nothing to add.

    Both adapters build through here, and both doors take the same
    `metadata.kyok` opt-in — a run is granted one only when its **own**
    caller submitted it, and nothing propagates from a parent run. The
    chain is the caller's own utterance,
    not a funduq digest: the agent verifies it for itself
    (`funduq_provider_sdk.verify_chain`), trusting no summary of the
    relay's — funduq authors nothing here beyond the KYOK grant.
    """
    extra: dict[str, Any] = {}
    if kyok_enabled:
        extra["kyok"] = kyok_forwarded_props(run_id, agent, signing_secret)
    if addressed_run_id is not None:
        # The caller's declared interjection intent (see
        # INTERJECTION_EXTENSION_URI). AG-UI callers write this key into
        # their own forwardedProps directly and it passes through untouched;
        # the A2A door copies it here from the extension's metadata key.
        extra["addressedRunId"] = addressed_run_id
    if actor_chain:
        extra["actorChain"] = actor_chain
    if delegation is not None:
        # The session delegation certificate, relayed so the agent can
        # resolve the chain's head to its durable authority itself. Safe to
        # carry: the certificate moves nothing without the delegate's own
        # private key.
        extra["delegation"] = delegation
    if not extra:
        return caller_forwarded_props
    if isinstance(caller_forwarded_props, dict):
        return {**caller_forwarded_props, **extra}
    return extra
