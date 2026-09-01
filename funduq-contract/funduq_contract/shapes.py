"""Every structure that crosses between a provider and funduq, defined once.

Each is a pydantic model and forbids unknown fields. Anything a transport
needs beyond these is the transport's own vocabulary.
"""

from __future__ import annotations

from typing import Any, Literal

from ag_ui.core import RunAgentInput
from pydantic import BaseModel, ConfigDict, Field


class Shape(BaseModel):
    """Base of every crossing structure: frozen, alias-aware, unknown fields refused."""

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="forbid")


class Registration(Shape):
    """One agent as it is published on a link."""

    name: str
    description: str = ""
    agent_card_extra: dict[str, Any] = Field(default_factory=dict, alias="agentCardExtra")
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeliveredRun(Shape):
    """One run as it is handed to a provider."""

    run_id: str = Field(alias="runId")
    agent_name: str = Field(alias="agentName")
    run_input: RunAgentInput = Field(alias="runInput")
    thread_id: str | None = Field(default=None, alias="threadId")
    metadata: dict[str, Any] = Field(default_factory=dict)


class Refusal(Shape):
    """A permanent decline of an offered run: never re-offer it, fail it."""

    reason: str


class Connect(Shape):
    """The opening of the link: the provider's identity and its proof."""

    public_key: str = Field(alias="publicKey")
    ticket: str
    provider_nonce: str = Field(alias="providerNonce")
    proof: str
    max_concurrent_runs: int | None = Field(default=None, alias="maxConcurrentRuns")


class ConnectOk(Shape):
    """funduq's answering proof; the provider verifies it against its pinned key."""

    proof: str


class ConnectErr(Shape):
    """The link was refused before it opened."""

    reason: str


class Offer(Shape):
    """funduq hands a run down the link and asks for a verdict."""

    id: str
    run: DeliveredRun


class Verdict(Shape):
    """The provider's answer to an offer: an intake decision, never an outcome."""

    id: str
    verdict: Literal["accepted", "declined", "refused"]
    reason: str | None = None


class Cancel(Shape):
    """funduq asks the run's thread handler to stop; a request, never a command."""

    id: str
    run_id: str = Field(alias="runId")


class Ack(Shape):
    """The request with this id was received; it says nothing about outcomes."""

    id: str
