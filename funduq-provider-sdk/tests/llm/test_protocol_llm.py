from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from funduq_provider_sdk import ProviderIdentity, funduq_connect_payload
from funduq_provider_sdk.llm import (
    Abandon,
    Chunk,
    Chunked,
    Complete,
    CompletionAbandoned,
    CompletionBroke,
    CompletionEnd,
    CompletionEnded,
    CompletionFailed,
    CompletionRequested,
    DeliveredCompletion,
    FunduqLlmSide,
    ProviderLlmSide,
    decode,
)
from funduq_provider_sdk.protocol import (
    Connect,
    ConnectOk,
    Gone,
    LinkFailed,
    Opened,
    Register,
    encode,
)
from funduq_provider_sdk.protocol.base import Link


def _identity() -> ProviderIdentity:
    return ProviderIdentity(Ed25519PrivateKey.generate())


def _completion() -> DeliveredCompletion:
    return DeliveredCompletion(
        run_id="r-1",
        provider_key="pk",
        agent_name="translator",
        body={"model": "gpt-4o", "messages": []},
        llm_name="house",
    )


def _funduq_open() -> FunduqLlmSide:
    machine = FunduqLlmSide()
    machine.feed(Connect(public_key="pk", ticket="tk", nonce="n", proof="sig"))
    machine.accept_connect("answer")
    return machine


def _provider_open(provider: ProviderIdentity, funduq: ProviderIdentity) -> ProviderLlmSide:
    machine = ProviderLlmSide(provider, funduq_public_key=funduq.public_key)
    machine.connect(ticket="tk", nonce="n")
    machine.feed(ConnectOk(answer=funduq.sign(funduq_connect_payload("tk", "n"))))
    return machine


def test_the_opening_is_the_same_one_the_agent_link_uses() -> None:
    """Both link kinds share `FunduqLinkMachine`, so the handshake is stated
    once. Two copies would mean a fix to it landing twice, which is the defect
    this package exists to remove one level up."""
    machine = FunduqLlmSide()

    turn = machine.feed(Register(id="1", agents=[{"name": "house"}]))

    assert isinstance(turn.events[0], LinkFailed)
    assert machine.state is Link.CLOSED


def test_a_provider_pinning_a_key_opens_against_the_shared_ceremony() -> None:
    provider, funduq = _identity(), _identity()

    machine = _provider_open(provider, funduq)

    assert machine.state is Link.OPEN


def test_a_completion_is_asked_for_once_and_answered_with_a_stream() -> None:
    """The shape that makes this half different: no three-valued ack, and a
    lifetime that ends in exactly one of three ways."""
    machine = _funduq_open()

    request_id, turn = machine.complete(_completion())

    assert turn.frames == [Complete(id=request_id, completion=_completion())]

    first = machine.feed(Chunk(id=request_id, chunk={"id": "c1"}))
    ended = machine.feed(CompletionEnd(id=request_id))

    assert first.events == [Chunked(id=request_id, chunk={"id": "c1"})]
    assert ended.events == [CompletionEnded(id=request_id)]


def test_a_chunk_after_the_end_breaks_the_link() -> None:
    machine = _funduq_open()
    request_id, _ = machine.complete(_completion())
    machine.feed(CompletionEnd(id=request_id))

    turn = machine.feed(Chunk(id=request_id, chunk={"id": "c2"}))

    assert isinstance(turn.events[0], LinkFailed)


def test_ending_a_completion_that_was_never_asked_for_breaks_the_link() -> None:
    machine = _funduq_open()

    turn = machine.feed(CompletionEnd(id="9"))

    assert isinstance(turn.events[0], LinkFailed)


def test_a_structured_refusal_travels_intact_and_stays_distinguishable() -> None:
    """funduq never interprets a refusal — its vocabulary belongs to the
    provider and its callers — and `refusal` present is what separates the
    provider's policy working from a failure funduq observed."""
    machine = _funduq_open()
    request_id, _ = machine.complete(_completion())

    turn = machine.feed(
        CompletionFailed(id=request_id, reason="policy", refusal={"code": "over_budget"})
    )

    assert turn.events == [
        CompletionBroke(id=request_id, reason="policy", refusal={"code": "over_budget"})
    ]


def test_a_failure_with_no_refusal_is_funduqs_own_words() -> None:
    machine = _funduq_open()
    request_id, _ = machine.complete(_completion())

    turn = machine.feed(CompletionFailed(id=request_id, reason="upstream died"))

    assert turn.events[0].refusal is None


def test_a_caller_that_stopped_consuming_reaches_the_provider() -> None:
    """In-process this is `GeneratorExit` arriving in the handler. Over a wire
    there was nothing at all, so a provider went on generating into a consumer
    that had gone."""
    provider, funduq = _identity(), _identity()
    caller = _funduq_open()
    request_id, _ = caller.complete(_completion())
    serving = _provider_open(provider, funduq)
    serving.feed(Complete(id=request_id, completion=_completion()))

    turn = caller.abandon(request_id)
    seen = serving.feed(turn.frames[0])

    assert turn.frames == [Abandon(id=request_id)]
    assert seen.events == [CompletionAbandoned(id=request_id)]


def test_a_lost_connection_names_the_completions_that_will_never_finish() -> None:
    machine = _funduq_open()
    open_id, _ = machine.complete(_completion())
    closed_id, _ = machine.complete(_completion())
    machine.feed(CompletionEnd(id=closed_id))

    turn = machine.connection_lost()

    assert turn.events == [Gone(unanswered_offers=[open_id], dropped_queries=[])]


def test_the_provider_side_refuses_to_speak_for_a_completion_it_does_not_hold() -> None:
    provider, funduq = _identity(), _identity()
    machine = _provider_open(provider, funduq)

    with pytest.raises(RuntimeError):
        machine.chunk("9", {"id": "c1"})


def test_the_llm_vocabulary_is_its_own_and_does_not_answer_agent_frames() -> None:
    """An agent link and an LLM link are different connections to different
    rosters, so each has its own frame set. Two codecs is the shape of the
    thing rather than a workaround for one."""
    from funduq_provider_sdk.protocol import Malformed

    assert isinstance(decode(encode(Complete(id="1", completion=_completion()))), Complete)

    an_agent_frame = {"kind": "report", "runId": "r-1", "event": {"type": "X"}}

    assert isinstance(decode(an_agent_frame), Malformed)


def test_a_completion_request_that_will_not_decode_fails_rather_than_goes_quiet() -> None:
    """Saying so is what stops the caller waiting on a stream that will never
    start."""
    from funduq_provider_sdk.protocol import Malformed

    provider, funduq = _identity(), _identity()
    machine = _provider_open(provider, funduq)

    turn = machine.feed(Malformed(id="1", reason="body did not validate"))

    assert turn.frames == [CompletionFailed(id="1", reason="body did not validate")]
