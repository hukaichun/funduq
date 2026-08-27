from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from funduq_provider_sdk import (
    DeliveredRun,
    ProviderIdentity,
    ProviderRuntime,
    funduq_connect_payload,
)
from funduq_provider_sdk.protocol import (
    Connect,
    ConnectOk,
    FunduqSide,
    ProviderSide,
    Report,
    Resume,
    ResumeAnswered,
    Resumed,
    Resuming,
)

TIMEOUT = 5.0


def _identity() -> ProviderIdentity:
    return ProviderIdentity(Ed25519PrivateKey.generate())


def _funduq_open() -> FunduqSide:
    machine = FunduqSide(deliver_timeout=TIMEOUT)
    machine.feed(Connect(public_key="pk", ticket="tk", nonce="n", proof="sig"), now=0.0)
    machine.accept_connect("answer")
    return machine


def _provider_open(provider: ProviderIdentity, funduq: ProviderIdentity) -> ProviderSide:
    machine = ProviderSide(provider, funduq_public_key=funduq.public_key)
    machine.connect(ticket="tk", nonce="n")
    machine.feed(ConnectOk(answer=funduq.sign(funduq_connect_payload("tk", "n"))))
    return machine


def test_funduq_counts_what_it_actually_saw_per_run() -> None:
    """The watermark is the one thing this machine is the authority on. Which
    runs survived is core's answer, handed in by the driver."""
    machine = _funduq_open()

    machine.feed(Report(run_id="r-1", event={"type": "A"}, seq=1), now=0.0)
    machine.feed(Report(run_id="r-1", event={"type": "B"}, seq=2), now=0.0)
    machine.feed(Report(run_id="r-2", event={"type": "A"}, seq=1), now=0.0)

    turn = machine.resumed("q1", still_held=["r-1", "r-2"], unknown=["r-3"])

    assert turn.frames == [
        Resumed(id="q1", watermarks={"r-1": 2, "r-2": 1}, unknown=["r-3"])
    ]


def test_a_run_funduq_never_heard_of_resumes_from_zero() -> None:
    """Nothing arrived, so everything the provider holds is replayed — which is
    the correct answer for a link that died before its first event landed."""
    machine = _funduq_open()

    turn = machine.resumed("q1", still_held=["r-9"], unknown=[])

    assert turn.frames[0].watermarks == {"r-9": 0}


def test_a_report_without_a_sequence_leaves_the_watermark_alone() -> None:
    """A link that does not resume — `InProcessLink`, and every link written
    before this — sends no `seq`, and must not be given a watermark that
    claims otherwise."""
    machine = _funduq_open()

    machine.feed(Report(run_id="r-1", event={"type": "A"}), now=0.0)

    assert machine.resumed("q1", still_held=["r-1"], unknown=[]).frames[0].watermarks == {
        "r-1": 0
    }


def test_the_ask_and_the_answer_meet_by_id() -> None:
    provider, funduq = _identity(), _identity()
    serving = _provider_open(provider, funduq)
    caller = _funduq_open()

    request_id, asked = serving.resume(["r-1"])
    seen = caller.feed(asked.frames[0], now=0.0)

    assert asked.frames == [Resume(id=request_id, run_ids=["r-1"])]
    assert seen.events == [Resuming(id=request_id, run_ids=["r-1"])]

    answered = serving.feed(caller.resumed(request_id, still_held=["r-1"], unknown=[]).frames[0])

    assert answered.events == [
        ResumeAnswered(id=request_id, watermarks={"r-1": 0}, unknown=[])
    ]


class _Agent:

    def __init__(self) -> None:
        self.started = 0

    async def run_stream(self, agent_name: str, run_input):
        self.started += 1
        for index in range(4):
            yield {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m", "delta": str(index)}


class _Collecting:
    """A link that records what it is handed and can be taken away."""

    def __init__(self, public_key: str) -> None:
        self.public_key = public_key
        self.max_concurrent_runs = None
        self.reported: list[tuple[str, int | None, object]] = []
        self.finished: list[str] = []

    async def offer(self, run) -> bool:
        return True

    def cancel(self, run_id: str) -> None:
        pass

    async def report_event(self, run_id: str, event, *, seq: int | None = None) -> None:
        self.reported.append((run_id, seq, event))

    async def finish_run(self, run_id: str) -> None:
        self.finished.append(run_id)

    async def thread_messages(self, thread_id: str, *, limit=None):
        return []


def _delivered(run_id: str) -> DeliveredRun:
    return DeliveredRun(
        run_id=run_id,
        agent_name="translator",
        run_input={
            "threadId": "t-1",
            "runId": run_id,
            "state": None,
            "messages": [],
            "tools": [],
            "context": [],
            "forwardedProps": None,
        },
        thread_id="t-1",
    )


@pytest.fixture
async def runtime():
    identity = _identity()
    made = ProviderRuntime(identity, _Agent())
    made.start()
    yield made
    await made.aclose(cancel_in_flight=True)


async def _settle(runtime: ProviderRuntime) -> None:
    import asyncio

    for _ in range(40):
        await asyncio.sleep(0)


async def test_events_produced_with_no_link_are_held_not_dropped(runtime) -> None:
    """This is the defect resume was unreachable behind: the runtime took each
    event off its queue and, finding no link, dropped it."""
    runtime.link = None

    await runtime.deliver(_delivered("r-1"))
    await _settle(runtime)

    assert runtime.resuming() == ["r-1"]

    link = _Collecting("pk")
    runtime.link = link
    await runtime.resume({"r-1": 0}, [])

    assert [seq for _, seq, _ in link.reported] == [1, 2, 3, 4]
    assert link.finished == ["r-1"]


async def test_a_resume_replays_only_what_funduq_is_missing(runtime) -> None:
    link = _Collecting("pk")
    runtime.link = link
    await runtime.deliver(_delivered("r-1"))
    await _settle(runtime)
    delivered_first_time = len(link.reported)

    second = _Collecting("pk")
    runtime.link = second
    await runtime.resume({"r-1": 2}, [])

    assert delivered_first_time == 4
    assert [seq for _, seq, _ in second.reported] == [3, 4]


async def test_a_run_funduq_no_longer_holds_is_dropped_rather_than_replayed(runtime) -> None:
    runtime.link = None
    await runtime.deliver(_delivered("r-1"))
    await _settle(runtime)

    link = _Collecting("pk")
    runtime.link = link
    await runtime.resume({}, ["r-1"])

    assert link.reported == []
    assert runtime.resuming() == []


async def test_a_gap_wider_than_the_buffer_abandons_the_run_rather_than_hiding_it() -> None:
    """Replaying what is left would hand the caller a stream with a hole in the
    middle, which is worse than the failure resume exists to avoid."""
    identity = _identity()
    runtime = ProviderRuntime(identity, _Agent(), max_buffered_events=2)
    runtime.start()
    try:
        runtime.link = None
        await runtime.deliver(_delivered("r-1"))
        await _settle(runtime)

        link = _Collecting("pk")
        runtime.link = link
        lost = await runtime.resume({"r-1": 0}, [])

        assert lost == ["r-1"]
        assert link.reported == []
        assert runtime.resuming() == []
    finally:
        await runtime.aclose(cancel_in_flight=True)
