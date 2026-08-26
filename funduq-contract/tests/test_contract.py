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

from funduq_contract.chain import hop_hash
from funduq_contract import (
    DispatchTarget,
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


def _target(provider: Ed25519PrivateKey, name: str) -> DispatchTarget:
    """The agent a dispatch names, built the way `dispatch_hop` now takes it.

    A helper because the two halves used to be two adjacent string arguments:
    swapping them signed happily, verified happily, and rejected the *honest*
    successor with a message pointing at it. One argument of one type cannot
    be handed over backwards.
    """
    return DispatchTarget(provider_key=_hex(provider), name=name)


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

    chain = dispatch_hop(
        funduq_key,
        new_chain(caller),
        DispatchTarget(provider_key="provider-key-hex", name="translator"),
    )

    claims = jwt.decode(chain[-1], options={"verify_signature": False})
    assert claims["dispatchedTo"] == {"providerKey": "provider-key-hex", "name": "translator"}
    assert verify_chain(chain).presenter == _hex(funduq_key)


def test_a_hop_that_dispatched_and_its_successor_must_agree():
    """The check that makes a rewritten chain contradict itself.

    A dispatch hop names where funduq handed the work, and an agent is
    `(provider_key, name)` — so that provider key is exactly the key that
    signs the next hop when the provider extends honestly. A party rebuilding
    the chain to leave someone out has to sign after a dispatch hop naming
    somebody else, and the two no longer agree.

    `dispatchedTo` was written and never read for as long as it existed, so
    this property was *available* rather than enforced: a probe performed the
    comparison and the verifier did not.
    """
    funduq_key, caller, intended, impostor = _key(), _key(), _key(), _key()
    dispatched = dispatch_hop(funduq_key, new_chain(caller), _target(intended, "translator"))

    assert verify_chain(extend_chain(intended, dispatched)).presenter == _hex(intended)

    with pytest.raises(InvalidChain, match="must agree"):
        verify_chain(extend_chain(impostor, dispatched))


def test_a_chain_may_end_at_a_dispatch_nobody_answered():
    """The named party never signed. That is a break — declining to extend —
    and a break is a boundary rather than a defect, so the chain stands as the
    record of a handover that stopped there."""
    funduq_key, caller = _key(), _key()
    dispatched = dispatch_hop(funduq_key, new_chain(caller), _target(_key(), "translator"))

    assert verify_chain(dispatched).presenter == _hex(funduq_key)


def test_the_same_witness_may_offer_the_work_onward():
    """Nobody took it, so the witness names somebody else. Legal because the
    second dispatch is signed by **the same key** as the first — the witness
    is still the one handing the work over, and it is the signer that says so
    rather than anything the hop claims about itself."""
    funduq_key, caller, first, second = _key(), _key(), _key(), _key()

    chain = dispatch_hop(funduq_key, new_chain(caller), _target(first, "translator"))
    chain = dispatch_hop(funduq_key, chain, _target(second, "translator"))

    assert verify_chain(extend_chain(second, chain)).presenter == _hex(second)


def test_a_witness_appears_in_a_chain_only_as_a_witness():
    """The exemption above is for **re-offering**, and re-offering is another
    dispatch. A witness signing a plain hop after its own dispatch would be
    appearing as a party, which is the one thing a witness is not: it never
    heads a segment and never does the work.

    Nothing outside funduq can reach this — you need funduq's key to sign the
    hop — so it is not a hole, and that is the reason it was written the loose
    way. But the docstring said "the witness offering the same work onward"
    while the code accepted any hop the witness signed, and the rule's real
    edge sitting wider than its stated edge is precisely the shape the
    opt-out bug had. The narrow reading is also the true one, so the code
    moves to meet the prose.
    """
    funduq_key, caller, intended = _key(), _key(), _key()
    dispatched = dispatch_hop(funduq_key, new_chain(caller), _target(intended, "translator"))

    with pytest.raises(InvalidChain, match="only as a witness"):
        verify_chain(extend_chain(funduq_key, dispatched))


def test_a_verified_chain_hands_back_its_hops():
    """What a consumer needs in order to perform the check the docs describe.

    `mechanisms/actor-chain.md` tells a consumer to pin funduq's key and
    require a hop of funduq's on the path. Until now the only way to write
    that was to decode the JWT and index into the claim mapping by hand —
    which is not an inconvenience, it is the posture that produced the bug
    this rule exists for: two places reading the same claim and disagreeing
    about its shape. A verifier that returns only the keys leaves every
    consumer to re-derive the rest from the wire.
    """
    funduq_key, caller, provider = _key(), _key(), _key()
    chain = extend_chain(
        provider,
        dispatch_hop(funduq_key, new_chain(caller), _target(provider, "translator")),
    )

    result = verify_chain(chain)

    assert [hop.actor_public_key for hop in result.hops] == result.actor_public_keys
    assert result.hops[0].dispatched_to is None
    assert result.hops[1].dispatched_to == DispatchTarget(
        provider_key=_hex(provider), name="translator"
    )
    # The documented consumer check, written without touching a JWT.
    assert any(
        hop.actor_public_key == _hex(funduq_key) and hop.dispatched_to is not None
        for hop in result.hops
    ), "this work passed a witness whose key I pinned"


@pytest.mark.parametrize(
    ("claimed", "refusal"),
    [
        pytest.param(
            {"providerKey": "self-appointed", "name": "x"}, "must agree", id="well-formed"
        ),
        pytest.param("not-a-dict", "not an object", id="not an object"),
        pytest.param({"providerKey": 1, "name": "x"}, "both strings", id="wrong field type"),
        pytest.param({"name": "x"}, "both strings", id="missing a field"),
    ],
)
def test_a_branching_party_cannot_excuse_itself_by_claiming_a_dispatch(claimed, refusal):
    """The check may not be switched off by the hop being checked.

    Its first version skipped itself whenever the successor carried a
    `dispatchedTo`, on the reasoning that one dispatch may follow another —
    and the party being checked is the one writing that field, so the whole
    rule was opt-out. A branching party added it and passed. The malformed
    case was worse: it slipped the check *and* cleared the pending dispatch,
    so the hop after it went unchecked too.

    What decides whether a hop is a witness's is whose key signed it. The
    second dispatch in the test above is legal because funduq signed it, not
    because it looks like one.

    A well-formed claim is refused by the rule; a malformed one is refused as
    malformed, because `dispatchedTo` is funduq's own claim rather than an
    unknown one, and a known claim of the wrong shape is not the same as an
    absent claim. Reading it as absent is exactly what the first version did.
    """
    funduq_key, caller, intended, brancher = _key(), _key(), _key(), _key()
    dispatched = dispatch_hop(funduq_key, new_chain(caller), _target(intended, "translator"))

    forged = jwt.encode(
        {
            "actorPublicKey": _hex(brancher),
            "prevHash": hop_hash(dispatched[-1]),
            "dispatchedTo": claimed,
        },
        brancher,
        algorithm="EdDSA",
    )

    with pytest.raises(InvalidChain, match=refusal):
        verify_chain([*dispatched, forged])


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
