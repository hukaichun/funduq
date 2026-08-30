"""The LLM link's state machine — the peer of `funduq_provider_sdk.protocol`.

The opening is the same one, shared rather than restated: `FunduqLinkMachine`
and `ProviderLinkMachine` carry the handshake and the roster verbs, and only
the work differs.

Both kinds of work are answered with a **stream** — a run's answer is its
events and then its finish. Two things differ, and neither is that:

**A run is admitted first.** An offer is answered three ways before any output
exists, and funduq holds the next utterance of that conversation until the run
is claimed. A completion has no admission step at all: it is assumed taken,
and can only fail afterwards. So this half has no three-valued ack, and no
delivery deadline to go with one.

**A run outlives any one offer of it; a completion does not.** A run declined
once is offered again under a new id, and a provider may claim one late by
producing for it, so its output is addressed by `runId` and the machine
deliberately does not gate it. A completion is asked for exactly once, so its
chunks are addressed by the request's own id — and gating *those* on the table
is right, which is why the two halves differ here rather than agreeing by
accident.

It lives under `llm/` because it names `DeliveredCompletion`, which reaches
openai's types: an agent provider must not pay that import, which is why the
completion half is an extra.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import Field, TypeAdapter

from funduq_provider_sdk.llm.provider import DeliveredCompletion
from funduq_provider_sdk.protocol import events as ev
from funduq_provider_sdk.protocol import frames as fr
from funduq_provider_sdk.protocol.base import FunduqLinkMachine, Link, ProviderLinkMachine
from funduq_provider_sdk.protocol.codec import decode as _decode
from funduq_provider_sdk.protocol.provider_side import as_json
from funduq_provider_sdk.protocol.turn import Turn


class RegisterLlm(fr.Frame):
    """Publish this link's LLM offerings.

    Its own frame rather than the agent link's `Register`, because the shapes
    genuinely differ: agents are published as records, offerings as names plus
    one metadata document that describes the link's terms. Sharing a frame
    would have meant either dropping the metadata or carrying a field that is
    always empty on one side."""

    kind: Literal["register.llm"] = "register.llm"
    id: str
    names: list[str]
    metadata: dict[str, Any] | None = None


class Complete(fr.Frame):
    """One completion request handed down. `completion` is the published
    delivered-completion envelope, nested rather than restated."""

    kind: Literal["complete"] = "complete"
    id: str
    completion: DeliveredCompletion


class Chunk(fr.Frame):
    """One chunk of an answer.

    `chunk` is `Any` for the same reason `Report.event` is: funduq is a relay,
    and openai's types are the authority on what is inside. Nothing here
    parses it."""

    kind: Literal["chunk"] = "chunk"
    id: str
    chunk: Any = None


class CompletionEnd(fr.Frame):

    kind: Literal["completion.end"] = "completion.end"
    id: str


class CompletionFailed(fr.Frame):
    """A completion that stopped before it finished.

    `refusal` present means the provider's own policy answered — its
    vocabulary, relayed intact, never interpreted. Absent means funduq
    observed a failure and says so in its own words. That distinction is the
    one the quality counters record, and neither is a judgement."""

    kind: Literal["completion.failed"] = "completion.failed"
    id: str
    reason: str = ""
    refusal: dict[str, Any] | None = None


LlmWireFrame = Annotated[
    Union[
        fr.Connect,
        fr.ConnectOk,
        fr.ConnectErr,
        fr.ThreadMessages,
        fr.Delete,
        RegisterLlm,
        fr.Ok,
        fr.Err,
        Complete,
        Chunk,
        CompletionEnd,
        CompletionFailed,
    ],
    Field(discriminator="kind"),
]

_LLM_FRAMES: TypeAdapter[Any] = TypeAdapter(LlmWireFrame)


def decode(payload: Any) -> fr.Frame:
    """The LLM link's own vocabulary. See `protocol.codec.decode`."""
    return _decode(payload, frames=_LLM_FRAMES)


class RegisteringLlm(ev.Event):

    id: str
    names: list[str]
    metadata: dict[str, Any] | None = None


class CompletionRequested(ev.Event):

    id: str
    completion: DeliveredCompletion


class Chunked(ev.Event):

    id: str
    chunk: Any = None


class CompletionEnded(ev.Event):

    id: str


class CompletionBroke(ev.Event):
    """A completion ended badly. `refusal` present is the provider's policy
    answering; absent is a failure funduq observed."""

    id: str
    reason: str = ""
    refusal: dict[str, Any] | None = None


class Streaming(Enum):

    OPEN = "open"
    ENDED = "ended"


