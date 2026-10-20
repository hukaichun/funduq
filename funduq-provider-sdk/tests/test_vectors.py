from __future__ import annotations

import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from funduq_provider_sdk import (
    ProviderIdentity,
    provider_connect_payload,
    funduq_connect_payload,
    kyok_call_payload,
    verify_signature,
)
from funduq_provider_sdk import cancel_payload, resolve_payload

VECTORS = json.loads((Path(__file__).parent.parent.parent / "docs" / "contract-vectors.json").read_text())

BUILDERS = {
    "kyok-call": lambda i: kyok_call_payload(i["bearer"], i["timestamp"], i["body_sha256_hex"]),
    "provider-connect": lambda i: provider_connect_payload(
        i["funduq_public_key"], i["funduq_nonce"], i["provider_nonce"]
    ),
    "funduq-connect": lambda i: funduq_connect_payload(i["funduq_nonce"], i["provider_nonce"]),
    "resolution": lambda i: resolve_payload(i["run_id"], i["ask_ids"]),
    "cancel": lambda i: cancel_payload(i["run_id"], i["timestamp"]),
}


def _identity() -> ProviderIdentity:
    return ProviderIdentity(
        Ed25519PrivateKey.from_private_bytes(
            bytes.fromhex(VECTORS["test_key"]["private_key_hex"])
        )
    )


def test_this_side_reproduces_every_vector_it_has_a_builder_for():
    identity = _identity()
    assert identity.public_key == VECTORS["test_key"]["public_key_hex"]
    covered = 0
    for vector in VECTORS["vectors"]:
        builder = BUILDERS.get(vector["kind"])
        if builder is None:
            continue
        covered += 1
        payload = builder(vector["inputs"])
        assert payload == vector["payload_utf8"].encode(), vector["kind"]
        assert identity.sign(payload) == vector["signature_hex"], vector["kind"]
        assert verify_signature(identity.public_key, vector["signature_hex"], payload)
    assert covered == len(BUILDERS)


def test_the_delivered_run_model_round_trips_under_either_spelling():
    """The model is the agreement; how a transport spells it is the
    transport's (#282), so this asserts the model's own symmetry rather than
    matching a published envelope.

    `forwardedProps` is the case worth pinning: legitimately `null` and
    required, so a dump that drops it turns a good run into a permanent
    refusal instead of a loud error.
    """
    from ag_ui.core import RunAgentInput

    from funduq_provider_sdk import DeliveredRun

    run_input = RunAgentInput(
        threadId="t-1",
        runId="run-1",
        state={},
        messages=[{"id": "m1", "role": "user", "content": "hi"}],
        tools=[],
        context=[],
        forwardedProps=None,
    )
    delivered = DeliveredRun(runId="run-1", agentName="translator", runInput=run_input)

    for dumped in (
        delivered.model_dump(mode="json"),
        delivered.model_dump(mode="json", by_alias=True),
    ):
        assert DeliveredRun.model_validate(dumped) == delivered
        carried = dumped.get("runInput", dumped.get("run_input"))
        assert "forwardedProps" in carried or "forwarded_props" in carried


def test_the_published_chain_verifies_here_too_and_can_be_reproduced():
    import jwt as _jwt
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey as _Key

    from funduq_provider_sdk import verify_chain

    (vector,) = [c for c in VECTORS["chains"] if c["kind"] == "actor-chain"]

    result = verify_chain(vector["chain"])
    assert result.actor_public_keys == vector["actor_public_keys"]
    assert result.head == vector["actor_public_keys"][0]

    first_key = _Key.from_private_bytes(bytes.fromhex(vector["inputs"]["hop_private_keys_hex"][0]))
    reproduced = _jwt.encode(
        {
            "actorPublicKey": vector["actor_public_keys"][0],
            "prevHash": None,
        },
        first_key,
        algorithm="EdDSA",
    )
    assert reproduced == vector["chain"][0]


def test_the_props_twins_are_guarded_where_both_sides_are_importable():
    """The SDK-side dual of the tag-scan guard used to read funduq's keys off a
    published frame. It now lives in funduq's own suite
    (`test_the_sdk_reads_every_key_funduq_actually_puts_under_its_own`), built
    from `build_forwarded_props` instead of a frozen sample — the only place
    both sides can be imported, and the only version that checks what funduq
    emits today rather than what a json file remembered (#282).

    A hand-restated copy of these shapes drifted once on one field's
    nullability and silently dropped verified caller identities, so what is
    kept here is that this package still exports the twins to guard.
    """
    from funduq_provider_sdk import KyokForwardedProps, verify_chain

    assert callable(verify_chain)
    assert set(KyokForwardedProps.model_fields) == {"token"}
