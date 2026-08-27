from __future__ import annotations

from typing import Any

from funduq_provider_sdk.protocol import events as ev
from funduq_provider_sdk.protocol import frames as fr
from funduq_provider_sdk.protocol.base import Link, ProviderLinkMachine
from funduq_provider_sdk.protocol.turn import Turn
from funduq_provider_sdk.provider import Refusal, Registration

__all__ = ["ProviderSide", "Link"]

_VERDICTS = {True: "accepted", False: "declined"}


class ProviderSide(ProviderLinkMachine):
    """A provider's half of an agent link, as a machine: frames in, frames and
    events out, no I/O and no clock.

    A transport mounts this between its connection and a `ProviderRuntime`
    instead of subclassing `FunduqLink` and hand-writing the bridge from
    frames to answers. `FunduqLink` remains the right surface for *provider
    authors*, who should never meet a frame; this is the surface for the
    people who were paying for the prose.
    """

    def __init__(self, identity, *, funduq_public_key: str | None = None) -> None:
        super().__init__(identity, funduq_public_key=funduq_public_key)
        self._offers: set[str] = set()

    def register(self, agents: list[Registration | dict[str, Any]]) -> tuple[str, Turn]:
        """Publish this link's agents. Not registered is offline, and the names
        served are exactly the ones last published — a shorter list takes the
        omitted ones off.

        A dict is accepted and validated into a `Registration` on the way
        through — `AgentHandle.as_registration()` still produces one — so a
        misspelt key is refused here instead of being dropped in silence by
        core."""
        return self._request(lambda i: fr.Register(id=i, agents=agents))

    def _work(self, frame: fr.Frame) -> Turn:
        if isinstance(frame, fr.Offer):
            self._offers.add(frame.id)
            return Turn([], [ev.Offered(id=frame.id, run=frame.run)])
        if isinstance(frame, fr.Cancel):
            return Turn([], [ev.Cancelled(run_id=frame.run_id)])
        if isinstance(frame, fr.Malformed):
            # An offered run that will not decode can never succeed on a
            # re-offer, so it is a permanent refusal rather than a decline.
            # It is a fact about the frame, not about this provider, which is
            # why the machine answers it and the agent never hears about it.
            if frame.id is None:
                return self._fail(f"funduq sent something that is not a frame: {frame.reason}")
            return Turn([fr.Ok(id=frame.id, verdict="refused", reason=frame.reason)], [])
        return self._fail(f"funduq sent a frame a provider does not answer: {frame.kind}")

    def _abandoned(self) -> list[str]:
        abandoned = sorted(self._offers)
        self._offers.clear()
        return abandoned

    def answer(self, offer_id: str, verdict: bool | Refusal) -> Turn:
        """Answer an offer: accepted, declined-because-full, or permanently
        refused.

        The answer is a receipt and must come from the provider's own state —
        whether the run arrived, whether there is room, whether the input
        parses are all known the moment it lands. funduq holds the next
        utterance of the same conversation until this answer returns, which is
        how a thread's delivery order survives a transport that guarantees
        none, so a link that waits for the agent to start turns a round trip
        into the agent's startup time."""
        if offer_id not in self._offers:
            raise RuntimeError(f"offer {offer_id} is not outstanding")
        self._offers.discard(offer_id)
        if isinstance(verdict, Refusal):
            return Turn([fr.Ok(id=offer_id, verdict="refused", reason=verdict.reason)], [])
        return Turn([fr.Ok(id=offer_id, verdict=_VERDICTS[bool(verdict)])], [])

    def report(self, run_id: str, event: Any) -> Turn:
        """Relay one event.

        The dump happens here so no transport has to remember it: a typed
        event dumped without `exclude_none=True` injects `timestamp: null` and
        `rawEvent: null` into the caller's stream, and with it the round trip
        is byte-identical to what the agent produced."""
        return self._send(fr.Report(run_id=run_id, event=as_json(event)))

    def finish(self, run_id: str) -> Turn:
        return self._send(fr.Finish(run_id=run_id))


def as_json(payload: Any) -> Any:
    """A typed payload as the wire carries it, or whatever it already was.

    `exclude_none=True` is the half that belongs *here* and not in the frame
    dump — see `codec.encode` for the other half and why the two pull opposite
    ways."""
    dump = getattr(payload, "model_dump", None)
    if dump is None:
        return payload
    return dump(mode="json", by_alias=True, exclude_none=True)
