from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from openai.types.chat import ChatCompletionChunk

from funduq_provider_sdk.llm.provider import DeliveredCompletion


class FunduqLLMLink(ABC):
    """A transport connecting an LLM provider to funduq — the peer of `funduq_provider_sdk.FunduqLink`."""

    @property
    @abstractmethod
    def public_key(self) -> str:
        pass

    @abstractmethod
    def complete(self, request: DeliveredCompletion) -> AsyncIterator[ChatCompletionChunk]:
        pass
