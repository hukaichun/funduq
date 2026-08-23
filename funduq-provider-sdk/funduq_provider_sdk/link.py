from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ag_ui.core import Message, RunAgentInput
from pydantic import ValidationError

from funduq_provider_sdk.provider import DeliveredRun, Refusal


class FunduqLink(ABC):
    """A transport connecting a provider to funduq; subclasses must implement every abstract member below
    (a subclass missing one, e.g. `max_concurrent_runs`, fails to construct with a TypeError).

    A link that crosses a process boundary must authenticate its open
    against a challenge the verifier chose — sign
    `provider_connect_payload` (and check funduq's `funduq_connect_payload`
    answer against the funduq key you pinned). A self-chosen timestamp is not
    a challenge; a signature over one is replayable for its whole freshness
    window. `InProcessLink` performs the same ceremony automatically —
    sharing a process is not a reason to skip it. A link may expose
    `confirm_connect(funduq_nonce, provider_nonce, answer)`: funduq's answering
    signature is handed over there before the attach commits, so a pinning
    link refuses the wrong funduq by raising.
    """

    @property
    @abstractmethod
    def public_key(self) -> str:
        pass

    @property
    @abstractmethod
    def max_concurrent_runs(self) -> int | None:
        pass

    async def deliver(self, run: Any) -> bool | Refusal:
        """Translates funduq's internal claimed-run object into a `DeliveredRun` and hands it to `offer`.

        An input that doesn't validate as `RunAgentInput` is a permanent
        refusal, not a transient decline — re-offering the same bytes can
        never succeed."""
        try:
            delivered = DeliveredRun.from_claimed(run)
        except ValidationError as e:
            return Refusal(f"input does not validate as RunAgentInput: {e}")
        return await self.offer(delivered)

    @abstractmethod
    async def offer(self, run: DeliveredRun) -> bool | Refusal:
        """Accept (`True`), decline transiently (`False` — full right now), or refuse permanently (`Refusal`).

        **Answer from your own state, never from the agent's.** Whether the
        run was received, whether there is room for it, and whether its input
        is valid are all known the moment it arrives; none of them requires
        asking the agent anything. This answer is a receipt, not a report of
        progress — `ProviderRuntime.deliver` does not await at all, and a
        link that waits for the agent to start would turn a round-trip into
        the agent's startup time.

        That matters because of what funduq does with it: the next utterance
        of the *same conversation* is held until this answer lands, which is
        how a thread's delivery order survives a transport that guarantees
        none. Nothing else waits — other conversations, other agents and
        other providers hand over meanwhile.
        """
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
