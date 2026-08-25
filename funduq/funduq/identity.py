from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import hashlib
import time
from dataclasses import dataclass

import jwt
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

if TYPE_CHECKING:
    from funduq.models import AgentRef



# The format is funduq-contract's, and these names are re-exported rather
# than rewritten. Core used to carry its own copy of every payload and of the
# chain format — a second opinion that was really an echo. What stays here is
# what core actually decides: which keys an act is allowed to come from, and
# how fresh a timestamp has to be. That is policy, not format.
from funduq_contract import (
    FINGERPRINT_HEX_LENGTH,
    ChainResult,
    InvalidChain as InvalidChain,
    cancel_payload as cancel_payload,
    delegation_payload as delegation_payload,
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
)


SESSION_TOKEN_TTL_SECONDS = 3600

SIGNATURE_FRESHNESS_WINDOW_SECONDS = 60


def is_timestamp_fresh(timestamp: int) -> bool:
    return abs(time.time() - timestamp) <= SIGNATURE_FRESHNESS_WINDOW_SECONDS


class InvalidDelegation(ValueError):
    pass


def verify_delegation(certificate: dict) -> str:
    """Verifies a session delegation certificate and returns the authority's public key.

    `certificate` is `{"authorityPublicKey", "delegatePublicKey",
    "expiresAt", "signature"}`: the authority signed
    `delegation_payload(delegatePublicKey, expiresAt)`. Raises
    `InvalidDelegation` if the signature fails or the certificate has
    expired. The certificate alone moves nothing — only the named delegate's
    own signatures gain the authority — so it is safe to store and to relay.
    """
    try:
        authority = certificate["authorityPublicKey"]
        delegate = certificate["delegatePublicKey"]
        expires_at = int(certificate["expiresAt"])
        signature = certificate["signature"]
    except (KeyError, TypeError, ValueError) as e:
        raise InvalidDelegation(f"malformed delegation certificate: {e}") from e
    if time.time() > expires_at:
        raise InvalidDelegation("delegation certificate has expired")
    if not verify_signature(
        authority, signature, delegation_payload(delegate, expires_at)
    ):
        raise InvalidDelegation("delegation certificate signature does not verify")
    return authority


class InvalidResolution(ValueError):
    pass


class InvalidCancel(ValueError):
    pass


def _verify_signed_act(
    proof: dict,
    run_id: str,
    payload_for: Callable[[str, int], bytes],
    allowed_keys: set[str],
    delegation: dict | None,
    invalid: type[ValueError],
    act: str,
) -> str:
    """Verifies one singular signed act against an authority set and returns the
    effective authority.

    `proof` is `{"publicKey", "timestamp", "signature"}`. With a delegation
    certificate naming the signer, the certificate's authority is the
    effective key — rights attach to the durable key and a session key is a
    glove; otherwise the signer stands for itself. The effective key must be
    in `allowed_keys`, and the timestamp inside the freshness window.

    One function for resolving an ask and for cancelling a run, because they
    are the same act with different words: prove you hold a key this run's
    segment answers to, once, now. What keeps them apart is the payload's
    own tag, so neither signature is ever the other.
    """
    try:
        signer = proof["publicKey"]
        timestamp = int(proof["timestamp"])
        signature = proof["signature"]
    except (KeyError, TypeError, ValueError) as e:
        raise invalid(f"malformed {act} proof: {e}") from e
    effective = signer
    if delegation is not None:
        authority = verify_delegation(delegation)
        if delegation.get("delegatePublicKey") == signer:
            effective = authority
    if effective not in allowed_keys:
        raise invalid(
            f"the signer is not an authority for this run — neither its "
            f"segment head nor its provider (cannot {act} it)"
        )
    if not is_timestamp_fresh(timestamp):
        raise invalid(f"{act} timestamp outside the freshness window")
    if not verify_signature(signer, signature, payload_for(run_id, timestamp)):
        raise invalid(f"{act} signature does not verify")
    return effective


def verify_resolution(
    resolution: dict,
    run_id: str,
    allowed_keys: set[str],
    delegation: dict | None = None,
) -> str:
    """Verifies a resolution proof for a paused run and returns the effective authority.

    The signer signed `resolve_payload(run_id, timestamp)`, and
    `allowed_keys` is the ask's authority set: the run's chain head and the
    agent's own provider key. Raises `InvalidResolution` on any failure.
    """
    return _verify_signed_act(
        resolution, run_id, resolve_payload,
        allowed_keys, delegation, InvalidResolution, "resolve",
    )


def verify_cancel(
    cancel: dict,
    run_id: str,
    allowed_keys: set[str],
    delegation: dict | None = None,
) -> str:
    """Verifies a cancel proof for a run and returns the effective authority.

    The signer signed `cancel_payload(run_id, timestamp)`, and
    `allowed_keys` is the run's authority set — the same one an ask on it
    would have: its chain head and the agent's own provider key. Raises
    `InvalidCancel` on any failure.

    Stopping someone else's run is a rights question, not an addressing
    one. A run id is an identifier, and [rule
    zero](../../docs/design-records.md#rule-zero-identifiers-are-never-credentials)
    says an identifier is never a credential — so possession of the id buys
    nothing here, and what counts is a signature from a key the run's
    segment answers to.
    """
    return _verify_signed_act(
        cancel, run_id, cancel_payload,
        allowed_keys, delegation, InvalidCancel, "cancel",
    )


class FunduqIdentity:
    """A funduq instance's own signing identity, distinct from any provider's.

    Two instances built from different keys are different identities that
    don't verify each other's signatures; the same key hex produces the
    same public identity across restarts, letting a provider pin funduq by
    its public key.
    """

    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._private_key = private_key
        self.public_key = private_key.public_key().public_bytes_raw().hex()

    def dispatch_hop(self, prev_chain: list[str], agent: "AgentRef") -> list[str]:
        """Extends `prev_chain` with this funduq's hop for a dispatch to `agent`.

        The `AgentRef` is unpacked here rather than handed on, because
        funduq-contract does not know core's types and should not have to —
        what the format needs is the pair `(provider_key, name)` an agent is
        addressed by. See `funduq_contract.dispatch_hop` for what naming the
        destination buys.
        """
        return _dispatch_hop(self._private_key, prev_chain, agent.provider_key, agent.name)

    @classmethod
    def from_hex(cls, private_key_hex: str) -> "FunduqIdentity":
        """Builds an identity from a 32-byte seed given as 64 hex chars.

        Raises `ValueError` if the string isn't valid hex or doesn't
        decode to exactly 32 bytes.
        """
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


