from __future__ import annotations

import ast
from pathlib import Path

import pytest

SDK_PACKAGE = Path(__file__).resolve().parent.parent / "funduq_provider_sdk"

# Core, and only core. `funduq_contract` is deliberately not here: the
# boundary this guards is dependency weight — a provider author must not
# install sqlalchemy, alembic and a database driver to sign a hop — and the
# contract package carries exactly what this SDK already carried. Sharing the
# bytes was never the danger; sharing core's belly was.
FORBIDDEN_ROOTS = {"funduq"}


def _sdk_modules() -> list[Path]:
    return sorted(SDK_PACKAGE.rglob("*.py"))


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize("module", _sdk_modules(), ids=lambda p: str(p.relative_to(SDK_PACKAGE)))
def test_sdk_module_does_not_import_funduq(module: Path) -> None:
    offenders = _imported_roots(module) & FORBIDDEN_ROOTS
    assert not offenders, (
        f"{module.name} imports {sorted(offenders)}. The SDK models a provider that "
        "runs in a different process with no access to funduq's code, and core drags a "
        "database stack behind it. It may share the wire contract — that is what "
        "funduq-contract is — but not core.\n\n"
        "This message used to say the two sides must each compute the bytes "
        "independently, because that duplication once caught a payload change 219 green "
        "tests had missed. That win was real and it is now historical: it happened six "
        "hours before docs/contract-vectors.json existed, and the frozen vectors catch "
        "that same class against a single shared implementation — checked by changing a "
        "domain tag in funduq-contract and watching the vector test go red."
    )


def test_funduq_is_not_installable_as_a_dependency() -> None:
    """Core must not be reachable through this package's dependency graph.

    Matching on the exact distribution name rather than the `funduq` prefix:
    `funduq-contract` is a legitimate dependency and shares the prefix, so a
    prefix test would forbid the very thing that made the duplication
    unnecessary.
    """
    import tomllib

    pyproject = tomllib.loads((SDK_PACKAGE.parent / "pyproject.toml").read_bytes().decode())
    declared = {
        requirement.split(">")[0].split("=")[0].split("[")[0].strip()
        for requirement in pyproject["project"].get("dependencies", [])
    }

    assert "funduq" not in declared, (
        "funduq-provider-sdk's dependencies include funduq, which puts core — and the "
        "database stack behind it — one import away from every provider. The two are "
        "contract-coupled, not code-coupled."
    )
