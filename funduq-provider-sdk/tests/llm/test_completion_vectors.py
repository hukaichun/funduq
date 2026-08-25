from __future__ import annotations

import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from funduq_provider_sdk.llm import ProviderIdentity

VECTORS = json.loads((Path(__file__).resolve().parents[3] / "docs" / "contract-vectors.json").read_text())


def test_this_side_publishes_no_payload_of_its_own_any_more():
    """An LLM provider's roster acts used to be two signed families of their
    own. They are operations on its open link now — the link proved the key,
    and re-proving it per operation is what those families were doing — so
    there is nothing left here to reproduce a vector for. Registration and
    deletion are exercised through funduq itself, in the core suite."""
    import funduq_provider_sdk.llm as sdk

    assert not [name for name in dir(sdk) if name.endswith("_payload")]


def test_the_delivered_completion_frame_round_trips_through_the_declared_model():
    from funduq_provider_sdk.llm import DeliveredCompletion

    (frame,) = [w["frame"] for w in VECTORS["wire"] if w["kind"] == "delivered-completion"]

    model = DeliveredCompletion.model_validate(frame)

    assert model.provider_key == frame["providerKey"]
    assert model.model_dump(mode="json", by_alias=True) == frame
