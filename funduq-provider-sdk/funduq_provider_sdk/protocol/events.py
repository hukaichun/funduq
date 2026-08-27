from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from funduq_provider_sdk.provider import DeliveredRun, Refusal, Registration


class Event(BaseModel):
    """Something the machine observed, for the driver to act on.

    Events are models for the same reason frames are — this surface is a
    specification, and an unenforced annotation specifies nothing — but they
    carry no aliases, because they never go on a wire. That one setting is the
    whole difference between the two families.

    A driver's entire job is to turn each of these into the one `Funduq` call
    it names.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)


class ConnectRequested(Event):
    """Someone is opening the link. The driver takes this to
    `attach_provider` — which is where the ticket is spent and the proof
    verified — and answers with `accept_connect` or `refuse_connect`.

    The machine does not verify the proof itself: the ticket store is core's,
    and a ticket is claimed only after the key it names matches, so that the
    burn cannot be triggered by anyone who merely saw one."""

    public_key: str
    ticket: str
    nonce: str
    proof: str
    max_concurrent_runs: int | None = None


class Registering(Event):

    id: str
    agents: list[Registration]


class Deleting(Event):

    id: str
    name: str


class AskingThreadMessages(Event):

    id: str
    thread_id: str
    limit: int | None = None


class Answered(Event):
    """An offer's three-valued answer, in core's vocabulary rather than the
    wire's: `True` accepted, `False` declined-because-full, `Refusal`
    permanently refused.

    `late` marks an answer that arrived after funduq stopped waiting. It is
    evidence rather than an instruction — see the note in
    `docs/link-protocol-machine.md`: core's late-claim path is reached from a
    reported event, not from a late answer, so there is nothing for a driver
    to call here."""

    id: str
    verdict: bool | Refusal
    late: bool = False


class Unanswered(Event):
    """An offer's deadline passed. The place goes back and the run is offered
    again when something changes; the provider is counted, not disbelieved."""

    id: str


class Reported(Event):

    run_id: str
    event: Any = None


class Finished(Event):

    run_id: str


class Offered(Event):

    id: str
    run: DeliveredRun


class Cancelled(Event):

    run_id: str


class Opened(Event):
    """The far side answered and, if a key was pinned, the answer verified."""


class Replied(Event):

    id: str
    payload: Any = None


class Failed(Event):

    id: str
    reason: str


class Gone(Event):
    """The connection ended.

    It says what funduq observed — this link is gone, these offers were never
    answered, these queries will never be — and draws no conclusion about any
    run. What a claimed run becomes is core's verdict, because funduq never
    decides on a provider's behalf."""

    unanswered_offers: list[str] = []
    dropped_queries: list[str] = []


class LinkFailed(Event):
    """The far side broke the protocol. The machine has already closed; the
    reason is for the log and the operator, not for a retry."""

    reason: str


class Refused(Event):
    """funduq declined to open the link at all — a ticket that was not live,
    or not issued to this key. Distinct from `LinkFailed`, which is a broken
    protocol rather than a refused admission."""

    reason: str
