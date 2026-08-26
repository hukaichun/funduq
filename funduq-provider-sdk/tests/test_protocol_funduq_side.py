from __future__ import annotations

import pytest

from funduq_provider_sdk import DeliveredRun, Refusal
from funduq_provider_sdk.protocol import (
    Answered,
    Asking,
    Cancel,
    Connect,
    ConnectOk,
    ConnectRequested,
    Finish,
    FunduqSide,
    Gone,
    LinkFailed,
    Malformed,
    Offer,
    Ok,
    Query,
    Register,
    Registering,
    Report,
    Reported,
    Unanswered,
    WireFrame,
)
from funduq_provider_sdk.protocol.funduq_side import Link

TIMEOUT = 5.0


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


def _connect() -> Connect:
    return Connect(public_key="pk", ticket="tk", nonce="n", proof="sig")


def _opened(*, now: float = 0.0) -> FunduqSide:
    machine = FunduqSide(deliver_timeout=TIMEOUT)
    machine.feed(_connect(), now=now)
    machine.accept_connect("answer")
    return machine


def test_the_first_frame_on_a_link_must_be_connect() -> None:
    machine = FunduqSide(deliver_timeout=TIMEOUT)

    turn = machine.feed(Register(id="1", agents=[{"name": "translator"}]), now=0.0)

    assert isinstance(turn.events[0], LinkFailed)
    assert machine.state is Link.CLOSED


def test_the_open_relays_funduqs_answer_and_never_verifies_the_proof_itself() -> None:
    """Verification is core's: the ticket store is core's, and a ticket is
    spent only once the key it names matches — so a stranger who merely saw a
    live ticket cannot burn it with a garbage proof."""
    machine = FunduqSide(deliver_timeout=TIMEOUT)

    turn = machine.feed(_connect(), now=0.0)

    assert turn.events == [
        ConnectRequested(public_key="pk", ticket="tk", nonce="n", proof="sig")
    ]
    assert turn.frames == []

    answered = machine.accept_connect("funduq-signature")

    assert answered.frames == [ConnectOk(answer="funduq-signature")]
    assert machine.state is Link.OPEN
    assert machine.public_key == "pk"


def test_a_run_may_be_offered_before_any_registration_has_been_answered() -> None:
    """The machine holds no registration state, so this violates nothing.

    The window is not theoretical: core's roster goes live and nudges the
    broker before `register_agents` does its write and commit, which on
    Postgres is a network round trip. A machine that refused to offer until it
    had answered a `Register` would deadlock against its own broker.
    """
    machine = _opened()
    machine.feed(Register(id="1", agents=[{"name": "translator"}]), now=0.0)

    offer_id, turn = machine.offer(_run(), now=0.0)

    assert turn.frames == [Offer(id=offer_id, run=_run())]


def test_there_is_no_frame_that_yields_a_ticket() -> None:
    """"Do not fetch the ticket over the link" stops being a warning a
    transport author has to read and becomes something the vocabulary cannot
    say."""
    kinds = {
        field.default
        for member in WireFrame.__origin__.__args__
        for name, field in member.model_fields.items()
        if name == "kind"
    }

    assert not [kind for kind in kinds if "ticket" in kind]


@pytest.mark.parametrize(
    "verdict,expected",
    [
        (Ok(id="1", verdict="accepted"), True),
        (Ok(id="1", verdict="declined"), False),
        (Ok(id="1", verdict="refused", reason="cannot"), Refusal("cannot")),
    ],
)
def test_the_wires_discriminant_becomes_cores_vocabulary(verdict: Ok, expected) -> None:
    machine = _opened()
    machine.offer(_run(), now=0.0)

    turn = machine.feed(verdict, now=0.0)

    assert turn.events == [Answered(id="1", verdict=expected, late=False)]


def test_answering_the_same_offer_twice_breaks_the_link() -> None:
    machine = _opened()
    machine.offer(_run(), now=0.0)
    machine.feed(Ok(id="1", verdict="accepted"), now=0.0)

    turn = machine.feed(Ok(id="1", verdict="declined"), now=0.0)

    assert isinstance(turn.events[0], LinkFailed)
    assert machine.state is Link.CLOSED


def test_answering_an_offer_that_was_never_made_breaks_the_link() -> None:
    machine = _opened()

    turn = machine.feed(Ok(id="9", verdict="accepted"), now=0.0)

    assert isinstance(turn.events[0], LinkFailed)


