from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ag_ui.core import Message, RunAgentInput
from pydantic import ValidationError

from funduq_provider_sdk.provider import DeliveredRun, Refusal


class FunduqLink(ABC):
    """A transport connecting a provider to funduq; subclasses must implement every abstract member below (a subclass missing one, e.g."""

    @property
    @abstractmethod
    def public_key(self) -> str:
        pass

    @property
    @abstractmethod
    def max_concurrent_runs(self) -> int | None:
        pass

    async def deliver(self, run: Any) -> bool | Refusal:
        """Translates funduq's internal claimed-run object into a `DeliveredRun` and hands it to `offer`."""
        try:
            delivered = DeliveredRun.from_claimed(run)
        except ValidationError as e:
            return Refusal(f"input does not validate as RunAgentInput: {e}")
        return await self.offer(delivered)

    @abstractmethod
    async def offer(self, run: DeliveredRun) -> bool | Refusal:
        """Accept (`True`), decline transiently (`False` — full right now), or refuse permanently (`Refusal`)."""
        pass

    @abstractmethod
    def cancel(self, run_id: str) -> None:
        pass


    @abstractmethod
    async def report_event(self, run_id: str, event: Any) -> None:
        pass

    @abstractmethod
    async def finish_run(self, run_id: str) -> None:
        pass

    @abstractmethod
    async def thread_messages(
        self, thread_id: str, *, limit: int | None = None
    ) -> list[Message]:
        pass
