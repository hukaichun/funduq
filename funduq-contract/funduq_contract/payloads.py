"""The exact bytes each party signs, and nothing else."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable


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


def resolve_payload(run_id: str, ask_ids: Iterable[str]) -> bytes:
    """The bytes an authority signs to answer a paused ask: "I answer run X's
    outstanding asks, exactly these".

    `ask_ids` is everything the paused run is waiting on (its interrupt /
    tool-call ids); canonicalization happens here and nowhere else — sorted,
    NUL-joined, hashed — so both signer and verifier derive the same bytes
    from the same set. Binding the instance is what makes this proof
    single-purpose: a later pause has new ids, so no time rides in it and
    no freshness window applies — replay against the same ask is consumed
    by the status-guarded reopen, and against any other ask it never
    verifies.
    """
    if isinstance(ask_ids, str):
        # A str is an Iterable[str] of characters; signing one silently would
        # produce a hash nothing else ever computes.
        raise TypeError("ask_ids is a collection of ids, not one id")
    asks_hash = hashlib.sha256(
        b"\x00".join(ask_id.encode() for ask_id in sorted(ask_ids))
    ).hexdigest()
    return f"{_RESOLVE}:{run_id}:{asks_hash}".encode()


def cancel_payload(run_id: str, timestamp: int) -> bytes:
    """The bytes an authority signs to ask that a run be stopped: "I ask this run to stop, now"."""
    return f"{_CANCEL}:{run_id}:{timestamp}".encode()


def view_payload(run_id: str, timestamp: int) -> bytes:
    """The bytes a chain party signs to read a bound run: "I ask to see this run, now"."""
    return f"{_VIEW}:{run_id}:{timestamp}".encode()
