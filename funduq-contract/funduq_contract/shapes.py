"""Every structure that crosses between a provider and funduq, defined once.

Each is a pydantic model and forbids unknown fields. Anything a transport
needs beyond these is the transport's own vocabulary.
"""

from __future__ import annotations

from typing import Any, Literal

from ag_ui.core import RunAgentInput
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.completion_create_params import (
    CompletionCreateParamsNonStreaming,
    CompletionCreateParamsStreaming,
)
from collections.abc import Iterator

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


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


class CompletionBodyNonStreaming(CompletionCreateParamsNonStreaming, total=False):
    """OpenAI's own request shape, with extension keys (extra_body and the like, merged at the top level by clients) allowed through verbatim."""

    __pydantic_config__ = ConfigDict(extra="allow")


class CompletionBodyStreaming(CompletionCreateParamsStreaming, total=False):
    """The streaming variant, extensions allowed the same way."""

    __pydantic_config__ = ConfigDict(extra="allow")


CompletionBody = CompletionBodyStreaming | CompletionBodyNonStreaming


class DeliveredCompletion(Shape):
    """One completion request as the LLM provider receives it."""

    run_id: str = Field(alias="runId")
    provider_key: str = Field(alias="providerKey")
    agent_name: str = Field(alias="agentName")
    body: CompletionBody
    llm_name: str = Field(default="", alias="llmName")
    context: Any = None
    actor_chain: list[str] | None = Field(default=None, alias="actorChain")

    @field_serializer("body", mode="plain")
    def _as_data(self, body: CompletionBody) -> dict[str, Any]:
        """The body is already plain data after validation; serialized as such, not re-checked against the lazy annotations."""
        return dict(body)

    @field_validator("body", mode="after")
    @classmethod
    def _materialized(cls, body: CompletionBody) -> CompletionBody:
        """OpenAI types several fields as `Iterable`, which pydantic validates lazily; a wire shape must survive a dump, so lazy validators are walked here, once."""
        return {  # type: ignore[return-value]
            key: list(value) if isinstance(value, Iterator) else value
            for key, value in body.items()
        }


class Complete(Shape):
    """funduq hands a completion request down the LLM link and asks for the chunks."""

    id: str
    request: DeliveredCompletion


class Chunk(Shape):
    """One chat-completion chunk of an answering stream, under its request's id."""

    id: str
    chunk: ChatCompletionChunk


class CompletionEnd(Shape):
    """The stream under this id ended normally."""

    id: str


class CompletionFailed(Shape):
    """The stream under this id will not finish; the reason is the provider's own words."""

    id: str
    reason: str
