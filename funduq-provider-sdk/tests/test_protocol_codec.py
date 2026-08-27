from __future__ import annotations

from funduq_provider_sdk import DeliveredRun
from funduq_provider_sdk.protocol import (
    Cancel,
    Malformed,
    Offer,
    Ok,
    Report,
    decode,
    encode,
)


def _run(**overrides) -> DeliveredRun:
    payload = {
        "threadId": "t-1",
        "runId": "r-1",
        "state": None,
        "messages": [],
        "tools": [],
        "context": [],
        "forwardedProps": None,
    }
    payload.update(overrides)
    return DeliveredRun(
        run_id="r-1", agent_name="translator", run_input=payload, thread_id="t-1"
    )


def test_frames_go_out_camelcase_and_come_back_identical() -> None:
    """The alias mapping is written once, in the models, rather than once per
    transport. A hand-written mapping is what `contract-vectors.json` exists to
    make unnecessary, and it is how funduq once ended up answering a protocol's
    old method names."""
    frame = Cancel(run_id="r-1")

    wire = encode(frame)

    assert wire == {"kind": "cancel", "runId": "r-1"}
    assert decode(wire) == frame


def test_an_offer_carries_the_published_delivered_run_envelope() -> None:
    wire = encode(Offer(id="1", run=_run()))

    assert wire["run"]["runId"] == "r-1"
    assert wire["run"]["agentName"] == "translator"
    assert decode(wire).run == _run()


def test_the_verdict_travels_as_a_discriminant_not_as_a_bare_bit() -> None:
    """A transport that collapses the three values into one re-creates a bug
    funduq already had: runs re-offered forever, reading `queued` from every
    vantage point while only the provider's log knew."""
    assert encode(Ok(id="1", verdict="declined"))["verdict"] == "declined"
    assert encode(Ok(id="1", verdict="refused", reason="no"))["reason"] == "no"
    assert decode(encode(Ok(id="1", payload=["a"]))).verdict is None


def test_the_frame_dump_does_not_strip_nulls_and_the_envelope_survives_it() -> None:
    """`exclude_none` is right for a relayed event and wrong for a frame, and
    this is where the two rules meet.

    `RunAgentInput` has required fields that are legitimately `None` —
    `state`, `forwardedProps` — and the published delivered-run envelope is
    `model_dump(by_alias=True)`, the form the vectors pin. A frame dump that
    stripped nulls would delete them, and the far side would answer a
    perfectly good run with a permanent refusal because its input no longer
    validates. Measured, not reasoned about: this test failed the first time
    the codec carried the flag.
    """
    wire = encode(Offer(id="1", run=_run()))

    assert wire["run"]["runInput"]["state"] is None
    assert wire["run"]["runInput"]["forwardedProps"] is None
    assert decode(wire).run == _run()


def test_a_relayed_event_keeps_the_nulls_the_agent_meant_to_send() -> None:
    """The event body is the one field the machine must not touch. An event
    whose `type` funduq has never heard of is relayed untouched, and so is a
    null inside it — the `exclude_none` that belongs to this path is applied
    to the agent's typed event in `ProviderSide.report`, before it becomes an
    opaque body."""
    event = {"type": "CUSTOM", "delta": None, "nested": {"a": None}}

    wire = encode(Report(run_id="r-1", event=event))

    assert wire["event"] == event


def test_something_that_is_not_a_frame_decodes_to_malformed_keeping_its_id() -> None:
    """Decoding never raises and never answers.

    The id is dug out of the payload on purpose: with it the machine can
    answer the request that failed, and without it the far side waits forever
    on a request nothing will ever answer.
    """
    result = decode({"kind": "offer", "id": "7", "run": {"runId": "r-1"}})

    assert isinstance(result, Malformed)
    assert result.id == "7"

    assert decode("not even a mapping").id is None
