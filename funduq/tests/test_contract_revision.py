from __future__ import annotations

import re

from . import contract_surface as contract


def test_the_recorded_fingerprint_matches_the_surface() -> None:
    """The whole mechanism, in one assert.

    An adopter's complaint was that 167 commits of good prose were
    unmappable to "does my transport still work", and that the only method
    available was to read the entire diff. A version field alone would not
    have helped: it rots the same way the prose did. What works is one layer
    down in this repo already — `EXPECTED_SCHEMA_REVISION` is written by
    hand, the migrations are the truth, and a test refuses to go green while
    they disagree.

    So this one fails whenever the contract surface moves without the
    revision moving with it, which makes writing the changelog line a
    condition of a green suite rather than a courtesy.
    """
    recorded = contract.recorded()
    computed = contract.fingerprint()

    assert recorded["fingerprint"] == computed, (
        "the contract surface changed but its revision did not.\n\n"
        f"  recorded: {recorded['fingerprint']} (revision {recorded['revision']})\n"
        f"  computed: {computed}\n\n"
        "If that change is intended: bump `contract.revision` in "
        "docs/contract-vectors.json, set `contract.fingerprint` to the computed "
        "value above, and add an entry to docs/contract-changelog.md saying what "
        "an outside implementation has to do about it. If it is not intended, the "
        "surface moved by accident — which is the case this exists to catch.\n\n"
        "What counts as the surface, and why, is in funduq/tests/contract_surface.py."
    )


def test_the_installed_constant_says_the_recorded_revision() -> None:
    """The one number an installed package can answer with, and the one the
    vectors record, have to be the same number.

    Nothing checked this, and they drifted the moment the constant was
    introduced: the changelog entry that added `CONTRACT_REVISION` cut
    revision 4 and left the constant at 3. The fingerprint test does not
    catch it — the constant's *value* is part of the surface, so changing it
    moves the fingerprint and forces a bump, but nothing required the bump to
    land on the same number. So a stranger asking an installed package which
    revision it implements got an answer one behind the vectors it was
    written against, which is the exact question the constant exists to
    answer.
    """
    from funduq_contract import CONTRACT_REVISION

    assert CONTRACT_REVISION == contract.recorded()["revision"], (
        f"funduq_contract.CONTRACT_REVISION is {CONTRACT_REVISION}, but "
        f"docs/contract-vectors.json records revision {contract.recorded()['revision']}. "
        "Cutting a revision means moving both."
    )


def test_the_changelog_has_an_entry_for_the_current_revision() -> None:
    """A bumped number with no sentence under it is the same silence in a new
    place. The fingerprint test forces the bump; this one forces the line."""
    revision = contract.recorded()["revision"]
    changelog = contract.CONTRACT_CHANGELOG.read_text()

    assert re.search(rf"^## Revision {revision}\b", changelog, re.M), (
        f"contract revision {revision} has no entry in docs/contract-changelog.md. "
        "A revision nobody described tells a reader as little as no revision at all."
    )


def test_the_surface_holds_the_things_an_implementation_is_written_against() -> None:
    """A fingerprint over the wrong things fails for the wrong reasons and
    passes for the wrong ones. These are the parts that must be in it, named
    so that dropping one is a deliberate act rather than an edit nobody
    reads."""
    surface = contract.surface()

    assert surface["vectors"], "the signing payloads and wire frames themselves"
    assert "identity_private_key:required" in surface["settings"], (
        "settings and their requiredness — this one stops an existing deployment "
        "from starting, and arrived unannounced once already"
    )
    assert "report_event" in surface["link"], "the provider port's verbs"
    assert any(item.startswith("protocol_version:") for item in surface["a2a"]), (
        "the A2A version, read from the SDK so a protocol bump moves the fingerprint "
        "on its own"
    )
    assert "funduq_provider_sdk:typed" in surface["typing"], (
        "the PEP 561 markers — losing one turns every exported annotation into Any "
        "downstream, by deleting an empty file"
    )


def test_the_fingerprint_ignores_formatting_but_not_content() -> None:
    """It hashes a canonical form, so reindenting the vectors file is not a
    contract change — and changing a single signing payload is."""
    import json

    original = contract.CONTRACT_VECTORS.read_text()
    document = json.loads(original)
    try:
        contract.CONTRACT_VECTORS.write_text(json.dumps(document, indent=8) + "\n")
        assert contract.fingerprint() == contract.recorded()["fingerprint"], (
            "reformatting moved the fingerprint"
        )

        document["vectors"][0]["payload_utf8"] += "-tampered"
        contract.CONTRACT_VECTORS.write_text(json.dumps(document, indent=2) + "\n")
        assert contract.fingerprint() != contract.recorded()["fingerprint"], (
            "a changed signing payload did not move the fingerprint"
        )
    finally:
        contract.CONTRACT_VECTORS.write_text(original)
