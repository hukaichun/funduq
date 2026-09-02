from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ag_ui.core import RunAgentInput
from funduq_contract import DeliveredRun, Refusal, Registration

__all__ = ["Provider", "Refusal", "Registration", "DeliveredRun", "AgentHandle",
           "HandleProvider"]


class Provider(Protocol):

    def run_stream(self, agent_name: str, run_input: RunAgentInput) -> AsyncIterator[Any]: ...


@dataclass
class AgentHandle:

    name: str
    run_stream: Callable[[RunAgentInput], AsyncIterator[Any]]
    description: str = ""
    agent_card_extra: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    # An interjection to this agent's active run goes here; None means the
    # agent takes none. The declaration is derived from this field — the
    # hook and the card's claim live in one place, so they cannot disagree.
    interject_stream: Callable[[RunAgentInput, str], AsyncIterator[Any]] | None = None

    def as_registration(self) -> Registration:
        return Registration(
            name=self.name,
            description=self.description,
            agent_card_extra=self.agent_card_extra,
            metadata=self.metadata,
            takes_interjections=callable(self.interject_stream),
        )


class HandleProvider:
    """A `Provider` that dispatches `run_stream` by agent name to the matching `AgentHandle`'s callable."""

    def __init__(self, agents: list[AgentHandle]) -> None:
        self.agents = {agent.name: agent for agent in agents}

    def run_stream(self, agent_name: str, run_input: RunAgentInput) -> AsyncIterator[Any]:
        return self.agents[agent_name].run_stream(run_input)

    def interjection_hook(
        self, agent_name: str
    ) -> Callable[[RunAgentInput, str], AsyncIterator[Any]] | None:
        """The named agent's interjection hook, or None — the one lookup both the card's declaration and the runtime's routing read."""
        handle = self.agents.get(agent_name)
        return handle.interject_stream if handle is not None else None
