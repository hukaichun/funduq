"""The actor-chain hop format: how one is built, and what verifying proves."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


class InvalidChain(ValueError):
    """A chain that fails verification: forged, reordered, truncated, spliced, or malformed."""


@dataclass(frozen=True)
class DispatchTarget:
    """Where a witness handed the work: one agent, addressed as it always is."""

    provider_key: str
    name: str


@dataclass(frozen=True)
class Hop:
    """One hop, after parsing."""

    actor_public_key: str
    prev_hash: str | None
    dispatched_to: DispatchTarget | None


def _parse_hop(index: int, payload: dict[str, Any]) -> Hop:
    """The one place claims become a `Hop`."""
    actor_public_key = payload.get("actorPublicKey")
    if not isinstance(actor_public_key, str):
        raise InvalidChain(f"hop {index}: missing actorPublicKey")

    prev_hash = payload.get("prevHash")
    if prev_hash is not None and not isinstance(prev_hash, str):
        raise InvalidChain(f"hop {index}: prevHash is not a string")

    dispatched_to: DispatchTarget | None = None
    if "dispatchedTo" in payload:
        claimed = payload["dispatchedTo"]
        if not isinstance(claimed, dict):
            raise InvalidChain(f"hop {index}: dispatchedTo is not an object")
        provider_key, name = claimed.get("providerKey"), claimed.get("name")
        if not isinstance(provider_key, str) or not isinstance(name, str):
            raise InvalidChain(
                f"hop {index}: dispatchedTo needs a providerKey and a name, both strings"
            )
        dispatched_to = DispatchTarget(provider_key=provider_key, name=name)

    return Hop(
        actor_public_key=actor_public_key, prev_hash=prev_hash, dispatched_to=dispatched_to
    )


@dataclass(frozen=True)
class ChainResult:
    """A verified chain: every hop, in order, head first."""

    hops: list[Hop]

    @property
    def actor_public_keys(self) -> list[str]:
        """Each hop's signing key, in order."""
        return [hop.actor_public_key for hop in self.hops]

    @property
    def head(self) -> str:
        """The first hop's signer: the responsibility segment's authority."""
        return self.actor_public_keys[0]

    @property
    def presenter(self) -> str:
        """The last hop's signer: the party offering this chain."""
        return self.actor_public_keys[-1]


def hop_hash(token: str) -> str:
    """The sha256 a following hop puts in its `prevHash`."""
    return hashlib.sha256(token.encode()).hexdigest()


def sign_hop(
    private_key: Ed25519PrivateKey,
    prev_token: str | None = None,
    dispatched_to: DispatchTarget | None = None,
) -> str:
    """One hop, signed by `private_key`, linked to `prev_token` if there is one."""
    claims: dict[str, Any] = {
        "actorPublicKey": private_key.public_key().public_bytes_raw().hex(),
        "prevHash": hop_hash(prev_token) if prev_token is not None else None,
    }
    if dispatched_to is not None:
        claims["dispatchedTo"] = {
            "providerKey": dispatched_to.provider_key,
            "name": dispatched_to.name,
        }
    return jwt.encode(claims, private_key, algorithm="EdDSA")


def new_chain(private_key: Ed25519PrivateKey) -> list[str]:
    """Starts a chain: one hop, whose signer is the head — the segment's authority."""
    return [sign_hop(private_key, None)]


def extend_chain(private_key: Ed25519PrivateKey, prev_chain: list[str]) -> list[str]:
    """Appends a hop signed by `private_key`, hash-linked to the chain's tail."""
    if not prev_chain:
        raise ValueError("extend_chain requires a non-empty chain — use new_chain to start one")
    return [*prev_chain, sign_hop(private_key, prev_chain[-1])]


def dispatch_hop(
    private_key: Ed25519PrivateKey, prev_chain: list[str], target: DispatchTarget
) -> list[str]:
    """Extends `prev_chain` with a hop recording a dispatch to one agent, as `{"providerKey", "name"}` under `dispatchedTo`."""
    return [*prev_chain, sign_hop(private_key, prev_chain[-1], target)]


def verify_chain(chain: list[str]) -> ChainResult:
    """Verifies a chain and returns each hop's actor key, in order (head first)."""
    if not chain:
        raise InvalidChain("empty actor chain")

    hops: list[Hop] = []
    prev_token: str | None = None
    previous: Hop | None = None

    for i, token in enumerate(chain):
        try:
            unverified = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError as e:
            raise InvalidChain(f"hop {i}: unparseable token: {e}") from e

        hop = _parse_hop(i, unverified)
        try:
            public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(hop.actor_public_key))
        except ValueError as e:
            raise InvalidChain(f"hop {i}: malformed actorPublicKey: {e}") from e

        try:
            jwt.decode(token, key=public_key, algorithms=["EdDSA"], options={"verify_exp": False})
        except jwt.PyJWTError as e:
            raise InvalidChain(f"hop {i}: signature check failed: {e}") from e

        expected_prev_hash = hop_hash(prev_token) if prev_token is not None else None
        if hop.prev_hash != expected_prev_hash:
            raise InvalidChain(
                f"hop {i}: prevHash doesn't match — chain reordered, truncated, or spliced"
            )

        if previous is not None and previous.dispatched_to is not None:
            if hop.actor_public_key == previous.dispatched_to.provider_key:
                pass  # the party it named accepted
            elif hop.actor_public_key == previous.actor_public_key:
                # The witness itself, which it may be only to offer the same work onward — and offering is another dispatch.
                if hop.dispatched_to is None:
                    raise InvalidChain(
                        f"hop {i}: signed by the witness that dispatched at hop {i - 1}, "
                        "but it is not itself a dispatch — a witness appears in a chain "
                        "only as a witness, so it may re-offer work nobody took and may "
                        "never sign as a party"
                    )
            else:
                raise InvalidChain(
                    f"hop {i}: the hop before it dispatched to "
                    f"{previous.dispatched_to.provider_key[:16]}…, but this hop is signed "
                    f"by {hop.actor_public_key[:16]}… — a hop that dispatched and its "
                    "successor must agree, and only the party it named or the witness "
                    "that named it may sign here"
                )

        hops.append(hop)
        prev_token, previous = token, hop

    return ChainResult(hops=hops)
