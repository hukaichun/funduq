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
class DispatchTarget:
    """Where a witness handed the work: one agent, addressed as it always is.

    A pair rather than a key alone because that is what an agent *is* here —
    a provider may serve several — and the provider half is what the check
    needs, since it is the key that signs the next hop when that provider
    accepts.
    """

    provider_key: str
    name: str


@dataclass(frozen=True)
class Hop:
    """One hop, after parsing. Everything past `_parse_hop` works on this.

    The JWT payload is the wire and stops there. Reaching into the claim
    mapping further in is how the dispatch check first went wrong: it asked
    `isinstance(value, dict)` in one place and `value is None` in another, so
    a `dispatchedTo` of the wrong shape counted as absent for one branch and
    present for the other, and the disagreement was a way through.

    **There is deliberately no `is_witness`.** One shipped in 0.0.3, unused,
    with a docstring warning against the reading it invites. A hop carrying
    `dispatchedTo` is a dispatch *claim*; whether it is a witness's is
    decided by `actor_public_key` — a key the reader pinned — so the honest
    predicate reads both fields, and a lone bool answers the question that
    must never be asked alone. Two readings of one thing is what caused the
    bug above; an accessor offering the second one is not worth its
    convenience.
    """

    actor_public_key: str
    prev_hash: str | None
    dispatched_to: DispatchTarget | None


def _parse_hop(index: int, payload: dict[str, Any]) -> Hop:
    """The one place claims become a `Hop`. Refuses a malformed one.

    A claim funduq does not know is ignored — a verifier failing on those
    would break on every future addition. `dispatchedTo` is not unknown, it
    is ours, and a known claim of the wrong shape is malformed rather than
    absent; treating it as absent is what let a branching party opt out of
    being checked. Unrecognised *keys inside* it are still ignored, so the
    target can gain fields without old verifiers refusing new chains.
    """
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
    """A verified chain: every hop, in order, head first.

    It used to be the signing keys alone, and that was too little to write
    the check this package's own documentation describes — pin funduq's key,
    require a hop of funduq's on the path. A consumer wanting that had to
    decode the JWT and index the claim mapping by hand, which is not an
    inconvenience: it is the posture that produced the dispatch bug, and ten
    call sites in this repository were standing in it. `verify_chain` already
    parses every hop; handing back only part of what it parsed sent everyone
    else back to the wire.
    """

    hops: list[Hop]

    @property
    def actor_public_keys(self) -> list[str]:
        """Each hop's signing key, in order. The chain's shape, without its claims."""
        return [hop.actor_public_key for hop in self.hops]

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
    dispatched_to: DispatchTarget | None = None,
) -> str:
    """One hop, signed by `private_key`, linked to `prev_token` if there is one.

    The claim names are written here and read in `_parse_hop`, and nowhere
    else: those two functions are the wire, and everything between them
    works on `Hop`.
    """
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
    private_key: Ed25519PrivateKey, prev_chain: list[str], target: DispatchTarget
) -> list[str]:
    """Extends `prev_chain` with a hop recording a dispatch to one agent,
    as `{"providerKey", "name"}` under `dispatchedTo`.

    `target` is one argument of one type because it used to be two adjacent
    interchangeable strings. Swapping them signed happily and verified
    happily; what broke was the *honest* provider extending it, refused with
    a message pointing at the innocent successor. The type that already
    existed for this stopped six lines short of the signature people call.

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
    return [*prev_chain, sign_hop(private_key, prev_chain[-1], target)]


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

    **A dispatch hop names the party that must sign next.** A hop carrying
    `dispatchedTo` is a witness saying where it handed the work, and the hop
    after it must be signed by one of exactly two keys: the provider that was
    named, or **the same key that signed the dispatching hop** — the witness
    offering the same work onward because nobody took it, which is itself
    another dispatch. Anyone else is a chain rewritten to leave someone out.
    A chain that *ends* at a dispatch hop is also legal: the named party
    never accepted, which is a break rather than a defect.

    That second allowance is narrow on purpose: **a witness appears in a
    chain only as a witness.** It never heads a segment and never does the
    work, so a plain hop under its key is a witness signing as a party and is
    refused. Nothing outside funduq can reach that case — it needs funduq's
    key — so this is not a hole being closed; it is the code's edge being
    moved back to where the sentence above always said it was. A rule whose
    real edge sits wider than its stated one is the shape the bug below had.

    **The successor's own claims decide nothing.** The first version of this
    check skipped itself whenever the next hop carried a `dispatchedTo` of
    its own, on the reasoning that one dispatch may follow another — which
    made the whole rule opt-out, since the party being checked writes that
    field. A branching party simply added it and passed, and a malformed
    value did worse: it slipped past the check *and* cleared the pending
    dispatch, so the hop after it went unchecked too. Whether a hop is a
    witness's is decided by whose key signed it, never by what it says about
    itself.

    This check was writable for as long as `dispatchedTo` has existed and
    was not read, so the property it gives — a branch contradicting itself
    — was available rather than enforced, and a probe rather than the
    verifier was the only thing performing it.

    Raises `InvalidChain` on any failure, including an empty chain.
    """
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
                # The witness itself, which it may be only to offer the same
                # work onward — and offering is another dispatch.
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
