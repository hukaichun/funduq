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


class Link(Enum):

    IDLE = "idle"
    AWAITING_CONNECT = "awaiting_connect"
    CONNECTING = "connecting"
    VERIFYING = "verifying"
    OPEN = "open"
    CLOSED = "closed"


class FunduqLinkMachine:
    """The half of funduq's side that both link kinds share: the handshake, the
    roster verbs, and replying to a request.

    Agents and completions arrive over different links, to different rosters,
    with different work on them — but the *opening* is identical, deliberately
    so: in-process is not trusted, and neither roster gets a shortcut the other
    does not. Stating it once is the same judgement core makes with `_Roster`,
    and for the same reason: two copies means a handshake fix has to land
    twice, which is the defect this package exists to remove one level up.

    A subclass supplies `_work`, which sees every frame the base does not
    answer, and `_abandoned`, which names what a lost connection will never
    answer. **Registration is a subclass's**, because it is the one roster verb
    whose shape differs: agents are published as records, LLM offerings as
    names plus one metadata document. Deleting and querying are the same shape
    for both and stay here.
    """

    def __init__(self) -> None:
        self.state = Link.AWAITING_CONNECT
        self.public_key: str | None = None
        self.max_concurrent_runs: int | None = None
        self._queries: set[str] = set()
        self._next_id = 0
        self._connecting: fr.Connect | None = None

    # -- transport -> machine ------------------------------------------

    def feed(self, frame: fr.Frame, *, now: float = 0.0) -> Turn:
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
        return self._opened(frame, now=now)

    def _opened(self, frame: fr.Frame, *, now: float) -> Turn:
        if isinstance(frame, fr.Connect):
            return self._fail("tried to connect on a link that is already open")
        if isinstance(frame, fr.Delete):
            return Turn([], [ev.Deleting(id=frame.id, name=frame.name)])
        if isinstance(frame, fr.ThreadMessages):
            self._queries.add(frame.id)
            return Turn(
                [],
                [
                    ev.AskingThreadMessages(
                        id=frame.id, thread_id=frame.thread_id, limit=frame.limit
                    )
                ],
            )
        return self._work(frame, now=now)

    def _work(self, frame: fr.Frame, *, now: float) -> Turn:
        raise NotImplementedError

    def _abandoned(self) -> list[str]:
        return []

    def connection_lost(self) -> Turn:
        """The connection ended. Says the fact and draws no conclusion: what an
        in-flight piece of work becomes is core's verdict, not this
        machine's."""
        if self.state is Link.CLOSED:
            return EMPTY
        self.state = Link.CLOSED
        abandoned = self._abandoned()
        dropped = sorted(self._queries)
        self._queries.clear()
        return Turn([], [ev.Gone(unanswered_offers=abandoned, dropped_queries=dropped)])

    def next_deadline(self) -> float | None:
        return None

    def timeout(self, now: float) -> Turn:
        return EMPTY

    # -- driver -> machine ---------------------------------------------

    def accept_connect(self, answer: str | None) -> Turn:
        """Let the link in, relaying funduq's answering signature.

        The proof is not verified here: the ticket store is core's, and a
        ticket is spent only once the key it names matches, so a stranger who
        merely saw one cannot burn it. The driver takes `ConnectRequested` to
        `attach_provider` and brings back what it answered."""
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


class ProviderLinkMachine:
    """The provider's half of the same shared opening.

    The machine signs the connect rather than taking a proof, because the one
    thing a transport author must not get wrong there is *what* is signed: the
    pinned funduq key goes into the bytes, so a proof one funduq coaxes out
    cannot be relayed to attach at another. And "check the answer before
    producing anything" is structural — `CONNECTING` emits no other frame.
    """

    def __init__(
        self, identity: ProviderIdentity, *, funduq_public_key: str | None = None
    ) -> None:
        self.state = Link.IDLE
        self.identity = identity
        self.funduq_public_key = funduq_public_key
        self._ticket: str | None = None
        self._nonce: str | None = None
        self._outstanding: set[str] = set()
        self._next_id = 0

    @property
    def public_key(self) -> str:
        return self.identity.public_key

    def connect(
        self,
        *,
        ticket: str,
        nonce: str | None = None,
        max_concurrent_runs: int | None = None,
    ) -> Turn:
        if self.state is not Link.IDLE:
            raise RuntimeError("this link has already been opened")
        self._ticket = ticket
        self._nonce = nonce or new_nonce()
        proof = self.identity.sign_connect(self.funduq_public_key or "", ticket, self._nonce)
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
        if isinstance(frame, fr.Ok):
            self._outstanding.discard(frame.id)
            return Turn([], [ev.Replied(id=frame.id, payload=frame.payload)])
        if isinstance(frame, fr.Err):
            self._outstanding.discard(frame.id)
            return Turn([], [ev.Failed(id=frame.id, reason=frame.reason)])
        if isinstance(frame, (fr.ConnectOk, fr.ConnectErr)):
            return self._fail("funduq answered a connect on a link already open")
        return self._work(frame)

    def _work(self, frame: fr.Frame) -> Turn:
        raise NotImplementedError

    def _abandoned(self) -> list[str]:
        return []

    def connection_lost(self) -> Turn:
        if self.state is Link.CLOSED:
            return EMPTY
        self.state = Link.CLOSED
        gone = ev.Gone(
            unanswered_offers=self._abandoned(), dropped_queries=sorted(self._outstanding)
        )
        self._outstanding.clear()
        return Turn([], [gone])

    def delete(self, name: str) -> tuple[str, Turn]:
        return self._request(lambda i: fr.Delete(id=i, name=name))

    def ask_thread_messages(
        self, thread_id: str, *, limit: int | None = None
    ) -> tuple[str, Turn]:
        return self._request(lambda i: fr.ThreadMessages(id=i, thread_id=thread_id, limit=limit))

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
