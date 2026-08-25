from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]

_DISTRIBUTIONS = ["funduq-contract", "funduq", "funduq-provider-sdk"]


def _project(distribution: str) -> dict:
    return tomllib.loads((_REPO / distribution / "pyproject.toml").read_bytes().decode())["project"]


@pytest.mark.parametrize("distribution", _DISTRIBUTIONS)
def test_the_declaration_carries_what_a_stranger_needs(distribution):
    """What a wheel must carry for the thing on PyPI to be usable by someone
    who did not write it.

    Every field here was missing at once, and none of them failed any other
    test: a suite that imports from the source tree never asks what a wheel
    would contain. Without a license PyPI shows "UNKNOWN", which for an
    enterprise adopter is where evaluation stops; without a readme the project
    page is blank; without urls there is nowhere to go — and `Changelog` in
    particular is how a reader tells whether anything they depend on moved.
    """
    project = _project(distribution)

    assert project.get("license"), f"{distribution} declares no license"
    assert project.get("readme"), f"{distribution} declares no readme"
    assert project.get("urls", {}).get("Changelog"), f"{distribution} links no changelog"
    assert project.get("classifiers"), f"{distribution} declares no classifiers"


@pytest.mark.parametrize("distribution", _DISTRIBUTIONS)
def test_every_file_the_declaration_names_exists(distribution):
    """A named file that is not there fails the *build*, which no other test
    performs — core declared a README it did not have, and the LICENSE that
    `license-files` named lived only at the repo root.

    Checked here rather than by building because building needs a network and
    a test that fails for want of one is a test that fails for the wrong
    reason. CI builds all three for real; this catches the same mistakes in a
    second, offline.
    """
    root = _REPO / distribution
    project = _project(distribution)

    assert (root / project["readme"]).exists(), (
        f"{distribution} declares readme {project['readme']!r}, which does not exist"
    )
    for pattern in project.get("license-files", []):
        assert list(root.glob(pattern)), (
            f"{distribution} declares license-files {pattern!r}, which matches nothing — "
            "a file at the repo root is not inside the distribution"
        )


@pytest.mark.parametrize("distribution", _DISTRIBUTIONS)
def test_no_table_was_swallowed_by_project_urls(distribution):
    """`[project.urls]` written above `dependencies` takes every table after it
    into itself, and TOML is happy about that — the build backend is what
    objects, with a message about a URL that is not a string.

    Asserting the shape rather than the position, so moving the table for a
    good reason does not fail and moving it for a bad one does.
    """
    for name, value in _project(distribution).get("urls", {}).items():
        assert isinstance(value, str), (
            f"{distribution}'s [project.urls] contains a table named {name!r} — it was "
            "written above another section and absorbed it"
        )


@pytest.mark.parametrize("distribution", ["funduq", "funduq-provider-sdk"])
def test_a_dependency_on_our_own_package_is_bounded(distribution):
    """An unbounded `funduq-contract` would let a future incompatible release
    install itself under an old dependant.

    It matters more here than any third-party pin: `funduq-contract` is the
    one distribution both sides depend on, so every version skew this project
    can have runs through it.
    """
    ours = [
        requirement
        for requirement in _project(distribution)["dependencies"]
        if requirement.startswith("funduq")
    ]

    assert ours, f"{distribution} declares no dependency on our own packages"
    for requirement in ours:
        assert any(op in requirement for op in (">=", "==", "~=")), (
            f"{distribution} depends on `{requirement}` with no lower bound"
        )
        assert "<" in requirement, (
            f"{distribution} depends on `{requirement}` with no upper bound — while these "
            "move together, an unbounded range is a promise nobody made"
        )
