from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentRef(BaseModel):

    model_config = ConfigDict(frozen=True)

    provider_key: str
    name: str

    def __str__(self) -> str:
        return f"{self.provider_key[:16]}…/{self.name}"


class LlmRef(BaseModel):

    model_config = ConfigDict(frozen=True)

    provider_key: str
    name: str

    def __str__(self) -> str:
        return f"{self.provider_key[:16]}…/{self.name}"


class LlmSummary(BaseModel):
    """A roster-list view of a registered LLM offering: enough to display and pick one (including online status), the mirror of `AgentSummary`."""

    provider_key: str
    name: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    joined_at: datetime
    last_seen_at: datetime
    online: bool = False
    provider_name: str | None = None


class AgentSummary(BaseModel):
    """A roster-list view of a registered agent: enough to display and pick an agent (including online status), but without its full agent_card or metadata."""

    provider_key: str
    name: str
    description: str = ""
    skills: list[dict[str, Any]] = Field(default_factory=list)
    joined_at: datetime
    last_seen_at: datetime
    online: bool = False
    provider_name: str | None = None


class AgentRecord(BaseModel):
    """The full stored record for a single registered agent, including its agent_card and metadata; returned by looking up one agent by id."""

    provider_key: str
    name: str
    agent_card: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    joined_at: datetime
    last_seen_at: datetime


class RunRecord(BaseModel):
    """A run as stored: the AG-UI `RunAgentInput` it is (its messages live in the thread), and the state funduq holds about it."""

    run_id: str
    thread_id: str
    provider_key: str
    agent_name: str
    status: str
    actor_chain: list[str] | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_activity_at: datetime | None = None
    # RunAgentInput
    parent_run_id: str | None = None
    state: Any = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    context: list[dict[str, Any]] = Field(default_factory=list)
    forwarded_props: Any = None
    resume: list[dict[str, Any]] | None = None
    # state
    cancel_requested_by: str | None = None

    @property
    def agent(self) -> "AgentRef":
        return AgentRef(provider_key=self.provider_key, name=self.agent_name)
