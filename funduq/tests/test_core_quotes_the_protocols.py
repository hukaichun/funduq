"""Core does not transcribe a protocol's vocabulary; it quotes the package that defines it.

The sibling of `test_core_is_network_free`. That one forbids a verb — our
code neither listens nor dials. This one forbids a *transcription*: an AG-UI
event type written out as a string literal instead of read off
`ag_ui.core.EventType`.

Both rules exist for the same measured reason. funduq hand-wrote A2A once and
was still answering `tasks/send` and emitting `{"type": "text"}` parts two
renames after the spec moved, with nothing failing until a real client got
-32601. A transcribed name cannot break at import; a quoted one can, and
that is the whole difference.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from ag_ui.core import EventType

FUNDUQ_PACKAGE = Path(__file__).resolve().parent.parent / "funduq"

EVENT_TYPE_NAMES = frozenset(member.value for member in EventType)


def _core_modules() -> list[Path]:
    return sorted(
        path for path in FUNDUQ_PACKAGE.rglob("*.py") if not path.name.startswith("__")
    )


def _docstrings(tree: ast.AST) -> set[int]:
    """The ids of string constants that are docstrings — prose, not vocabulary."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


@pytest.mark.parametrize(
    "module", _core_modules(), ids=lambda p: str(p.relative_to(FUNDUQ_PACKAGE))
)
def test_no_core_module_transcribes_an_ag_ui_event_type(module: Path) -> None:
    tree = ast.parse(module.read_text())
    prose = _docstrings(tree)
    offenders = sorted(
        {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in EVENT_TYPE_NAMES
            and id(node) not in prose
        }
    )
    assert not offenders, (
        f"{module.name} writes {offenders} out as string literals. Read the name off "
        "`ag_ui.core.EventType` instead — a transcribed name goes stale in silence, a "
        "quoted one fails at import when the package moves. Prose in a docstring is fine; "
        "this is about names the code compares or emits."
    )
