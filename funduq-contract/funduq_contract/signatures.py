"""Checking an Ed25519 signature, and choosing a nonce."""

from __future__ import annotations

import hashlib
import secrets

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


FINGERPRINT_HEX_LENGTH = 16


def verify_signature(public_key_hex: str, signature_hex: str, payload: bytes) -> bool:
    """Returns True iff `signature_hex` is a valid Ed25519 signature over `payload` for `public_key_hex`."""
    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        public_key.verify(bytes.fromhex(signature_hex), payload)
        return True
    except (InvalidSignature, ValueError):
        return False


def new_nonce() -> str:
    """A fresh 128-bit hex nonce for one side of a link-open challenge."""
    return secrets.token_hex(16)


def provider_fingerprint(public_key: str) -> str:
    """A short, deterministic identifier for a provider, derived from its public key."""
    return hashlib.sha256(bytes.fromhex(public_key)).hexdigest()[:FINGERPRINT_HEX_LENGTH]


def is_fingerprint(value: str) -> bool:
    return len(value) == FINGERPRINT_HEX_LENGTH
