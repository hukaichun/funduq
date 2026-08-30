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
    """funduq's half of an agent link, as a machine: frames in, frames and events out."""

    def __init__(self, *, deliver_timeout: float) -> None:
        """`deliver_timeout` is core's own `deliver_timeout_seconds`, handed in rather than defaulted here: one number, one definition, and a machine that disagreed with the broker it serves would hand a run back while the broker was still waiting for it."""
        super().__init__()
        self._deliver_timeout = deliver_timeout
        self._offers: dict[str, OfferState] = {}
        self._deadlines: dict[str, float] = {}

    def _work(self, frame: fr.Frame, *, now: float) -> Turn:
        if isinstance(frame, fr.Register):
            return Turn([], [ev.Registering(id=frame.id, agents=frame.agents)])
        if isinstance(frame, fr.Report):
            # Deliberately not checked against `_offers`.
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

    def _abandoned(self) -> list[str]:
        abandoned = sorted(i for i, s in self._offers.items() if s is OfferState.OFFERED)
        self._deadlines.clear()
        return abandoned

    def timeout(self, now: float) -> Turn:
        """Fires every armed deadline `now` has passed."""
        events: list[ev.Event] = []
        for offer_id in sorted(i for i, at in self._deadlines.items() if at <= now):
            del self._deadlines[offer_id]
            self._offers[offer_id] = OfferState.UNANSWERED
            events.append(ev.Unanswered(id=offer_id))
        return Turn([], events)

    def next_deadline(self) -> float | None:
        return min(self._deadlines.values(), default=None)

    def offer(self, run: DeliveredRun, *, now: float) -> tuple[str, Turn]:
        """Hand `run` down and arm its deadline."""
        if self.state is not Link.OPEN:
            raise RuntimeError("the link is not open")
        offer_id = self._claim_id()
        self._offers[offer_id] = OfferState.OFFERED
        self._deadlines[offer_id] = now + self._deliver_timeout
        return offer_id, Turn([fr.Offer(id=offer_id, run=run)], [])

    def cancel(self, run_id: str) -> Turn:
        """Ask the provider to stop."""
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