def test_a_timed_out_offer_is_not_forgotten_and_a_later_answer_is_late_not_illegal() -> None:
    """Forgetting the id is the instinct, and it turns a provider's late
    honesty into a protocol error.

    Core counts an unanswered offer against the provider and hands the run
    back; an answer arriving afterwards is evidence about that provider, so it
    is surfaced rather than swallowed.
    """
    machine = _opened()
    offer_id, _ = machine.offer(_run(), now=0.0)

    assert machine.next_deadline() == TIMEOUT
    assert machine.timeout(TIMEOUT - 0.1).events == []

    expired = machine.timeout(TIMEOUT)

    assert expired.events == [Unanswered(id=offer_id)]
    assert machine.next_deadline() is None

    late = machine.feed(Ok(id=offer_id, verdict="accepted"), now=TIMEOUT + 1)

    assert late.events == [Answered(id=offer_id, verdict=True, late=True)]
    assert machine.state is Link.OPEN


def test_events_and_finishes_are_not_gated_on_the_offer_table() -> None:
    """The tempting check, and the one that must not be written.

    Events are addressed by run, and whether a key may speak for a run is
    core's question — answered against `claimed_by`, which includes letting a
    provider claim late by producing for a run funduq had given up waiting
    for. Gating this here would make that path unreachable over a wire while
    leaving it working in-process.
    """
    machine = _opened()

    reported = machine.feed(Report(run_id="never-offered", event={"type": "X"}), now=0.0)
    finished = machine.feed(Finish(run_id="never-offered"), now=0.0)

    assert reported.events == [Reported(run_id="never-offered", event={"type": "X"})]
    assert finished.events[0].run_id == "never-offered"
    assert machine.state is Link.OPEN


def test_a_second_connect_on_an_open_link_breaks_it() -> None:
    machine = _opened()

    turn = machine.feed(_connect(), now=0.0)

    assert isinstance(turn.events[0], LinkFailed)


def test_a_frame_that_did_not_decode_is_answered_rather_than_dropped() -> None:
    machine = _opened()

    turn = machine.feed(Malformed(id="4", reason="not a run"), now=0.0)

    assert turn.frames[0].id == "4"
    assert machine.state is Link.OPEN


def test_a_lost_connection_says_the_fact_and_draws_no_conclusion() -> None:
    """funduq never decides on a provider's behalf. The machine reports what
    it observed — this link is gone, these offers were never answered — and
    what a claimed run becomes is core's verdict."""
    machine = _opened()
    offer_id, _ = machine.offer(_run(), now=0.0)
    machine.feed(Query(id="q1", method="thread_messages", args={"thread_id": "t-1"}), now=0.0)

    turn = machine.connection_lost()

    assert turn.events == [Gone(unanswered_offers=[offer_id], dropped_queries=["q1"])]
    assert not any(isinstance(event, Answered) for event in turn.events)
    assert machine.state is Link.CLOSED


def test_a_query_surfaces_for_the_driver_to_answer() -> None:
    machine = _opened()

    turn = machine.feed(
        Query(id="q1", method="thread_messages", args={"thread_id": "t-1"}), now=0.0
    )

    assert turn.events == [
        Asking(id="q1", method="thread_messages", args={"thread_id": "t-1"})
    ]
    assert machine.reply_ok("q1", payload=[]).frames[0].id == "q1"


def test_a_registration_surfaces_for_the_driver_to_apply() -> None:
    machine = _opened()

    turn = machine.feed(Register(id="1", agents=[{"name": "translator"}]), now=0.0)

    assert turn.events == [Registering(id="1", agents=[{"name": "translator"}])]


def test_cancelling_is_a_request_and_settles_nothing() -> None:
    machine = _opened()
    machine.offer(_run(), now=0.0)
    machine.feed(Ok(id="1", verdict="accepted"), now=0.0)

    turn = machine.cancel("r-1")

    assert turn.frames == [Cancel(run_id="r-1")]
    assert turn.events == []


def test_offering_on_a_link_that_is_not_open_is_a_programming_error() -> None:
    machine = FunduqSide(deliver_timeout=TIMEOUT)

    with pytest.raises(RuntimeError):
        machine.offer(_run(), now=0.0)
