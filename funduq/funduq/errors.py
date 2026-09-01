from __future__ import annotations

from funduq.repo import (
    ProviderFingerprintTaken,
    ThreadNotFound,
    ThreadOwnershipMismatch,
    ThreadMembershipRequired,
    ThreadQueueFull,
)

__all__ = [
    "AgentInUse",
    "AgentNotFound",
    "InvalidRegistration",
    "KyokRejected",
    "InvalidRunInput",
    "NoPendingAsk",
    "ProviderFingerprintTaken",
    "RunNotCancellable",
    "RunNotFound",
    "FunduqError",
    "ThreadNotFound",
    "ThreadOwnershipMismatch",
    "ThreadMembershipRequired",
    "ThreadQueueFull",
]


class FunduqError(Exception):
    pass


class AgentNotFound(FunduqError):
    pass


class LlmProviderNotFound(FunduqError):
    pass


class LlmOfferingInUse(FunduqError):
    """Raised when deleting an LLM offering is refused because it's still in use — the mirror of `AgentInUse`."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class AgentInUse(FunduqError):
    """Raised when deleting an agent is refused because it's still in use."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class InvalidRegistration(FunduqError):
    pass


class KyokRejected(FunduqError):
    """A KYOK completion call was refused; `status` is the status code a caller should be told."""

    def __init__(self, message: str, *, status: int, refusal: dict | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.refusal = refusal


class RunNotFound(FunduqError):
    pass


class RunNotCancellable(FunduqError):
    """Raised when a cancel is asked of a run that has nobody to ask."""


class NoPendingAsk(FunduqError):
    """Raised when a deferred call's result is offered to a run that is not waiting for one."""


class InvalidRunInput(FunduqError):
    pass
