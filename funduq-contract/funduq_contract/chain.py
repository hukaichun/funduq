"""The actor-chain hop format: how one is built, and what verifying proves.

A chain answers "on whose behalf, through whose hands". Each hop is an EdDSA
JWT carrying exactly two claims — the signer's own `actorPublicKey` and a
`prevHash`, the sha256 of the previous hop's full JWT, null on the first —
plus `dispatchedTo` on the hop funduq signs for a dispatch. A chain carries
keys and nothing else: no subject, and **no time**.

Signing needs a private key, so `new_chain`, `extend_chain` and
`dispatch_hop` take one as an argument rather than holding it. Whose key it
is stays whoever's business it was.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


class InvalidChain(ValueError):
    """A chain that fails verification: forged, reordered, truncated, spliced, or malformed."""


@dataclass(frozen=True)
class ChainResult:
    """A verified chain: each hop's signing key, in order, head first."""

    actor_public_keys: list[str]

    @property
    def head(self) -> str:
        """The first hop's signer: the responsibility segment's authority."""
        return self.actor_public_keys[0]

    @property
    def presenter(self) -> str:
        """The last hop's signer: the party offering this chain.

        Named, rather than left as `actor_public_keys[-1]`, because this is
        the key an authenticating seat's principal is compared against and
        the two ends are easy to confuse — comparing `head` instead lets a
        provider replay its caller's chain, which is the whole attack.
        """
        return self.actor_public_keys[-1]


def hop_hash(token: str) -> str:
    """The sha256 a following hop puts in its `prevHash`."""
    return hashlib.sha256(token.encode()).hexdigest()


def sign_hop(
    private_key: Ed25519PrivateKey,
    prev_token: str | None = None,
    dispatched_to: dict[str, str] | None = None,
) -> str:
    """One hop, signed by `private_key`, linked to `prev_token` if there is one."""
    claims: dict[str, Any] = {
        "actorPublicKey": private_key.public_key().public_bytes_raw().hex(),
        "prevHash": hop_hash(prev_token) if prev_token is not None else None,
    }
    if dispatched_to is not None:
        claims["dispatchedTo"] = dispatched_to
    return jwt.encode(claims, private_key, algorithm="EdDSA")


def new_chain(private_key: Ed25519PrivateKey) -> list[str]:
    """Starts a chain: one hop, whose signer is the head — the segment's authority.

    A chain carries keys and nothing else; whom a key represents is a
    separate, opt-in disclosure (a voucher), never a hop field.
    """
    return [sign_hop(private_key, None)]


def extend_chain(private_key: Ed25519PrivateKey, prev_chain: list[str]) -> list[str]:
    """Appends a hop signed by `private_key`, hash-linked to the chain's tail.

    Extending is provenance, not authorization: the head stays the segment's
    authority however many hands the work passes through. Raises `ValueError`
    on an empty chain — starting one is `new_chain`, and the two are
    different acts.
    """
    if not prev_chain:
        raise ValueError("extend_chain requires a non-empty chain — use new_chain to start one")
    return [*prev_chain, sign_hop(private_key, prev_chain[-1])]


def dispatch_hop(
    private_key: Ed25519PrivateKey, prev_chain: list[str], provider_key: str, agent_name: str
) -> list[str]:
    """Extends `prev_chain` with a hop recording a dispatch to one agent,
    as `{"providerKey", "name"}` under `dispatchedTo`.

    This is the one thing that reaches a chain's **completeness**. Signatures
    and links prove nobody was inserted, reordered or spliced in; never that
    nobody was *removed*, and a party holding `caller → A → B` can rebuild it
    as `caller → B` forging nothing. What breaks that is naming the
    destination: an agent is addressed as `(provider_key, name)`, and the
    provider half is exactly the key that signs the next hop when that
    provider extends. So a hop and its successor check against each other —
    this one says it went to P, therefore the next must be signed by P — and
    a branch cannot satisfy both. Dropping the hop instead leaves a gap a
    consumer requiring these hops can refuse.
    """
    return [
        *prev_chain,
        sign_hop(private_key, prev_chain[-1], {"providerKey": provider_key, "name": agent_name}),
    ]


def verify_chain(chain: list[str]) -> ChainResult:
    """Verifies a chain and returns each hop's actor key, in order (head first).

    Each hop's signature must verify under its own embedded public key, and
    each hop after the first must link to the previous one via a matching
    `prevHash` — reordering, truncating, or splicing in a hop from a
    different chain breaks this and is rejected.

    **A hop has no expiry to check.** Freshness is not a question this can
    answer: it sees bytes, not a live presenter, so proving a presentation
    live belongs to the authenticating seat in front of the door, and no
    expiry is read here whatever a signer chose to stamp. Unknown claims are
    ignored for the same reason unknown fields are ignored elsewhere — a
    verifier that failed on them would break on every future addition.

    Raises `InvalidChain` on any failure, including an empty chain.
    """
    if not chain:
        raise InvalidChain("empty actor chain")

    actor_public_keys: list[str] = []
    prev_token: str | None = None

    for i, token in enumerate(chain):
        try:
            unverified = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError as e:
            raise InvalidChain(f"hop {i}: unparseable token: {e}") from e

        actor_public_key = unverified.get("actorPublicKey")
        if not isinstance(actor_public_key, str):
            raise InvalidChain(f"hop {i}: missing actorPublicKey")
        try:
            public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(actor_public_key))
        except ValueError as e:
            raise InvalidChain(f"hop {i}: malformed actorPublicKey: {e}") from e

        try:
            payload = jwt.decode(
                token, key=public_key, algorithms=["EdDSA"], options={"verify_exp": False}
            )
        except jwt.PyJWTError as e:
            raise InvalidChain(f"hop {i}: signature check failed: {e}") from e

        expected_prev_hash = hop_hash(prev_token) if prev_token is not None else None
        if payload.get("prevHash") != expected_prev_hash:
            raise InvalidChain(
                f"hop {i}: prevHash doesn't match — chain reordered, truncated, or spliced"
            )

        actor_public_keys.append(actor_public_key)
        prev_token = token

    return ChainResult(actor_public_keys=actor_public_keys)
