"""The window between "is anyone serving?" and handing the run over.

`dispatch` used to ask the roster, then `await session.commit()`, then call
`enqueue_run` — which asks the same question again and raised `RuntimeError`
when the answer had changed. The commit is a suspension point (on Postgres,
a network round trip), and a provider closing its socket inside it is an
ordinary event, not a contrived one.

Three things broke together, and the third is the one that matters: the
caller got an unhandled `RuntimeError` where the door promises
`agent_offline` — a 500 at either protocol door; the run stayed `queued` in
the record forever; and the broker never heard of it, which is precisely the
"run nothing could ever finish" `enqueue_run`'s own docstring says it exists
to refuse.

The fix is not to narrow the window. It is that **one party decides**: the
door stopped asking, and `Funduq.enqueue_run`'s answer — taken in the same
synchronous breath as the enqueue it guards — is the only reading of the
roster on this path.
"""

from __future__ import annotations

import pytest

from funduq import doors
from funduq.models import AgentRef

from tests.conftest import EchoAgent


def _valid_input(run_id: str, thread_id: str) -> dict:
    """The smallest dict that validates as a `RunAgentInput`: the broker now
    builds the published `DeliveredRun` itself, so a test input must be one."""
    return {
        "threadId": thread_id,
        "runId": run_id,
        "state": None,
        "messages": [],
        "tools": [],
        "context": [],
        "forwardedProps": None,
    }


async def test_a_provider_leaving_mid_dispatch_reaches_the_caller_as_agent_offline(
    funduq, new_identity, attach, monkeypatch
):
    """The provider detaches inside the door's own window.

    Reproduced by detaching from `build_run_agent_input`, which sits between
    the two readings of the roster — after the door's check, before the
    commit and the enqueue. It stands in for the commit itself, which is the
    real suspension point and is a network round trip on Postgres; hooking a
    named function is deterministic where racing that round trip is not.
    """
    identity = new_identity()
    runtime, link = await attach(identity, EchoAgent(), ["assistant"])
    agent = AgentRef(provider_key=identity.public_key, name="assistant")

    real_build = doors.build_run_agent_input

    def detach_then_build(*args, **kwargs):
        funduq.detach_provider(identity.public_key, link)
        return real_build(*args, **kwargs)

    monkeypatch.setattr(doors, "build_run_agent_input", detach_then_build)

    handle = await funduq.start_run(agent, {"messages": []})
    events = [event async for event in handle.events()]

    assert events[-1]["type"] == "RUN_ERROR", events

    run = await funduq.get_run(handle.run_id)
    assert run.status == "failed", "a run nothing will dispatch must not read as queued forever"
    assert run.metadata.get("failureReason") == "agent_offline"
    assert handle.run_id not in funduq.active_runs(), "and the broker never took it"


async def test_funduq_answers_rather_than_raising_when_nobody_is_serving(
    funduq, new_identity
):
    """The refusal is a value, not an exception.

    A run arriving at a door for an agent nobody serves is refused there —
    "nobody is serving" is an answer a caller can act on, and the door has a
    path for it. The broker itself no longer asks: a run it is handed waits
    on the unserved clock, which is what a run read back after a restart
    needs (#122). Being asked to enqueue while the broker is stopped stays
    an exception: that is a programming error, not a race.
    """
    identity = new_identity()
    agent = AgentRef(provider_key=identity.public_key, name="assistant")

    assert funduq.enqueue_run("run_1", agent, "thread_1", _valid_input("run_1", "thread_1"), "ag-ui") is None
