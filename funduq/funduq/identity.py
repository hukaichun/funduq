from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

if TYPE_CHECKING:
    from funduq.models import AgentRef



# The format is funduq-contract's, and these names are re-exported rather than rewritten.
from funduq_contract import (
    FINGERPRINT_HEX_LENGTH,
    ChainResult,
    DispatchTarget as DispatchTarget,
    InvalidChain as InvalidChain,
    cancel_payload as cancel_payload,
    dispatch_hop as _dispatch_hop,
    extend_chain as extend_chain,
    funduq_connect_payload as funduq_connect_payload,
    is_fingerprint,
    kyok_call_payload as kyok_call_payload,
    new_chain as new_chain,
    provider_connect_payload as provider_connect_payload,
    provider_fingerprint,
    resolve_payload as resolve_payload,
    verify_chain as verify_chain,
    verify_signature,
    view_payload as view_payload,
)


SIGNATURE_FRESHNESS_WINDOW_SECONDS = 60


def is_timestamp_fresh(timestamp: int) -> bool:
    return abs(time.time() - timestamp) <= SIGNATURE_FRESHNESS_WINDOW_SECONDS


class InvalidResolution(ValueError):
    pass


class InvalidCancel(ValueError):
    pass


class InvalidView(ValueError):
    pass


def _verify_signed_act(
    proof: dict,
    run_id: str,
    payload_for: Callable[[str, int], bytes],
    allowed_keys: set[str],
    invalid: type[ValueError],
    act: str,
) -> str:
    """Verifies one singular signed act against an authority set and returns the signer."""
    try:
        signer = proof["publicKey"]
        timestamp = int(proof["timestamp"])
        signature = proof["signature"]
    except (KeyError, TypeError, ValueError) as e:
        raise invalid(f"malformed {act} proof: {e}") from e
    if signer not in allowed_keys:
        raise invalid(
            f"the signer is not an authority for this run — neither its "
            f"segment head nor its provider (cannot {act} it)"
        )
    if not is_timestamp_fresh(timestamp):
        raise invalid(f"{act} timestamp outside the freshness window")
    if not verify_signature(signer, signature, payload_for(run_id, timestamp)):
        raise invalid(f"{act} signature does not verify")
    return signer


def verify_resolution(
    resolution: dict, run_id: str, ask_ids: set[str], allowed_keys: set[str]
) -> str:
    """Verifies a resolution proof for a paused run and returns the signer.

    Resolve is not in the timestamp family: the signature binds the exact
    asks being answered (`ask_ids`, the run's outstanding interrupt /
    tool-call ids), so the proof is single-purpose by construction — a
    later pause has new ids — and carries no time. Both sides derive the
    signed bytes from the same set via `resolve_payload`.
    """
    try:
        signer = resolution["publicKey"]
        signature = resolution["signature"]
    except (KeyError, TypeError) as e:
        raise InvalidResolution(f"malformed resolve proof: {e}") from e
    if signer not in allowed_keys:
        raise InvalidResolution(
            "the signer is not an authority for this run — neither its "
            "segment head nor its provider (cannot resolve it)"
        )
    if not verify_signature(signer, signature, resolve_payload(run_id, ask_ids)):
        raise InvalidResolution(
            "resolve signature does not verify — it must sign this run's "
            "outstanding asks, exactly"
        )
    return signer


def verify_cancel(cancel: dict, run_id: str, allowed_keys: set[str]) -> str:
    """Verifies a cancel proof for a run and returns the signer."""
    return _verify_signed_act(
        cancel, run_id, cancel_payload, allowed_keys, InvalidCancel, "cancel",
    )


def verify_view(view: dict, run_id: str, allowed_keys: set[str]) -> str:
    """Verifies a view proof for a run and returns the signer."""
    return _verify_signed_act(
        view, run_id, view_payload, allowed_keys, InvalidView, "view",
    )


class FunduqIdentity:
    """A funduq instance's own signing identity, distinct from any provider's."""

    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._private_key = private_key
        self.public_key = private_key.public_key().public_bytes_raw().hex()

    def dispatch_hop(self, prev_chain: list[str], agent: "AgentRef") -> list[str]:
        """Extends `prev_chain` with this funduq's hop for a dispatch to `agent`."""
        return _dispatch_hop(
            self._private_key,
            prev_chain,
            DispatchTarget(provider_key=agent.provider_key, name=agent.name),
        )

    @classmethod
    def from_hex(cls, private_key_hex: str) -> "FunduqIdentity":
        """Builds an identity from a 32-byte seed given as 64 hex chars."""
        try:
            raw = bytes.fromhex(private_key_hex)
        except ValueError as e:
            raise ValueError("identity_private_key is not valid hex") from e
        if len(raw) != 32:
            raise ValueError(
                f"identity_private_key must be a 32-byte seed (64 hex chars), got {len(raw)} bytes"
            )
        return cls(Ed25519PrivateKey.from_private_bytes(raw))

    @staticmethod
    def generate_hex() -> str:
        """Generates a fresh private key and returns it as a 32-byte hex seed."""
        return Ed25519PrivateKey.generate().private_bytes_raw().hex()

    def sign(self, payload: bytes) -> str:
        """Signs `payload` with this identity's private key, returning the signature as hex."""
        return self._private_key.sign(payload).hex()


