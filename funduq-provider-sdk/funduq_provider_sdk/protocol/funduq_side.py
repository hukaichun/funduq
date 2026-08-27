from __future__ import annotations

from enum import Enum

from funduq_provider_sdk.protocol import events as ev
from funduq_provider_sdk.protocol import frames as fr
from funduq_provider_sdk.protocol.base import FunduqLinkMachine, Link
from funduq_provider_sdk.protocol.turn import EMPTY, Turn
from funduq_provider_sdk.provider import DeliveredRun, Refusal

__all__ = ["FunduqSide", "Link", "OfferState"]


class OfferState(Enum):

    OFFERED = "offered"
    CLAIMED = "claimed"
    DECLINED = "declined"
    REFUSED = "refused"
    UNANSWERED = "unanswered"


_SETTLED = (OfferState.CLAIMED, OfferState.DECLINED, OfferState.REFUSED)


class FunduqSide(FunduqLinkMachine):
    """funduq's half of an agent link, as a machine: frames in, frames and
    events out.

    It performs no I/O and reads no clock — time enters as `now` and leaves as
    `next_deadline()`. That is what sans-io buys here, and it is what makes
    every ordering testable as an ordered script instead of a sleep.

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
        super().__init__()
        self._deliver_timeout = deliver_timeout
        self._offers: dict[str, OfferState] = {}
        self._deadlines: dict[str, float] = {}
        self.received: dict[str, int] = {}

    def _work(self, frame: fr.Frame, *, now: float) -> Turn:
        if isinstance(frame, fr.Register):
            return Turn([], [ev.Registering(id=frame.id, agents=frame.agents)])
        if isinstance(frame, fr.Report):
            # Deliberately not checked against `_offers`. Events are addressed
            # by run, and whether this key may speak for that run is core's
            # question, answered against `claimed_by` — which includes letting
            # a provider claim late by producing for a run funduq had given up
            # waiting for. A machine that gated this on its own table would
            # look obviously right and would make that path unreachable.
            if frame.seq is not None:
                # Advanced on emit rather than on core's answer. A `False` from
                # `report_event` means the run is unknown or held by someone
                # else, and in both of those a watermark is moot — while an
                # extra call per event, on the hottest path there is, would buy
                # nothing.
                self.received[frame.run_id] = max(
                    frame.seq, self.received.get(frame.run_id, 0)
                )
            return Turn(
                [], [ev.Reported(run_id=frame.run_id, event=frame.event, seq=frame.seq)]
            )
        if isinstance(frame, fr.Finish):
            return Turn([], [ev.Finished(run_id=frame.run_id)])
        if isinstance(frame, fr.Resume):
            return Turn([], [ev.Resuming(id=frame.id, run_ids=frame.run_ids)])
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

    def _abandoned(self) -> list[str]:
        abandoned = sorted(i for i, s in self._offers.items() if s is OfferState.OFFERED)
        self._deadlines.clear()
        return abandoned

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

    def resumed(self, id: str, *, still_held: list[str], unknown: list[str]) -> Turn:
        """Answer a resume: the watermark for each run still held, and the
        names of the ones that are not.

        Which runs survived is core's answer, not this machine's — the driver
        asks it and hands the split back. What the machine contributes is the
        only thing it is the authority on: how much of each it actually saw.
        """
        return Turn(
            [
                fr.Resumed(
                    id=id,
                    watermarks={run_id: self.received.get(run_id, 0) for run_id in still_held},
                    unknown=unknown,
                )
            ],
            [],
        )

    def cancel(self, run_id: str) -> Turn:
        """Ask the provider to stop. A request to the agent, not a verdict on
        the run — nothing here settles anything."""
        if self.state is not Link.OPEN:
            return EMPTY
        return Turn([fr.Cancel(run_id=run_id)], [])


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
