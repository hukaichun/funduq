from __future__ import annotations

from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]

_DISTRIBUTED_PACKAGES = [
    _REPO / "funduq" / "funduq",
    _REPO / "funduq-provider-sdk" / "funduq_provider_sdk",
    _REPO / "funduq-llm-provider-sdk" / "funduq_llm_provider_sdk",
]


@pytest.mark.parametrize("package", _DISTRIBUTED_PACKAGES, ids=lambda p: p.name)
def test_every_distributed_package_ships_its_types(package: Path) -> None:
    """Without a PEP 561 marker, an integrator's type checker treats every one
    of these modules as untyped: `ProviderIdentity.public_key` reveals as
    `Any`, `verify_chain`'s result reveals as `Any`, and a wrong call is
    silent. The annotations are all written already — the marker is the only
    thing standing between them and the people the SDKs exist for.

    An empty file is easy to lose in a move or a rename and nothing else would
    notice, which is what this test is for. It does not prove the file reaches
    a wheel; `hatchling` includes everything under the package directory, and
    the built wheels were checked by hand when the markers landed.
    """
    assert (package / "__init__.py").exists(), f"{package} is not a package"
    assert (package / "py.typed").exists(), (
        f"{package.name} has no py.typed, so downstream type checkers see Any "
        "for everything it exports"
    )
