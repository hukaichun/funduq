from __future__ import annotations

import asyncio

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ag_ui.core import RunAgentInput
from pydantic import BaseModel, ConfigDict, Field


class Provider(Protocol):

    def run_stream(self, agent_name: str, run_input: RunAgentInput) -> AsyncIterator[Any]: ...


@dataclass(frozen=True)
class Refusal:
    """A permanent decline of an offered run: this provider will never accept it, so funduq should stop re-offering and fail the run."""

    reason: str


class Registration(BaseModel):
    """One agent as it is published on a link — and the declared wire form of one."""

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="forbid")

    name: str
    description: str = ""
    agent_card_extra: dict[str, Any] = Field(default_factory=dict, alias="agentCardExtra")
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeliveredRun(BaseModel):
    """The run data handed to a `FunduqLink`, translated from funduq's internal claimed-run representation — and the declared wire form of an offered run."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    run_id: str = Field(alias="runId")
    agent_name: str = Field(alias="agentName")
    run_input: RunAgentInput = Field(alias="runInput")
    thread_id: str | None = Field(default=None, alias="threadId")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_claimed(cls, run: Any) -> "DeliveredRun":
        """Translates funduq's claimed-run object (read by attribute, never imported) into the delivered form."""
        return cls(
            run_id=run.run_id,
            agent_name=run.agent.name,
            run_input=RunAgentInput.model_validate(run.run_input),
            thread_id=run.thread_id,
            metadata=dict(getattr(run, "metadata", None) or {}),
        )


@dataclass
class AgentHandle:

    name: str
    run_stream: Callable[[RunAgentInput], AsyncIterator[Any]]
    description: str = ""
    agent_card_extra: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_registration(self) -> dict[str, Any]:
        registration: dict[str, Any] = {"name": self.name, "description": self.description}
        if self.agent_card_extra:
            registration["agent_card_extra"] = self.agent_card_extra
        if self.metadata:
            registration["metadata"] = self.metadata
        return registration


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
