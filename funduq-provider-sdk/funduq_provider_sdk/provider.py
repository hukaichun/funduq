from __future__ import annotations

import asyncio

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ag_ui.core import RunAgentInput
from funduq_contract import DeliveredRun, Refusal, Registration

__all__ = ["Provider", "Refusal", "Registration", "DeliveredRun", "AgentHandle",
           "HandleProvider", "serialize_per_thread"]


class Provider(Protocol):

    def run_stream(self, agent_name: str, run_input: RunAgentInput) -> AsyncIterator[Any]: ...


@dataclass
class AgentHandle:

    name: str
    run_stream: Callable[[RunAgentInput], AsyncIterator[Any]]
    description: str = ""
    agent_card_extra: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_registration(self) -> Registration:
        return Registration(
            name=self.name,
            description=self.description,
            agent_card_extra=self.agent_card_extra,
            metadata=self.metadata,
        )


class HandleProvider:
    """A `Provider` that dispatches `run_stream` by agent name to the matching `AgentHandle`'s callable."""

    def __init__(self, agents: list[AgentHandle]) -> None:
        self.agents = {agent.name: agent for agent in agents}

    def run_stream(self, agent_name: str, run_input: RunAgentInput) -> AsyncIterator[Any]:
        return self.agents[agent_name].run_stream(run_input)


def serialize_per_thread(
    run_stream: Callable[[RunAgentInput], AsyncIterator[Any]],
) -> Callable[[RunAgentInput], AsyncIterator[Any]]:
    """Wraps an agent callable so runs of the same thread execute one at a time, in arrival order; runs on different threads still interleave freely."""
    locks: dict[str, asyncio.Lock] = {}

    async def serialized(run_input: RunAgentInput) -> AsyncIterator[Any]:
        thread_id = getattr(run_input, "thread_id", None)
        if thread_id is None:
            async for event in run_stream(run_input):
                yield event
            return
        async with locks.setdefault(thread_id, asyncio.Lock()):
            async for event in run_stream(run_input):
                yield event

    return serialized
