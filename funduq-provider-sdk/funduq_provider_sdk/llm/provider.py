from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

from openai.types.chat import ChatCompletionChunk
from funduq_contract import DeliveredCompletion


CompletionHandler = Callable[[DeliveredCompletion], AsyncIterator[ChatCompletionChunk]]


class CompletionRefused(Exception):
    """Raise from a `CompletionHandler` to answer with a structured refusal instead of an opaque failure."""

    def __init__(self, refusal: dict[str, Any]) -> None:
        super().__init__(str(refusal))
        self.refusal = refusal


