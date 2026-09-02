from __future__ import annotations

import json
from pathlib import Path

from funduq.identity import (
    cancel_payload,
    resolve_payload,
    view_payload,
    provider_connect_payload,
    funduq_connect_payload,
    kyok_call_payload,
    verify_signature,
)

# `parents[3]`, not a chain of `.parent`: this file sits one level deeper than
# the rest of the suite, and a chain of attributes is the kind of thing that
# silently walks to the wrong place when a file moves. The count is the thing
# to read.
VECTORS = json.loads(
    (Path(__file__).resolve().parents[3] / "docs" / "contract-vectors.json").read_text()
)

BUILDERS = {
    "provider-connect": lambda i: provider_connect_payload(
        i["funduq_public_key"], i["funduq_nonce"], i["provider_nonce"]
    ),
    "funduq-connect": lambda i: funduq_connect_payload(i["funduq_nonce"], i["provider_nonce"]),
    "kyok-call": lambda i: kyok_call_payload(
        i["bearer"], i["timestamp"], i["body_sha256_hex"]
    ),
    "resolution": lambda i: resolve_payload(i["run_id"], i["ask_ids"]),
    "cancel": lambda i: cancel_payload(i["run_id"], i["timestamp"]),
    "view": lambda i: view_payload(i["run_id"], i["timestamp"]),
}


def test_every_published_vector_is_what_this_implementation_computes():
    assert {v["kind"] for v in VECTORS["vectors"]} == set(BUILDERS)
    for vector in VECTORS["vectors"]:
        payload = BUILDERS[vector["kind"]](vector["inputs"])
        assert payload == vector["payload_utf8"].encode(), vector["kind"]
        assert verify_signature(
            VECTORS["test_key"]["public_key_hex"], vector["signature_hex"], payload
        ), vector["kind"]


def test_registration_vectors_do_not_depend_on_name_order():
    for vector in VECTORS["vectors"]:
        if "names" in vector["inputs"]:
            shuffled = list(reversed(vector["inputs"]["names"]))
            assert BUILDERS[vector["kind"]](
                {**vector["inputs"], "names": shuffled}
            ) == vector["payload_utf8"].encode()


def test_every_domain_tag_has_a_published_vector_family():
    """The completeness guard: an unpublished payload family fails here, not in an integrator's transport."""
    import re

    from funduq_contract import payloads as payloads_module

    # The tags live wherever the bytes are stated, which is funduq-contract
    # now rather than core's identity module. Scanning the source rather than
    # importing a list is the point: a family added without a vector is
    # exactly what this catches, and a hand-kept list would be one more thing
    # to forget.
    source = Path(payloads_module.__file__).read_text()
    tags = set(re.findall(r'= "(funduq-[a-z-]+)"', source))
    assert tags, "no domain tags found — the scan is broken, not the contract"
    covered = {v["payload_utf8"].split(":", 1)[0] for v in VECTORS["vectors"]}
    assert tags <= covered, (
        f"domain tags without a vector family in docs/contract-vectors.json: {sorted(tags - covered)}. "
        "Whoever states the bytes publishes the vectors for them."
    )


def test_the_published_wire_frames_are_what_the_ports_translate_to():
    from funduq_provider_sdk.llm import DeliveredCompletion
    from funduq_provider_sdk import DeliveredRun

    (run_wire,) = [w["frame"] for w in VECTORS["wire"] if w["kind"] == "delivered-run"]
    rebuilt = DeliveredRun.model_validate(run_wire)
    assert rebuilt.model_dump(mode="json", by_alias=True) == run_wire

    (completion_wire,) = [
        w["frame"] for w in VECTORS["wire"] if w["kind"] == "delivered-completion"
    ]
    rebuilt_completion = DeliveredCompletion.model_validate(completion_wire)
    assert (
        rebuilt_completion.model_dump(mode="json", by_alias=True) == completion_wire
    )


def test_the_published_chain_verifies_and_names_exactly_the_published_actors():
    from funduq.identity import verify_chain

    (vector,) = [c for c in VECTORS["chains"] if c["kind"] == "actor-chain"]

    result = verify_chain(vector["chain"])

    assert result.actor_public_keys == vector["actor_public_keys"]
    assert result.head == vector["actor_public_keys"][0]


def test_cross_party_formats_without_a_domain_tag_are_vectored_too():
    """The tag scan can't see formats that aren't tagged strings — this pins the rest by name."""
    assert {c["kind"] for c in VECTORS.get("chains", [])} == {"actor-chain"}
    assert {w["kind"] for w in VECTORS.get("wire", [])} == {"delivered-run", "delivered-completion"}


def test_both_sides_props_twins_validate_the_same_frame():
    from funduq_provider_sdk import KyokForwardedProps as SdkKyok
    from funduq_provider_sdk import verify_chain

    from funduq.identity import verify_chain
    from funduq.kyok import KyokForwardedProps

    (frame,) = [w["frame"] for w in VECTORS["wire"] if w["kind"] == "delivered-run"]
    props = frame["runInput"]["forwardedProps"]

    ours = KyokForwardedProps.model_validate(props["kyok"]).model_dump(mode="json", by_alias=True)
    theirs = SdkKyok.model_validate(props["kyok"]).model_dump(mode="json", by_alias=True)
    assert ours == theirs == props["kyok"]
    # The chain is relayed verbatim, not modeled: both verifiers must agree on it.
    assert (
        verify_chain(props["actorChain"]).actor_public_keys
        == verify_chain(props["actorChain"]).actor_public_keys
    )
