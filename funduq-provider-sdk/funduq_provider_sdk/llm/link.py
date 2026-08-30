from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from openai.types.chat import ChatCompletionChunk

from funduq_provider_sdk.llm.provider import DeliveredCompletion


class FunduqLLMLink(ABC):
    """A transport connecting an LLM provider to funduq — the peer of `funduq_provider_sdk.FunduqLink`."""

    @property
    @abstractmethod
    def public_key(self) -> str:
        pass

    def complete(self, request: Any) -> AsyncIterator[ChatCompletionChunk]:
        """Repackages a completion request's fields into a `DeliveredCompletion` and hands it to `serve`."""
        return self.serve(DeliveredCompletion.from_request(request))

    @abstractmethod
    def serve(self, delivered: DeliveredCompletion) -> AsyncIterator[ChatCompletionChunk]:
        pass
