from __future__ import annotations

import pytest
from ag_ui.core import TextMessageContentEvent

from funduq_provider_sdk import (
    DeliveredRun,
    ProviderIdentity,
    Refusal,
    funduq_connect_payload,
    provider_connect_payload,
    verify_signature,
)
from funduq_provider_sdk.protocol import (
    Cancel,
    Cancelled,
    ConnectErr,
    ConnectOk,
    Err,
    Failed,
    Gone,
    LinkFailed,
    Malformed,
    Offer,
    Offered,
    Ok,
    Opened,
    ProviderSide,
    Refused,
    Replied,
    Report,
)
from funduq_provider_sdk.protocol.provider_side import Link


def _run() -> DeliveredRun:
    return DeliveredRun(
        run_id="r-1",
        agent_name="translator",
        run_input={
            "threadId": "t-1",
            "runId": "r-1",
            "state": None,
            "messages": [],
            "tools": [],
            "context": [],
            "forwardedProps": None,
        },
        thread_id="t-1",
    )


@pytest.fixture
def funduq() -> ProviderIdentity:
    return ProviderIdentity.generate()


@pytest.fixture
def provider() -> ProviderIdentity:
    return ProviderIdentity.generate()


def _answer(funduq: ProviderIdentity, ticket: str, nonce: str) -> ConnectOk:
    return ConnectOk(answer=funduq.sign(funduq_connect_payload(ticket, nonce)))


def _opened(provider: ProviderIdentity, funduq: ProviderIdentity) -> ProviderSide:
    machine = ProviderSide(provider, funduq_public_key=funduq.public_key)
    machine.connect(ticket="tk", nonce="n")
    machine.feed(_answer(funduq, "tk", "n"))
    return machine


def test_the_machine_signs_the_connect_so_the_recipient_cannot_be_left_out(
    provider: ProviderIdentity, funduq: ProviderIdentity
) -> None:
    """The pinned funduq key goes into the signed bytes, so a proof one funduq
    coaxes out cannot be relayed to attach at another. Handing the signing to
    the machine is what makes that impossible to skip or reorder."""
    machine = ProviderSide(provider, funduq_public_key=funduq.public_key)

    turn = machine.connect(ticket="tk", nonce="n")

    frame = turn.frames[0]
    assert frame.public_key == provider.public_key
    assert verify_signature(
        provider.public_key,
        frame.proof,
        provider_connect_payload(funduq.public_key, "tk", "n"),
    )


def test_a_wrong_answering_signature_closes_the_link_before_anything_is_produced(
    provider: ProviderIdentity, funduq: ProviderIdentity
) -> None:
    """The point of the pin is refusing to produce anything worth stealing for
    an imposter, so the check happens before the machine will emit a single
    other frame."""
    imposter = ProviderIdentity.generate()
    machine = ProviderSide(provider, funduq_public_key=funduq.public_key)
    machine.connect(ticket="tk", nonce="n")

    turn = machine.feed(_answer(imposter, "tk", "n"))

    assert isinstance(turn.events[0], LinkFailed)
    assert machine.state is Link.CLOSED
    assert turn.frames == []


def test_a_provider_that_pinned_nothing_accepts_whatever_answers(
    provider: ProviderIdentity,
) -> None:
    """A funduq with no identity key answers `None`, and only a provider that
    pinned a key treats that as a failure."""
    machine = ProviderSide(provider)
    machine.connect(ticket="tk", nonce="n")

    turn = machine.feed(ConnectOk(answer=None))

    assert turn.events == [Opened()]
    assert machine.state is Link.OPEN


def test_a_refused_admission_is_not_a_broken_protocol(
    provider: ProviderIdentity, funduq: ProviderIdentity
) -> None:
    machine = ProviderSide(provider, funduq_public_key=funduq.public_key)
    machine.connect(ticket="stale", nonce="n")

    turn = machine.feed(ConnectErr(reason="no live ticket for that key"))

    assert turn.events == [Refused(reason="no live ticket for that key")]


def test_funduq_speaking_before_answering_the_connect_breaks_the_link(
    provider: ProviderIdentity, funduq: ProviderIdentity
) -> None:
    machine = ProviderSide(provider, funduq_public_key=funduq.public_key)
    machine.connect(ticket="tk", nonce="n")

    turn = machine.feed(Offer(id="1", run=_run()))

    assert isinstance(turn.events[0], LinkFailed)


