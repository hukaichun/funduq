from __future__ import annotations

import pytest

from funduq_provider_sdk import InvalidChain, ProviderIdentity, verify_chain


def test_a_chain_verifies_and_names_each_hop_in_order():
    a, b = ProviderIdentity.generate(), ProviderIdentity.generate()
    chain = b.extend_chain(a.new_chain())

    result = verify_chain(chain)

    assert result.actor_public_keys == [a.public_key, b.public_key]
    assert result.head == a.public_key, "the first signer is the segment's authority"


def test_an_empty_chain_is_invalid():
    with pytest.raises(InvalidChain):
        verify_chain([])


def test_a_grafted_hop_from_another_chain_is_rejected():
    a, b = ProviderIdentity.generate(), ProviderIdentity.generate()
    real = a.new_chain()
    foreign = b.new_chain()
    grafted = b.sign_hop(prev_token=foreign[0])

    with pytest.raises(InvalidChain, match="prevHash"):
        verify_chain([*real, grafted])


def test_a_legacy_hop_still_stamping_subject_verifies():
    """The retired `subject` field is an unknown claim now: a signer still
    stamping it produces a chain that verifies — the field just carries no
    meaning to anyone."""
    import time

    import jwt

    a = ProviderIdentity.generate()
    now = int(time.time())
    legacy = jwt.encode(
        {
            "subject": {"type": "user", "id": "employee_x"},
            "actorPublicKey": a.public_key,
            "prevHash": None,
        },
        a._private_key,
        algorithm="EdDSA",
    )
    assert verify_chain([legacy]).head == a.public_key


def test_a_hop_is_exactly_two_claims():
    """The chain is only keys: a hop carries the signer's key and the link to
    the hop before it, and nothing else — no `subject`, and no time. Freshness
    is the authenticating seat's job, not a hop's, so there is no expiry here
    to enforce, honour, or work around. The independent twin of funduq's own
    format test."""
    import jwt

    a, b = ProviderIdentity.generate(), ProviderIdentity.generate()
    hop0 = a.sign_hop()
    hop1 = b.sign_hop(prev_token=hop0)

    for hop in (hop0, hop1):
        claims = jwt.decode(hop, options={"verify_signature": False})
        assert set(claims) == {"actorPublicKey", "prevHash"}
