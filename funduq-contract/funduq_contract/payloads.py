"""The exact bytes each party signs, and nothing else."""

from __future__ import annotations


_KYOK_CALL = "funduq-kyok-call"
_CONNECT_PROVIDER = "funduq-connect-provider"
_CONNECT_FUNDUQ = "funduq-connect-funduq"
_RESOLVE = "funduq-resolve"
_CANCEL = "funduq-cancel"
_VIEW = "funduq-view"


def provider_connect_payload(
    funduq_public_key: str, funduq_nonce: str, provider_nonce: str
) -> bytes:
    """The bytes a provider signs to authenticate opening a link."""
    return f"{_CONNECT_PROVIDER}:{funduq_public_key}:{funduq_nonce}:{provider_nonce}".encode()


def funduq_connect_payload(funduq_nonce: str, provider_nonce: str) -> bytes:
    """The bytes funduq signs to prove itself to a connecting provider."""
    return f"{_CONNECT_FUNDUQ}:{funduq_nonce}:{provider_nonce}".encode()


def kyok_call_payload(bearer: str, timestamp: int, body_hash: str) -> bytes:
    """The bytes an agent provider signs to prove it made a given KYOK completion call."""
    return f"{_KYOK_CALL}:{bearer}:{timestamp}:{body_hash}".encode()


def resolve_payload(run_id: str, timestamp: int) -> bytes:
    """The bytes an authority signs to answer a paused ask: "I resolve this run, now"."""
    return f"{_RESOLVE}:{run_id}:{timestamp}".encode()


def cancel_payload(run_id: str, timestamp: int) -> bytes:
    """The bytes an authority signs to ask that a run be stopped: "I ask this run to stop, now"."""
    return f"{_CANCEL}:{run_id}:{timestamp}".encode()


def view_payload(run_id: str, timestamp: int) -> bytes:
    """The bytes a chain party signs to read a bound run: "I ask to see this run, now"."""
    return f"{_VIEW}:{run_id}:{timestamp}".encode()
