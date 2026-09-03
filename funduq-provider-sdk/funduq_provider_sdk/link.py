from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ag_ui.core import Message

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

    @abstractmethod
    async def deliver(self, run: DeliveredRun) -> None:
        """Hand the offered run over. The verdict (accept `True` / decline `False` / `Refusal`) does not ride the return — it goes back to funduq through the same road reports take (`answer_offer`), in the call path that learned it, so nothing funduq-side has to win a scheduling race to hear it."""
        pass

    @abstractmethod
    async def cancel(self, run_id: str) -> bool:
        """Ask the run's thread handler to stop; True acknowledges the ask arrived, never an outcome."""
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
