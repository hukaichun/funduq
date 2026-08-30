from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from funduq_provider_sdk.provider import DeliveredRun, Refusal, Registration


class Event(BaseModel):
    """Something the machine observed, for the driver to act on."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)


class ConnectRequested(Event):
    """Someone is opening the link."""

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
    """An offer's three-valued answer, in core's vocabulary rather than the wire's: `True` accepted, `False` declined-because-full, `Refusal` permanently refused."""

    id: str
    verdict: bool | Refusal
    late: bool = False


class Unanswered(Event):
    """An offer's deadline passed."""

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
    """The connection ended."""

    unanswered_offers: list[str] = []
    dropped_queries: list[str] = []


class LinkFailed(Event):
    """The far side broke the protocol."""

    reason: str


class Refused(Event):
    """funduq declined to open the link at all — a ticket that was not live, or not issued to this key."""

    reason: str
