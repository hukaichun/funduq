"""One thread has one active run — by construction, in the runtime itself."""

from __future__ import annotations

import asyncio

from ag_ui.core import RunAgentInput

from funduq_contract import DeliveredRun, Refusal
from funduq_provider_sdk import ProviderIdentity, ProviderRuntime


def _delivered(run_id: str, thread_id: str, *, addressed: str | None = None) -> DeliveredRun:
    props = {"addressedRunId": addressed} if addressed else None
    return DeliveredRun(
        run_id=run_id,
        agent_name="a",
        run_input=RunAgentInput.model_validate(
            {
                "threadId": thread_id,
                "runId": run_id,
                "state": None,
                "messages": [],
                "tools": [],
                "context": [],
                "forwardedProps": props,
            }
        ),
        thread_id=thread_id,
    )


class _GatedAgent:
    """Every run waits on its own gate; the test decides who finishes when."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.gates: dict[str, asyncio.Event] = {}

    def gate(self, run_id: str) -> asyncio.Event:
        return self.gates.setdefault(run_id, asyncio.Event())

    async def run_stream(self, agent_name: str, run_input: RunAgentInput):
        run_id = run_input.run_id
        self.started.append(run_id)
        yield {"type": "RUN_STARTED", "threadId": run_input.thread_id, "runId": run_id}
        await self.gate(run_id).wait()
        yield {"type": "RUN_FINISHED", "threadId": run_input.thread_id, "runId": run_id}


class _Sink:
    """A link that only collects what comes back up."""

    def __init__(self, runtime: ProviderRuntime) -> None:
        runtime.link = self
        self.finished: list[str] = []

    async def report_event(self, run_id: str, event) -> None:
        pass

    async def finish_run(self, run_id: str) -> None:
        self.finished.append(run_id)


async def _settled(predicate, timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


async def test_two_accepted_runs_on_one_thread_execute_one_at_a_time():
    agent = _GatedAgent()
    runtime = ProviderRuntime(ProviderIdentity.generate(), agent)
    sink = _Sink(runtime)
    runtime.start()
    try:
        assert await runtime.deliver(_delivered("r1", "t")) is True
        assert await runtime.deliver(_delivered("r2", "t")) is True
        await _settled(lambda: agent.started == ["r1"])
        await asyncio.sleep(0.05)
        assert agent.started == ["r1"], "r2 must not start while r1 runs"

        agent.gate("r1").set()
        await _settled(lambda: agent.started == ["r1", "r2"])
        agent.gate("r2").set()
        await _settled(lambda: sink.finished == ["r1", "r2"])
    finally:
        await runtime.aclose(cancel_in_flight=True)


async def test_runs_on_different_threads_execute_concurrently():
    agent = _GatedAgent()
    runtime = ProviderRuntime(ProviderIdentity.generate(), agent)
    _Sink(runtime)
    runtime.start()
    try:
        await runtime.deliver(_delivered("r1", "t1"))
        await runtime.deliver(_delivered("r2", "t2"))
        await _settled(lambda: sorted(agent.started) == ["r1", "r2"])
    finally:
        await runtime.aclose(cancel_in_flight=True)


async def test_an_interjection_is_refused_without_the_hook():
    agent = _GatedAgent()
    runtime = ProviderRuntime(ProviderIdentity.generate(), agent)
    _Sink(runtime)
    runtime.start()
    try:
        await runtime.deliver(_delivered("r1", "t"))
        await _settled(lambda: agent.started == ["r1"])

        answer = await runtime.deliver(_delivered("r2", "t", addressed="r1"))
        assert isinstance(answer, Refusal)
        assert "interjection" in answer.reason
        assert agent.started == ["r1"], "the refused run never touched the agent"
    finally:
        await runtime.aclose(cancel_in_flight=True)


async def test_an_interjection_reaches_the_hook_while_the_run_it_names_is_live():
    class InterjectingAgent(_GatedAgent):
        def __init__(self) -> None:
            super().__init__()
            self.interjected: list[tuple[str, str]] = []

        async def interject_stream(self, agent_name, run_input, active_run_id):
            self.interjected.append((run_input.run_id, active_run_id))
            ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
            yield {"type": "RUN_STARTED", **ids}
            yield {"type": "RUN_FINISHED", **ids}

    agent = InterjectingAgent()
    runtime = ProviderRuntime(ProviderIdentity.generate(), agent)
    sink = _Sink(runtime)
    runtime.start()
    try:
        await runtime.deliver(_delivered("r1", "t"))
        await _settled(lambda: agent.started == ["r1"])

        assert await runtime.deliver(_delivered("r2", "t", addressed="r1")) is True
        await _settled(lambda: agent.interjected == [("r2", "r1")])
        await _settled(lambda: "r2" in sink.finished)
        assert agent.started == ["r1"], "the interjection rode the hook, not the lane"
    finally:
        await runtime.aclose(cancel_in_flight=True)


async def test_a_declaration_naming_anything_but_the_active_run_is_an_ordinary_turn():
    agent = _GatedAgent()
    runtime = ProviderRuntime(ProviderIdentity.generate(), agent)
    _Sink(runtime)
    runtime.start()
    try:
        await runtime.deliver(_delivered("r1", "t"))
        await _settled(lambda: agent.started == ["r1"])

        # Addressed to a run that is not the lane's active one: no hook consulted,
        # no refusal — it queues like any next turn.
        assert await runtime.deliver(_delivered("r2", "t", addressed="r-gone")) is True
        await asyncio.sleep(0.05)
        assert agent.started == ["r1"]
        agent.gate("r1").set()
        await _settled(lambda: agent.started == ["r1", "r2"])
    finally:
        await runtime.aclose(cancel_in_flight=True)


async def test_cancelling_a_queued_run_finishes_it_without_running_it():
    agent = _GatedAgent()
    runtime = ProviderRuntime(ProviderIdentity.generate(), agent)
    sink = _Sink(runtime)
    runtime.start()
    try:
        await runtime.deliver(_delivered("r1", "t"))
        await runtime.deliver(_delivered("r2", "t"))
        await _settled(lambda: agent.started == ["r1"])

        runtime.cancel("r2")
        await _settled(lambda: sink.finished == ["r2"])

        agent.gate("r1").set()
        await _settled(lambda: sink.finished == ["r2", "r1"])
        assert agent.started == ["r1"], "the cancelled run never executed"
    finally:
        await runtime.aclose(cancel_in_flight=True)
