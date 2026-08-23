from __future__ import annotations

import pytest

from funduq_provider_sdk import ProviderIdentity, provider_connect_payload


def test_a_connect_payload_is_exactly_these_bytes():
    assert provider_connect_payload("f0", "n1", "n2") == b"funduq-connect-provider:f0:n1:n2"


def test_the_connect_payload_says_nothing_about_what_will_be_served():
    """Opening a link proves the key; publishing a name is a separate act on
    the open link. The names used to be bound in here because the ticket was
    an anonymous nonce anyone could answer — a ticket issued to one key cannot
    be replayed at all, so there is nothing left for them to protect."""
    assert b"agent" not in provider_connect_payload("f0", "n1", "n2")


def test_an_identity_is_its_key_and_signs_the_ticket_it_was_given():
    identity = ProviderIdentity.generate()

    signature = identity.sign_connect("f0", "ticket", "mine")

    assert len(identity.public_key) == 64
    assert isinstance(signature, str)


def test_a_chain_grows_one_signed_hop_at_a_time(tmp_path):
    first, second = ProviderIdentity.generate(), ProviderIdentity.generate()

    chain = second.extend_chain(first.new_chain())

    assert len(chain) == 2


def test_extending_nothing_is_refused():
    with pytest.raises(ValueError):
        ProviderIdentity.generate().extend_chain([])


def test_an_identity_persists_so_a_restart_is_the_same_provider(tmp_path):
    path = tmp_path / "identity.key"

    first = ProviderIdentity.load_or_create(path)
    second = ProviderIdentity.load_or_create(path)

    assert first.public_key == second.public_key
