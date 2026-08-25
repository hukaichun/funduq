from __future__ import annotations

import pytest

from funduq.identity import InvalidChain, verify_chain


def test_empty_chain_is_rejected(new_identity):
    with pytest.raises(InvalidChain, match="empty"):
        verify_chain([])


def test_single_hop_chain_verifies(new_identity):
    identity = new_identity()
    chain = [identity.sign_chain_hop()]

    result = verify_chain(chain)

    assert result.actor_public_keys == [identity.public_key]
    assert result.head == identity.public_key


def test_multi_hop_chain_verifies_in_order(new_identity):
    a, b, c = new_identity(), new_identity(), new_identity()
    hop0 = a.sign_chain_hop()
    hop1 = b.sign_chain_hop(prev_token=hop0)
    hop2 = c.sign_chain_hop(prev_token=hop1)

    result = verify_chain([hop0, hop1, hop2])

    assert result.actor_public_keys == [a.public_key, b.public_key, c.public_key]
    assert result.head == a.public_key, "the first signer is the segment's authority"


def test_reordered_hops_rejected(new_identity):
    a, b = new_identity(), new_identity()
    hop0 = a.sign_chain_hop()
    hop1 = b.sign_chain_hop(prev_token=hop0)

    with pytest.raises(InvalidChain, match="prevHash"):
        verify_chain([hop1, hop0])


def test_spliced_hop_from_different_chain_rejected(new_identity):
    a, b, foreign = new_identity(), new_identity(), new_identity()
    hop0 = a.sign_chain_hop()
    hop1 = b.sign_chain_hop(prev_token=hop0)
    foreign_hop0 = foreign.sign_chain_hop()
    spliced_hop1 = b.sign_chain_hop(prev_token=foreign_hop0)

    with pytest.raises(InvalidChain, match="prevHash"):
        verify_chain([hop0, spliced_hop1])


def test_a_legacy_hop_still_stamping_subject_verifies(new_identity):
    """`subject` was retired from the hop format: it was the signer's own
    unverifiable claim, and a chain carries keys and nothing else. A signer
    still stamping it produces an unknown claim, which is ignored."""
    import time

    import jwt

    identity = new_identity()
    now = int(time.time())
    legacy = jwt.encode(
        {
            "subject": {"type": "user", "id": "employee_x"},
            "actorPublicKey": identity.public_key,
            "prevHash": None,
        },
        identity._private_key,
        algorithm="EdDSA",
    )
    assert verify_chain([legacy]).head == identity.public_key


def test_a_hop_is_exactly_two_claims(new_identity):
    """The chain is only keys: a hop carries the signer's key and the link to
    the hop before it, and nothing else — no `subject`, and no time. Freshness
    is the authenticating seat's job, not a hop's, so there is no expiry here
    to enforce, honour, or work around."""
    import jwt

    a, b = new_identity(), new_identity()
    hop0 = a.sign_chain_hop()
    hop1 = b.sign_chain_hop(prev_token=hop0)

    for hop in (hop0, hop1):
        claims = jwt.decode(hop, options={"verify_signature": False})
        assert set(claims) == {"actorPublicKey", "prevHash"}


def test_the_presenter_is_the_last_hop_not_the_head(new_identity):
    """`head` answers for the work; `presenter` handed it over just now. They
    are the same party only on a chain nobody extended, and confusing them is
    the whole replay: a provider presenting its caller's chain has the
    caller's head and its own presenter."""
    caller, provider = new_identity(), new_identity()
    hop0 = caller.sign_chain_hop()
    chain = [hop0, provider.sign_chain_hop(prev_token=hop0)]

    result = verify_chain(chain)

    assert result.head == caller.public_key
    assert result.presenter == provider.public_key
    assert verify_chain([hop0]).presenter == caller.public_key
