"""What "the contract" is, as something a machine can compare.

An adopter's complaint, in their own words: 167 commits moved through the
handshake, dispatch, cancel authority and `RUN_FINISHED` semantics, the
commit subjects were good prose, and none of it was mappable to "does my
transport still work". The only method available was to read the whole diff
and re-derive the implications.

A version number alone would not fix that, because a version number rots
exactly like the prose did. What works is already in this repo, one layer
down: `EXPECTED_SCHEMA_REVISION` is a constant a human writes, the
migrations are the truth, and a test fails when they disagree. Nobody has
to remember to bump it — the suite refuses to go green until they do.

This is that shape, for the contract instead of the schema. `fingerprint()`
reads the surface an external implementation depends on and hashes it;
`docs/contract-vectors.json` records the revision and the fingerprint of
the surface at that revision; a test compares them and, when they differ,
says to bump the revision and write the changelog line. The line becomes a
condition of a green suite rather than a courtesy.

**What counts as the surface** is the judgement in this file, and it is
deliberately narrow: things an outside implementation would have to change
its own code to keep up with. Prose, internal helpers and private names are
not in it. That judgement has been wrong once and been corrected here rather
than apologised for: `funduq_contract`'s exported Python signatures were
outside it, so a parameter changing type shipped with a changelog entry
saying nothing had changed for anyone. Wire compatibility is not the whole
of the contract when one of the four distributions *is* the contract.

Everything here is read live from the code, never copied — a copy is another
thing to drift.

**It lives beside the tests rather than in the package**, for two reasons
that point the same way: it reads the provider SDK's port, which core is
forbidden to import (`test_core_is_sdk_free.py` caught the first draft of
this file), and it finds documents by repo layout, which does not survive
being installed as a wheel. Checking the contract is something this
repository does, not something funduq does at runtime.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any


CONTRACT_VECTORS = Path(__file__).resolve().parents[2] / "docs" / "contract-vectors.json"

CONTRACT_CHANGELOG = Path(__file__).resolve().parents[2] / "docs" / "contract-changelog.md"


def _settings_surface() -> list[str]:
    """Every `CoreSettings` field and whether a deployment must supply it.

    Requiredness is contract, not detail: `identity_private_key` losing its
    default is a change that stops an existing deployment from starting, and
    it is exactly the kind that arrived unannounced before.
    """
    from funduq.config import CoreSettings

    return sorted(
        f"{name}:{'required' if field.is_required() else 'optional'}"
        for name, field in CoreSettings.model_fields.items()
    )


def _link_surface() -> list[str]:
    """The verbs a provider link must implement.

    The names of the port itself. A transport is written against these, so a
    rename or an added abstract method is a change an implementer has to act
    on, whatever the docstrings around them say.
    """
    from funduq_provider_sdk.link import FunduqLink

    return sorted(
        name
        for name, member in inspect.getmembers(FunduqLink)
        if not name.startswith("_")
        and (inspect.isfunction(member) or isinstance(member, property))
    )


def _shapes_surface() -> list[str]:
    """Every crossing shape funduq-contract defines: name plus field aliases.

    In the surface because these ARE the wire: a renamed field or a dropped
    shape is a change every transport and every second implementation has to
    act on. Read live off the models, never copied.
    """
    import funduq_contract
    from funduq_contract import Shape

    out: list[str] = []
    for name in sorted(funduq_contract.__all__):
        member = getattr(funduq_contract, name)
        if not (isinstance(member, type) and issubclass(member, Shape)):
            continue
        if member is Shape:
            continue
        fields = sorted(
            field.alias or field_name
            for field_name, field in member.model_fields.items()
        )
        out.append(f"shape:{name}:{','.join(fields)}")
    return out


def _a2a_surface() -> list[str]:
    """The A2A protocol version funduq answers as, and the transport bindings
    it will accept. Both are read from `a2a-sdk` rather than written here, so
    a protocol bump moves this fingerprint by itself."""
    from funduq.protocols.a2a import _BINDINGS, PROTOCOL_VERSION

    return [f"protocol_version:{PROTOCOL_VERSION}", *sorted(f"binding:{b}" for b in _BINDINGS)]


def _typing_surface() -> list[str]:
    """Whether each distributed package still ships its PEP 561 marker.

    In the surface because losing one silently turns every annotation these
    packages export into `Any` on the other side of an install — a change to
    what an integrator can rely on, made by deleting an empty file.
    """
    root = Path(__file__).resolve().parents[2]
    packages = (
        root / "funduq-contract" / "funduq_contract",
        root / "funduq" / "funduq",
        root / "funduq-provider-sdk" / "funduq_provider_sdk",
    )
    return sorted(f"{p.name}:{'typed' if (p / 'py.typed').exists() else 'untyped'}" for p in packages)


def _contract_api_surface() -> list[str]:
    """Every public name `funduq_contract` exports, with the shape it exports it as.

    In the surface because of a break that landed without one. `sign_hop`'s
    third parameter went from `dict[str, str] | None` to `DispatchTarget |
    None` between 0.0.2 and 0.0.3 — no byte on the wire moved, so the vectors
    did not move, so the fingerprint did not move, and the changelog entry
    said "chains you were building are unaffected". True of the wire, false
    of anyone's code: the old call raised `AttributeError` from inside a
    function they never wrote.

    That gap was in the *definition* of the surface, not in someone's
    diligence. This package is the reference implementation every Python
    implementer builds against — its exported signatures are as much a thing
    they must change their own code to keep up with as a renamed A2A method
    is. Reading them live is the same trick used everywhere else here: a copy
    would drift, and drift is the thing being detected.

    Not extended to core or the provider SDK. Those are one implementation of
    a contract other languages may implement differently; this package *is*
    the contract, and the line is drawn where the changelog's own definition
    draws it.
    """
    import funduq_contract

    def shape(name: str) -> str:
        member = getattr(funduq_contract, name)
        if inspect.isclass(member):
            model_fields = getattr(member, "model_fields", None)
            if model_fields is not None:
                parts = [
                    f"{field_name}:{field.alias or field_name}"
                    for field_name, field in model_fields.items()
                ]
            else:
                fields = getattr(member, "__dataclass_fields__", {})
                parts = [f"{f.name}:{f.type}" for f in fields.values()]
            parts += sorted(
                f"{attr}()"
                for attr, value in vars(member).items()
                if not attr.startswith("_")
                and (inspect.isfunction(value) or isinstance(value, property))
            )
            return f"{name}(class):{','.join(parts)}"
        if inspect.isfunction(member):
            return f"{name}{inspect.signature(member)}"
        return f"{name}={member!r}"

    return sorted(shape(name) for name in funduq_contract.__all__)


def _without_prose(value: Any) -> Any:
    """Drops `note` and `comment` keys, at any depth.

    The vectors file explains itself as it goes, and those explanations are
    not contract: rewording one must not force a revision. This exists
    because the first version hashed them and a rename in the prose turned
    the suite red — the mechanism catching its own author is the argument
    for having it.
    """
    if isinstance(value, dict):
        return {k: _without_prose(v) for k, v in value.items() if k not in {"note", "comment"}}
    if isinstance(value, list):
        return [_without_prose(item) for item in value]
    return value


def _vectors_surface() -> Any:
    """The vectors file, minus its own `contract` block and minus prose.

    The block records the revision and the fingerprint, so hashing it would
    make the fingerprint depend on itself. What is left — every signing
    payload, every signature, every wire frame, the chain — is contract by
    construction: this file exists so an implementation in another language
    can replay it.
    """
    document = json.loads(CONTRACT_VECTORS.read_text())
    return _without_prose({key: value for key, value in document.items() if key != "contract"})


def _revision_surface() -> str:
    """The revision `funduq_contract` says it implements.

    In the surface so that cutting a revision cannot forget the constant: an
    installed package that claims the wrong one is worse than one that claims
    nothing, because it answers confidently.
    """
    from funduq_contract import CONTRACT_REVISION

    return f"contract_revision:{CONTRACT_REVISION}"


def surface() -> dict[str, Any]:
    """Everything an outside implementation depends on, gathered live."""
    return {
        "declared_revision": _revision_surface(),
        "contract_api": _contract_api_surface(),
        "vectors": _vectors_surface(),
        "settings": _settings_surface(),
        "link": _link_surface(),
        "shapes": _shapes_surface(),
        "a2a": _a2a_surface(),
        "typing": _typing_surface(),
    }


def fingerprint() -> str:
    """A stable hash of `surface()`.

    `sort_keys` and a compact separator so the digest depends on the surface
    and not on how anything was formatted; hashing a canonical form is what
    keeps a whitespace change out of the changelog.
    """
    canonical = json.dumps(surface(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def recorded() -> dict[str, Any]:
    """The revision and fingerprint `contract-vectors.json` claims."""
    return json.loads(CONTRACT_VECTORS.read_text())["contract"]
