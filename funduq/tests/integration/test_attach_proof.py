from __future__ import annotations

import pytest
from funduq_provider_sdk import ProviderIdentity

from funduq.core import Funduq
from funduq.errors import InvalidRegistration

from tests.conftest import DATABASE_URL, TEST_SIGNING_SECRET, publish_offline
from funduq.config import CoreSettings
from funduq.identity import FunduqIdentity
from funduq_contract import Registration


class _Stub:

    max_concurrent_runs = None

    def __init__(self, public_key: str) -> None:
        self.public_key = public_key

    async def deliver(self, run):
        return False

    async def cancel(self, run_id: str) -> bool:
        return True

    def takes_interjections(self, agent_name: str) -> bool:
        return False
class _Forged(_Stub):
    """Claims one identity's public key while holding a different private key."""

    def __init__(self, claimed_key: str, actual: ProviderIdentity) -> None:
        super().__init__(claimed_key)
        self._actual = actual

    def sign_connect(
        self, funduq_public_key: str, funduq_nonce: str, provider_nonce: str
    ) -> str:
        return self._actual.sign_connect(funduq_public_key, funduq_nonce, provider_nonce)


async def _registered(funduq, name: str) -> ProviderIdentity:
    identity = ProviderIdentity.generate()
    await publish_offline(funduq, identity, [Registration(name=name)])
    return identity


async def test_a_connection_that_cannot_sign_for_its_claimed_key_is_rejected(funduq):
    identity = await _registered(funduq, "forged")
    imposter = _Forged(identity.public_key, ProviderIdentity.generate())

    with pytest.raises(InvalidRegistration, match="invalid connect proof"):
        await funduq.attach_provider(imposter)


async def test_an_explicit_proof_must_answer_a_ticket_funduq_issued(funduq):
    identity = await _registered(funduq, "replayer")
    stub = _Stub(identity.public_key)
    proof = identity.sign_connect(funduq.identity_public_key, "not-a-funduq-ticket", "pn")

    with pytest.raises(InvalidRegistration, match="live ticket"):
        await funduq.attach_provider(
            stub, ticket="not-a-funduq-ticket", provider_nonce="pn", proof=proof
        )


async def test_a_ticket_admits_the_key_it_was_issued_to_and_no_other(funduq):
    """Issuing is the admission decision, so the ticket names who it admits.
    A ticket that leaks is worthless: only the named key can produce the
    signature that answers it."""
    admitted = await _registered(funduq, "admitted")
    stranger = ProviderIdentity.generate()
    ticket = funduq.issue_ticket(admitted.public_key)

    proof = stranger.sign_connect(funduq.identity_public_key, ticket, "pn")
    with pytest.raises(InvalidRegistration, match="live ticket"):
        await funduq.attach_provider(
            _Stub(stranger.public_key), ticket=ticket, provider_nonce="pn", proof=proof
        )


async def test_a_stranger_cannot_burn_a_ticket_it_merely_saw(funduq):
    """The ticket travels a channel funduq does not control, so seeing one is
    not exotic. Matching the named key **before** destroying it is what keeps
    a stranger's garbage proof from spending someone else's admission and
    leaving them unable to connect — a denial that needs no key at all."""
    admitted = await _registered(funduq, "unburnt")
    ticket = funduq.issue_ticket(admitted.public_key)

    stranger = ProviderIdentity.generate()
    with pytest.raises(InvalidRegistration):
        await funduq.attach_provider(
            _Stub(stranger.public_key),
            ticket=ticket,
            provider_nonce="pn",
            proof=stranger.sign_connect(funduq.identity_public_key, ticket, "pn"),
        )

    await funduq.attach_provider(
        _Stub(admitted.public_key),
        ticket=ticket,
        provider_nonce="pn",
        proof=admitted.sign_connect(funduq.identity_public_key, ticket, "pn"),
    )


async def test_a_ticket_is_single_use(funduq):
    identity = await _registered(funduq, "once")
    stub = _Stub(identity.public_key)
    ticket = funduq.issue_ticket(identity.public_key)
    proof = identity.sign_connect(funduq.identity_public_key, ticket, "pn")

    await funduq.attach_provider(stub, ticket=ticket, provider_nonce="pn", proof=proof)
    funduq.detach_all_for(identity.public_key)
    with pytest.raises(InvalidRegistration, match="live ticket"):
        await funduq.attach_provider(stub, ticket=ticket, provider_nonce="pn", proof=proof)


async def test_nothing_may_be_published_without_an_open_link(funduq):
    """The link is the credential for everything a provider does to its own
    roster. There is no signature to present instead, and no way to reach
    these without one."""
    identity = await _registered(funduq, "closed")
    stub = _Stub(identity.public_key)

    with pytest.raises(InvalidRegistration, match="not on an open link"):
        await funduq.register_agents(stub, [Registration(name="closed")])
    with pytest.raises(InvalidRegistration, match="not on an open link"):
        await funduq.delete_agent(stub, "closed")


async def test_a_silent_connection_is_rejected_and_the_signer_admitted():
    funduq = Funduq(
        CoreSettings(
            database_url=DATABASE_URL,
            token_signing_secret=TEST_SIGNING_SECRET,
            identity_private_key=FunduqIdentity.generate_hex(),
        )
    )
    try:
        identity = await _registered(funduq, "strict")

        with pytest.raises(InvalidRegistration, match="without a connect proof"):
            await funduq.attach_provider(_Stub(identity.public_key))

        signer = _Forged(identity.public_key, identity)
        await funduq.attach_provider(signer)
        await funduq.register_agents(signer, [Registration(name="strict")])
        from funduq.models import AgentRef

        assert funduq.is_serving(AgentRef(provider_key=identity.public_key, name="strict"))
    finally:
        await funduq.aclose()
