from __future__ import annotations


import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from funduq.identity import (
    InvalidChain,
    extend_chain,
    new_chain,
    verify_chain,
)


def _key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def _hex(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes_raw().hex()


def test_a_chain_survives_several_hops():
    agency, a, b = _key(), _key(), _key()

    chain = new_chain(agency)
    chain = extend_chain(a, chain)
    chain = extend_chain(b, chain)

    result = verify_chain(chain)
    assert result.actor_public_keys == [_hex(agency), _hex(a), _hex(b)]
    assert result.head == _hex(agency), "the originating signer is the segment's head"


def test_a_forged_hop_is_rejected():
    victim, forger = _key(), _key()
    forged = jwt.encode(
        {"actorPublicKey": _hex(victim), "prevHash": None},
        forger,
        algorithm="EdDSA",
    )
    with pytest.raises(InvalidChain):
        verify_chain([forged])


def test_a_spliced_chain_is_rejected():
    agency, a = _key(), _key()
    real = new_chain(agency)
    elsewhere = new_chain(_key())
    grafted = extend_chain(a, elsewhere)[-1]

    with pytest.raises(InvalidChain):
        verify_chain([*real, grafted])




def test_extending_nothing_is_an_error():
    with pytest.raises(ValueError):
        extend_chain(_key(), [])


def test_a_chain_built_across_the_custody_boundary_verifies(new_identity):
    """A hop signed through `ProviderIdentity` and one signed with a bare key
    link and verify together.

    This used to be two tests, one of which compared core's verifier against
    the SDK's. There is one verifier now, so that comparison became
    `f(x) == f(x)` and was deleted rather than left to look like coverage.
    What survives is the part that was never about the twins: the two sides
    hold their keys differently, and a chain still links across that.
    """
    remote = new_identity()
    sdk_chain = [remote.sign_chain_hop()]

    in_process = _key()
    chain = extend_chain(in_process, sdk_chain)

    result = verify_chain(chain)
    assert result.actor_public_keys == [remote.public_key, _hex(in_process)]
