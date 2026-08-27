from __future__ import annotations

from enum import Enum
from typing import Any

from funduq_provider_sdk.protocol import events as ev
from funduq_provider_sdk.protocol import frames as fr
from funduq_provider_sdk.protocol.turn import EMPTY, Turn
from funduq_provider_sdk.provider import DeliveredRun, Refusal


class Link(Enum):

    AWAITING_CONNECT = "awaiting_connect"
    VERIFYING = "verifying"
    OPEN = "open"
    CLOSED = "closed"


class OfferState(Enum):

    OFFERED = "offered"
    CLAIMED = "claimed"
    DECLINED = "declined"
    REFUSED = "refused"
    UNANSWERED = "unanswered"


_SETTLED = (OfferState.CLAIMED, OfferState.DECLINED, OfferState.REFUSED)


class FunduqSide:
    """funduq's half of the link, as a machine: frames in, frames and events out.

    It performs no I/O and reads no clock — time enters as `now` and leaves as
    `next_deadline()`. That is what sans-io buys here, and it is what makes
    every ordering below testable as an ordered script instead of a sleep.

    A driver mounts this between its connection and a `Funduq` object: it
    presents `CONNECTED_PROVIDER_ATTRS` upward and turns each event into the
    one `Funduq` call the event names. It imports nothing from core.

    **There is no registration state.** This machine never learns which agents
    the link serves, so an offer arriving before a `Register` has been
    answered violates nothing — there is nothing for it to violate. The window
    is real and wide: core's roster goes live and nudges the broker before
    `register_agents` does its write and commit, which on Postgres is a
    network round trip.
    """

    def __init__(self, *, deliver_timeout: float) -> None:
        """`deliver_timeout` is core's own `deliver_timeout_seconds`, handed in
        rather than defaulted here: one number, one definition, and a machine
        that disagreed with the broker it serves would hand a run back while
        the broker was still waiting for it."""
        self.state = Link.AWAITING_CONNECT
        self.public_key: str | None = None
        self.max_concurrent_runs: int | None = None
        self._deliver_timeout = deliver_timeout
        self._offers: dict[str, OfferState] = {}
        self._deadlines: dict[str, float] = {}
        self._queries: set[str] = set()
        self._next_id = 0
        self._connecting: fr.Connect | None = None

    # -- transport -> machine ------------------------------------------

    def feed(self, frame: fr.Frame, *, now: float) -> Turn:
        """Read one frame and say what it did."""
        if self.state is Link.CLOSED:
            return EMPTY
        if self.state is Link.AWAITING_CONNECT:
            if isinstance(frame, fr.Connect):
                self.state = Link.VERIFYING
                self._connecting = frame
                return Turn(
                    [],
                    [
                        ev.ConnectRequested(
                            public_key=frame.public_key,
                            ticket=frame.ticket,
                            nonce=frame.nonce,
                            proof=frame.proof,
                            max_concurrent_runs=frame.max_concurrent_runs,
                        )
                    ],
                )
            return self._fail("the first frame on a link must be connect")
        if self.state is Link.VERIFYING:
            return self._fail("spoke while its connect was still being verified")
        return self._opened(frame)

    def _opened(self, frame: fr.Frame) -> Turn:
        if isinstance(frame, fr.Connect):
            return self._fail("tried to connect on a link that is already open")
        if isinstance(frame, fr.Register):
            return Turn([], [ev.Registering(id=frame.id, agents=frame.agents)])
        if isinstance(frame, fr.Delete):
            return Turn([], [ev.Deleting(id=frame.id, name=frame.name)])
        if isinstance(frame, fr.Query):
            self._queries.add(frame.id)
            return Turn([], [ev.Asking(id=frame.id, method=frame.method, args=frame.args)])
        if isinstance(frame, fr.Report):
            # Deliberately not checked against `_offers`. Events are addressed
            # by run, and whether this key may speak for that run is core's
            # question, answered against `claimed_by` — which includes letting
            # a provider claim late by producing for a run funduq had given up
            # waiting for. A machine that gated this on its own table would
            # look obviously right and would make that path unreachable.
            return Turn([], [ev.Reported(run_id=frame.run_id, event=frame.event)])
        if isinstance(frame, fr.Finish):
            return Turn([], [ev.Finished(run_id=frame.run_id)])
        if isinstance(frame, fr.Ok):
            return self._answered(frame)
        if isinstance(frame, fr.Malformed):
            if frame.id is None:
                return self._fail(f"sent something that is not a frame: {frame.reason}")
            return Turn([fr.Err(id=frame.id, reason=frame.reason)], [])
        return self._fail(f"sent a frame funduq does not answer: {frame.kind}")

    def _answered(self, frame: fr.Ok) -> Turn:
        state = self._offers.get(frame.id)
        if state is None:
            return self._fail(f"answered offer {frame.id}, which was never made")
        if state in _SETTLED:
            return self._fail(f"answered offer {frame.id} twice")
        verdict = _verdict_of(frame)
        if verdict is None:
            return self._fail(f"answered offer {frame.id} with no verdict")
        late = state is OfferState.UNANSWERED
        if not late:
            self._offers[frame.id] = _settled(verdict)
            self._deadlines.pop(frame.id, None)
        return Turn([], [ev.Answered(id=frame.id, verdict=verdict, late=late)])

    def connection_lost(self) -> Turn:
        """The connection ended. Says the fact and draws no conclusion: what a
        claimed run becomes is core's verdict, not this machine's."""
        if self.state is Link.CLOSED:
            return EMPTY
        self.state = Link.CLOSED
        unanswered = sorted(i for i, s in self._offers.items() if s is OfferState.OFFERED)
        dropped = sorted(self._queries)
        self._deadlines.clear()
        self._queries.clear()
        return Turn([], [ev.Gone(unanswered_offers=unanswered, dropped_queries=dropped)])

    def timeout(self, now: float) -> Turn:
        """Fires every armed deadline `now` has passed.

        A timed-out offer is not forgotten: its id stays, so an answer arriving
        afterwards is surfaced as `late` rather than read as an answer to an
        offer that was never made. Forgetting it is the instinct, and it turns
        a provider's late honesty into a protocol error."""
        events: list[ev.Event] = []
        for offer_id in sorted(i for i, at in self._deadlines.items() if at <= now):
            del self._deadlines[offer_id]
            self._offers[offer_id] = OfferState.UNANSWERED
            events.append(ev.Unanswered(id=offer_id))
        return Turn([], events)

    def next_deadline(self) -> float | None:
        return min(self._deadlines.values(), default=None)

    # -- driver and core -> machine ------------------------------------

    def accept_connect(self, answer: str | None) -> Turn:
        """Let the link in, relaying funduq's answering signature.

        The proof is not verified here: the ticket store is core's, and a
        ticket is spent only once the key it names matches, so that a stranger
        who merely saw one cannot burn it. The driver takes `ConnectRequested`
        to `attach_provider` and brings back what it answered."""
        if self.state is not Link.VERIFYING:
            raise RuntimeError("nothing is waiting to be let in")
        if self._connecting is not None:
            self.public_key = self._connecting.public_key
            self.max_concurrent_runs = self._connecting.max_concurrent_runs
        self._connecting = None
        self.state = Link.OPEN
        return Turn([fr.ConnectOk(answer=answer)], [])

    def refuse_connect(self, reason: str) -> Turn:
        if self.state is not Link.VERIFYING:
            raise RuntimeError("nothing is waiting to be let in")
        self._connecting = None
        self.state = Link.CLOSED
        return Turn([fr.ConnectErr(reason=reason)], [])

    def offer(self, run: DeliveredRun, *, now: float) -> tuple[str, Turn]:
        """Hand `run` down and arm its deadline. Returns the offer's id, which
        is what a later `Answered` names.

        Each offer gets its own id rather than reusing the run's: a run
        declined once is offered again later, and an answer to the first offer
        arriving after the second was made would otherwise be read as an
        answer to the second."""
        if self.state is not Link.OPEN:
            raise RuntimeError("the link is not open")
        offer_id = self._claim_id()
        self._offers[offer_id] = OfferState.OFFERED
        self._deadlines[offer_id] = now + self._deliver_timeout
        return offer_id, Turn([fr.Offer(id=offer_id, run=run)], [])

    def cancel(self, run_id: str) -> Turn:
        """Ask the provider to stop. A request to the agent, not a verdict on
        the run — nothing here settles anything."""
        if self.state is not Link.OPEN:
            return EMPTY
        return Turn([fr.Cancel(run_id=run_id)], [])

    def reply_ok(self, id: str, payload: Any = None) -> Turn:
        self._queries.discard(id)
        return Turn([fr.Ok(id=id, payload=payload)], [])

    def reply_err(self, id: str, reason: str) -> Turn:
        self._queries.discard(id)
        return Turn([fr.Err(id=id, reason=reason)], [])

    # -- internals -----------------------------------------------------

    def _claim_id(self) -> str:
        self._next_id += 1
        return str(self._next_id)

    def _fail(self, reason: str) -> Turn:
        self.state = Link.CLOSED
        return Turn([], [ev.LinkFailed(reason=reason)])


def _verdict_of(frame: fr.Ok) -> bool | Refusal | None:
    if frame.verdict == "refused":
        return Refusal(frame.reason or "")
    if frame.verdict == "accepted":
        return True
    if frame.verdict == "declined":
        return False
    return None


def _settled(verdict: bool | Refusal) -> OfferState:
    if isinstance(verdict, Refusal):
        return OfferState.REFUSED
    return OfferState.CLAIMED if verdict else OfferState.DECLINED
