from __future__ import annotations

__all__ = [
    "AgentInUse",
    "AgentNotFound",
    "InvalidRegistration",
    "KyokRejected",
    "InvalidRunInput",
    "NoPendingAsk",
    "ProviderFingerprintTaken",
    "RunNotCancellable",
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


class ProviderFingerprintTaken(FunduqError):
    """A provider's public key hashes to a fingerprint another registered public key already holds."""


class ThreadNotFound(FunduqError):
    """A thread id funduq never minted, where creating one was not asked for."""


class ThreadOwnershipMismatch(FunduqError):
    """The thread belongs to a different agent than the one addressed."""


class ThreadMembershipRequired(FunduqError):
    """The thread is bound to a responsibility segment and the writer is not a member."""


class ThreadQueueFull(FunduqError):
    """The thread's pending-utterance buffer is at its limit; the message was NOT accepted."""


class RunNotCancellable(FunduqError):
    """Raised when a cancel is asked of a run that has nobody to ask."""


class NoPendingAsk(FunduqError):
    """Raised when a deferred call's result is offered to a run that is not waiting for one."""


class InvalidRunInput(FunduqError):
    pass


class PresenterRequired(FunduqError):
    """A chain arrived, but this door was not told which key presented it.

    Nothing the caller sent is wrong — the chain may verify perfectly. The
    chain's last hop says "I am presenting this", and that statement cannot
    be checked without knowing who is at the door. The transport must
    authenticate the caller and hand the key to core (`presenter_key_of` on
    the A2A handler, `presenter_key=` on the AG-UI adapter and the facade);
    until it does, this deployment does not accept chains. Distinct from
    `InvalidChain` so a gateway can answer "authentication required" rather
    than "bad request".
    """


class StreamTaken(FunduqError):
    """The run already has a live stream. funduq serves one stream per run (A2A §3.5.2 leaves serving several a MAY); a second subscriber is refused rather than handed half the events."""