class FunduqLlmSide(FunduqLinkMachine):
    """funduq's half of an LLM link.

    `next_deadline()` is always `None`, and that is deliberate rather than
    unfinished: the clock that used to sit here was removed for blaming a slow
    model for its own slowness, and how long an attached provider takes is its
    own business. Liveness is a fact funduq holds — whether the link is still
    here — not a deduction from how long a chunk took.
    """

    def __init__(self) -> None:
        super().__init__()
        self._streams: dict[str, Streaming] = {}

    def complete(self, completion: DeliveredCompletion) -> tuple[str, Turn]:
        if self.state is not Link.OPEN:
            raise RuntimeError("the link is not open")
        request_id = self._claim_id()
        self._streams[request_id] = Streaming.OPEN
        return request_id, Turn([Complete(id=request_id, completion=completion)], [])

    def _work(self, frame: fr.Frame, *, now: float) -> Turn:
        if isinstance(frame, RegisterLlm):
            return Turn(
                [], [RegisteringLlm(id=frame.id, names=frame.names, metadata=frame.metadata)]
            )
        if isinstance(frame, Chunk):
            if self._streams.get(frame.id) is not Streaming.OPEN:
                return self._fail(f"sent a chunk for {frame.id}, which is not streaming")
            return Turn([], [Chunked(id=frame.id, chunk=frame.chunk)])
        if isinstance(frame, CompletionEnd):
            if self._streams.get(frame.id) is not Streaming.OPEN:
                return self._fail(f"ended {frame.id}, which is not streaming")
            self._streams[frame.id] = Streaming.ENDED
            return Turn([], [CompletionEnded(id=frame.id)])
        if isinstance(frame, CompletionFailed):
            if self._streams.get(frame.id) is not Streaming.OPEN:
                return self._fail(f"failed {frame.id}, which is not streaming")
            self._streams[frame.id] = Streaming.ENDED
            return Turn(
                [],
                [CompletionBroke(id=frame.id, reason=frame.reason, refusal=frame.refusal)],
            )
        if isinstance(frame, fr.Malformed):
            if frame.id is None:
                return self._fail(f"sent something that is not a frame: {frame.reason}")
            return Turn([fr.Err(id=frame.id, reason=frame.reason)], [])
        return self._fail(f"sent a frame an LLM link does not answer: {frame.kind}")

    def _abandoned(self) -> list[str]:
        return sorted(i for i, s in self._streams.items() if s is Streaming.OPEN)


class ProviderLlmSide(ProviderLinkMachine):
    """An LLM provider's half of the link."""

    def __init__(self, identity, *, funduq_public_key: str | None = None) -> None:
        super().__init__(identity, funduq_public_key=funduq_public_key)
        self._streams: set[str] = set()

    def register(
        self, names: list[str], metadata: dict[str, Any] | None = None
    ) -> tuple[str, Turn]:
        """Publish this link's offerings. Not registered is offline, the same
        rule the agent roster lives under."""
        return self._request(lambda i: RegisterLlm(id=i, names=names, metadata=metadata))

    def _work(self, frame: fr.Frame) -> Turn:
        if isinstance(frame, Complete):
            self._streams.add(frame.id)
            return Turn([], [CompletionRequested(id=frame.id, completion=frame.completion)])
        if isinstance(frame, fr.Malformed):
            # A completion request that will not decode cannot be served, and
            # saying so as a failure rather than a silence is what stops the
            # caller waiting on a stream that will never start.
            if frame.id is None:
                return self._fail(f"funduq sent something that is not a frame: {frame.reason}")
            return Turn([CompletionFailed(id=frame.id, reason=frame.reason)], [])
        return self._fail(f"funduq sent a frame an LLM provider does not answer: {frame.kind}")

    def _abandoned(self) -> list[str]:
        abandoned = sorted(self._streams)
        self._streams.clear()
        return abandoned

    def chunk(self, request_id: str, chunk: Any) -> Turn:
        self._require(request_id)
        return self._send(Chunk(id=request_id, chunk=as_json(chunk)))

    def end(self, request_id: str) -> Turn:
        self._require(request_id)
        self._streams.discard(request_id)
        return self._send(CompletionEnd(id=request_id))

    def fail(self, request_id: str, reason: str, refusal: dict[str, Any] | None = None) -> Turn:
        """End a completion badly.

        A structured `refusal` travels intact — this package defines the
        envelope, never the vocabulary inside it, which belongs to the
        provider and its callers."""
        self._require(request_id)
        self._streams.discard(request_id)
        return self._send(CompletionFailed(id=request_id, reason=reason, refusal=refusal))

    def _require(self, request_id: str) -> None:
        if request_id not in self._streams:
            raise RuntimeError(f"completion {request_id} is not in flight")
