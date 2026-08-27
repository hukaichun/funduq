from __future__ import annotations

from enum import Enum
from typing import Any

from funduq_provider_sdk.identity import (
    ProviderIdentity,
    funduq_connect_payload,
    new_nonce,
    verify_signature,
)
from funduq_provider_sdk.protocol import events as ev
from funduq_provider_sdk.protocol import frames as fr
from funduq_provider_sdk.protocol.turn import EMPTY, Turn
from funduq_provider_sdk.provider import Refusal


class Link(Enum):

    IDLE = "idle"
    CONNECTING = "connecting"
    OPEN = "open"
    CLOSED = "closed"


_VERDICTS = {True: "accepted", False: "declined"}


class ProviderSide:
    """A provider's half of the link, as a machine: frames in, frames and
    events out, no I/O and no clock.

    A transport mounts this between its connection and a `ProviderRuntime`
    instead of subclassing `FunduqLink` and hand-writing the bridge from
    frames to answers. `FunduqLink` remains the right surface for *provider
    authors*, who should never meet a frame; this is the surface for the
    people who were paying for the prose.
    """

    def __init__(self, identity: ProviderIdentity, *, funduq_public_key: str | None = None) -> None:
        """`funduq_public_key` is the key this provider pins. Leave it `None`
        to accept whatever answers — a choice, and one only a provider with
        nothing worth stealing should make."""
        self.state = Link.IDLE
        self.identity = identity
        self.funduq_public_key = funduq_public_key
        self._ticket: str | None = None
        self._nonce: str | None = None
        self._offers: set[str] = set()
        self._outstanding: set[str] = set()
        self._next_id = 0

    @property
    def public_key(self) -> str:
        return self.identity.public_key

    # -- driver -> machine ---------------------------------------------

    def connect(
        self,
        *,
        ticket: str,
        nonce: str | None = None,
        max_concurrent_runs: int | None = None,
    ) -> Turn:
        """Open the link, signing the ticket funduq issued out of band.

        The machine signs rather than taking a proof, because the one thing a
        transport author must not get wrong here is *what* is signed: the
        pinned funduq key goes into the bytes, so a proof one funduq coaxes
        out cannot be relayed to attach at another. Handing that step over
        means it cannot be skipped or reordered.
        """
        if self.state is not Link.IDLE:
            raise RuntimeError("this link has already been opened")
        self._ticket = ticket
        self._nonce = nonce or new_nonce()
        proof = self.identity.sign_connect(
            self.funduq_public_key or "", ticket, self._nonce
        )
        self.state = Link.CONNECTING
        return Turn(
            [
                fr.Connect(
                    public_key=self.public_key,
                    ticket=ticket,
                    nonce=self._nonce,
                    proof=proof,
                    max_concurrent_runs=max_concurrent_runs,
                )
            ],
            [],
        )

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
        return self._send(fr.Report(run_id=run_id, event=_as_json(event)))

    def finish(self, run_id: str) -> Turn:
        return self._send(fr.Finish(run_id=run_id))

    def register(self, agents: list[dict[str, Any]]) -> tuple[str, Turn]:
        """Publish this link's roster. Not registered is offline, and the names
        served are exactly the ones last published — a shorter list takes the
        omitted ones off."""
        return self._request(lambda i: fr.Register(id=i, agents=agents))

    def delete(self, name: str) -> tuple[str, Turn]:
        return self._request(lambda i: fr.Delete(id=i, name=name))

    def ask(self, method: str, args: dict[str, Any] | None = None) -> tuple[str, Turn]:
        return self._request(lambda i: fr.Query(id=i, method=method, args=args or {}))

    # -- transport -> machine ------------------------------------------

    def feed(self, frame: fr.Frame) -> Turn:
        if self.state is Link.CLOSED:
            return EMPTY
        if self.state is Link.IDLE:
            return self._fail("funduq spoke before this link was opened")
        if self.state is Link.CONNECTING:
            return self._connecting(frame)
        return self._opened(frame)

    def _connecting(self, frame: fr.Frame) -> Turn:
        if isinstance(frame, fr.ConnectErr):
            self.state = Link.CLOSED
            return Turn([], [ev.Refused(reason=frame.reason)])
        if not isinstance(frame, fr.ConnectOk):
            return self._fail("funduq spoke before answering the connect")
        if self.funduq_public_key is not None:
            payload = funduq_connect_payload(self._ticket or "", self._nonce or "")
            if frame.answer is None or not verify_signature(
                self.funduq_public_key, frame.answer, payload
            ):
                self.state = Link.CLOSED
                return Turn(
                    [],
                    [ev.LinkFailed(reason="the funduq answering this link is not the pinned one")],
                )
        self.state = Link.OPEN
        return Turn([], [ev.Opened()])

    def _opened(self, frame: fr.Frame) -> Turn:
        if isinstance(frame, fr.Offer):
            self._offers.add(frame.id)
            return Turn([], [ev.Offered(id=frame.id, run=frame.run)])
        if isinstance(frame, fr.Cancel):
            return Turn([], [ev.Cancelled(run_id=frame.run_id)])
        if isinstance(frame, fr.Ok):
            self._outstanding.discard(frame.id)
            return Turn([], [ev.Replied(id=frame.id, payload=frame.payload)])
        if isinstance(frame, fr.Err):
            self._outstanding.discard(frame.id)
            return Turn([], [ev.Failed(id=frame.id, reason=frame.reason)])
        if isinstance(frame, fr.Malformed):
            # An offered run that will not decode can never succeed on a
            # re-offer, so it is a permanent refusal rather than a decline.
            # It is a fact about the frame, not about this provider, which is
            # why the machine answers it and the agent never hears about it.
            if frame.id is None:
                return self._fail(f"funduq sent something that is not a frame: {frame.reason}")
            return Turn([fr.Ok(id=frame.id, verdict="refused", reason=frame.reason)], [])
        if isinstance(frame, fr.ConnectOk) or isinstance(frame, fr.ConnectErr):
            return self._fail("funduq answered a connect on a link already open")
        return self._fail(f"funduq sent a frame a provider does not answer: {frame.kind}")

    def connection_lost(self) -> Turn:
        if self.state is Link.CLOSED:
            return EMPTY
        self.state = Link.CLOSED
        gone = ev.Gone(
            unanswered_offers=sorted(self._offers), dropped_queries=sorted(self._outstanding)
        )
        self._offers.clear()
        self._outstanding.clear()
        return Turn([], [gone])

    # -- internals -----------------------------------------------------

    def _request(self, build) -> tuple[str, Turn]:
        if self.state is not Link.OPEN:
            raise RuntimeError("the link is not open")
        self._next_id += 1
        request_id = str(self._next_id)
        self._outstanding.add(request_id)
        return request_id, Turn([build(request_id)], [])

    def _send(self, frame: fr.Frame) -> Turn:
        if self.state is not Link.OPEN:
            raise RuntimeError("the link is not open")
        return Turn([frame], [])

    def _fail(self, reason: str) -> Turn:
        self.state = Link.CLOSED
        return Turn([], [ev.LinkFailed(reason=reason)])


def _as_json(event: Any) -> Any:
    dump = getattr(event, "model_dump", None)
    if dump is None:
        return event
    return dump(mode="json", by_alias=True, exclude_none=True)