def test_an_offer_can_arrive_before_a_registration_has_been_answered(
    provider: ProviderIdentity, funduq: ProviderIdentity
) -> None:
    """The mirror of the funduq side's rule, and the reason it has to be
    stated on both: a provider that queued incoming offers until its own
    `Register` came back would stall against a broker that is already
    offering."""
    machine = _opened(provider, funduq)
    machine.register([{"name": "translator"}])

    turn = machine.feed(Offer(id="1", run=_run()))

    assert turn.events == [Offered(id="1", run=_run())]


@pytest.mark.parametrize(
    "verdict,expected",
    [(True, "accepted"), (False, "declined")],
)
def test_the_answer_carries_the_discriminant_the_wire_needs(
    provider: ProviderIdentity, funduq: ProviderIdentity, verdict: bool, expected: str
) -> None:
    machine = _opened(provider, funduq)
    machine.feed(Offer(id="1", run=_run()))

    turn = machine.answer("1", verdict)

    assert turn.frames == [Ok(id="1", verdict=expected)]


def test_a_permanent_refusal_carries_the_providers_own_words(
    provider: ProviderIdentity, funduq: ProviderIdentity
) -> None:
    machine = _opened(provider, funduq)
    machine.feed(Offer(id="1", run=_run()))

    turn = machine.answer("1", Refusal("this agent was retired"))

    assert turn.frames == [Ok(id="1", verdict="refused", reason="this agent was retired")]


def test_a_run_that_will_not_decode_is_refused_by_the_machine_not_the_agent(
    provider: ProviderIdentity, funduq: ProviderIdentity
) -> None:
    """Re-offering the same bytes can never succeed, so it is a permanent
    refusal rather than a decline — and it is a fact about the frame rather
    than about this provider, which is why the agent never hears about it."""
    machine = _opened(provider, funduq)

    turn = machine.feed(Malformed(id="1", reason="runInput did not validate"))

    assert turn.frames == [Ok(id="1", verdict="refused", reason="runInput did not validate")]
    assert turn.events == []


def test_an_event_is_dumped_without_the_nulls_a_default_dump_would_inject(
    provider: ProviderIdentity, funduq: ProviderIdentity
) -> None:
    """The rule moves from something every transport has to remember into
    something none of them can get wrong."""
    machine = _opened(provider, funduq)

    turn = machine.report("r-1", TextMessageContentEvent(message_id="m1", delta="hi"))

    body = turn.frames[0].event
    assert body["delta"] == "hi"
    assert "timestamp" not in body
    assert "rawEvent" not in body


def test_a_cancel_reaches_the_runtime_as_a_request(
    provider: ProviderIdentity, funduq: ProviderIdentity
) -> None:
    machine = _opened(provider, funduq)

    turn = machine.feed(Cancel(run_id="r-1"))

    assert turn.events == [Cancelled(run_id="r-1")]


def test_a_query_is_correlated_and_its_answer_comes_back_by_id(
    provider: ProviderIdentity, funduq: ProviderIdentity
) -> None:
    machine = _opened(provider, funduq)

    query_id, turn = machine.ask_thread_messages("t-1")

    assert turn.frames[0].thread_id == "t-1"
    assert machine.feed(Ok(id=query_id, payload=[])).events == [
        Replied(id=query_id, payload=[])
    ]


def test_a_rejected_request_comes_back_as_a_failure_not_a_reply(
    provider: ProviderIdentity, funduq: ProviderIdentity
) -> None:
    machine = _opened(provider, funduq)
    request_id, _ = machine.register([{"name": "translator"}])

    turn = machine.feed(Err(id=request_id, reason="registered no agents"))

    assert turn.events == [Failed(id=request_id, reason="registered no agents")]


def test_a_lost_connection_names_what_will_never_be_answered(
    provider: ProviderIdentity, funduq: ProviderIdentity
) -> None:
    machine = _opened(provider, funduq)
    machine.feed(Offer(id="1", run=_run()))
    query_id, _ = machine.ask_thread_messages("t-1")

    turn = machine.connection_lost()

    assert turn.events == [Gone(unanswered_offers=["1"], dropped_queries=[query_id])]


def test_answering_an_offer_that_is_not_outstanding_is_a_programming_error(
    provider: ProviderIdentity, funduq: ProviderIdentity
) -> None:
    machine = _opened(provider, funduq)

    with pytest.raises(RuntimeError):
        machine.answer("9", True)
