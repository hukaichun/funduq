"""What this package owes on its own, testable without core or an SDK.

The *values* are not asserted here — `docs/contract-vectors.json` pins those,
and it pins them as recorded bytes rather than as whatever the code currently
produces, which is the whole reason it exists. What this file asserts is the
structure those values have to keep: that no two acts share a payload, that a
chain links and refuses to be rewritten, and that a verifier says False
rather than exploding on garbage.
"""

from __future__ import annotations

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from funduq_contract import (
    InvalidChain,
    cancel_payload,
    delegation_payload,
    dispatch_hop,
    extend_chain,
    funduq_connect_payload,
    kyok_call_payload,
    new_chain,
    provider_connect_payload,
    resolve_payload,
    verify_chain,
    verify_signature,
)


def _key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def _hex(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes_raw().hex()


def test_no_two_acts_produce_the_same_bytes():
    """The domain tag is what stops a signature made for one act being spent as
    another — a resolution replayed as a cancel, or a provider's connect proof
    reflected back as funduq's answering one. Nothing else in the system
    enforces that the tags differ, so it is asserted where they are written."""
    payloads = [
        provider_connect_payload("fk", "n1", "n2"),
        funduq_connect_payload("n1", "n2"),
        kyok_call_payload("bearer", 1, "hash"),
        delegation_payload("delegate", 1),
        resolve_payload("run", 1),
        cancel_payload("run", 1),
    ]
    prefixes = [p.split(b":", 1)[0] for p in payloads]

    assert len(set(prefixes)) == len(prefixes), f"two acts share a domain tag: {prefixes}"
    assert len(set(payloads)) == len(payloads)


def test_the_same_arguments_always_give_the_same_bytes():
    """Pure functions of their arguments — no clock, no randomness, nothing
    read from the environment. An implementation in another language can
    reproduce them from the vectors alone, which it could not if anything here
    varied per call."""
    assert resolve_payload("run", 1) == resolve_payload("run", 1)
    assert resolve_payload("run", 1) != resolve_payload("run", 2)
    assert resolve_payload("run", 1) != resolve_payload("other", 1)


def test_a_chain_links_and_reports_both_of_its_ends():
    head_key, middle, tail = _key(), _key(), _key()

    chain = extend_chain(tail, extend_chain(middle, new_chain(head_key)))
    result = verify_chain(chain)

    assert result.actor_public_keys == [_hex(head_key), _hex(middle), _hex(tail)]
    assert result.head == _hex(head_key), "who answers for the work"
    assert result.presenter == _hex(tail), "who is offering it now"


def test_a_single_hop_is_its_own_head_and_presenter():
    only = _key()
    result = verify_chain(new_chain(only))
    assert result.head == result.presenter == _hex(only)


def test_a_hop_carries_the_signers_key_and_the_link_and_nothing_else():
    a, b = _key(), _key()
    chain = extend_chain(b, new_chain(a))

    for hop in chain:
        claims = jwt.decode(hop, options={"verify_signature": False})
        assert set(claims) == {"actorPublicKey", "prevHash"}


def test_a_dispatch_hop_names_where_it_went():
    """The one hop that carries a third claim, and the only thing that makes an
    erased hand noticeable: an agent is `(provider_key, name)`, and that
    provider key is what signs the next hop when the provider extends
    honestly."""
    funduq_key, caller = _key(), _key()

    chain = dispatch_hop(funduq_key, new_chain(caller), "provider-key-hex", "translator")

    claims = jwt.decode(chain[-1], options={"verify_signature": False})
    assert claims["dispatchedTo"] == {"providerKey": "provider-key-hex", "name": "translator"}
    assert verify_chain(chain).presenter == _hex(funduq_key)


def test_a_forged_hop_is_refused():
    victim, forger = _key(), _key()
    forged = jwt.encode(
        {"actorPublicKey": _hex(victim), "prevHash": None}, forger, algorithm="EdDSA"
    )
    with pytest.raises(InvalidChain):
        verify_chain([forged])


def test_a_hop_from_another_chain_cannot_be_grafted_on():
    a, b = _key(), _key()
    real = new_chain(a)
    grafted = extend_chain(b, new_chain(_key()))[-1]

    with pytest.raises(InvalidChain):
        verify_chain([*real, grafted])


def test_a_reordered_chain_is_refused():
    a, b = _key(), _key()
    chain = extend_chain(b, new_chain(a))

    with pytest.raises(InvalidChain):
        verify_chain(list(reversed(chain)))


def test_an_empty_chain_is_refused_rather_than_returning_nothing():
    with pytest.raises(InvalidChain):
        verify_chain([])


def test_extending_nothing_is_an_error():
    """Starting a chain and extending one are different acts: the first makes
    its signer the head. Silently treating an empty chain as a start would make
    a party the authority by accident."""
    with pytest.raises(ValueError):
        extend_chain(_key(), [])


def test_a_hop_stamping_time_still_verifies():
    """A hop carries no expiry, and this verifier reads none — freshness needs
    a live presenter and it sees bytes. A signer that stamps `exp` anyway,
    even one long past, is not refused: unknown claims are ignored the way
    unknown fields are ignored everywhere else."""
    a = _key()
    stamped = jwt.encode(
        {"actorPublicKey": _hex(a), "prevHash": None, "iat": 1, "exp": 2},
        a,
        algorithm="EdDSA",
    )
    assert verify_chain([stamped]).head == _hex(a)


def test_verify_signature_answers_false_instead_of_raising():
    """Every failure means the same thing at every call site — bad signature,
    wrong key, malformed hex — so they get the same answer. An exception for
    one of them would invite it being handled differently by accident."""
    key = _key()
    payload = resolve_payload("run", 1)
    signature = key.sign(payload).hex()

    assert verify_signature(_hex(key), signature, payload)
    assert not verify_signature(_hex(_key()), signature, payload)
    assert not verify_signature(_hex(key), signature, b"different bytes")
    assert not verify_signature("not-hex", signature, payload)
    assert not verify_signature(_hex(key), "zz", payload)
