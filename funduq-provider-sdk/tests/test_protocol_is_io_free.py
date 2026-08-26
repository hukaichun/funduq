from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROTOCOL = Path(__file__).resolve().parent.parent / "funduq_provider_sdk" / "protocol"

# Sans-io means no I/O and no clock — not no types. What is forbidden here is
# the machine reaching for a socket, an event loop, or the time, because each
# of those is what makes an ordering untestable: a race against a real clock
# has to be provoked with a sleep, and a race behind a socket cannot be
# provoked at all. Time enters these modules as a `now` argument and leaves as
# `next_deadline()`; that is the whole mechanism, and this test is what keeps
# it true.
FORBIDDEN = {
    "asyncio",
    "socket",
    "ssl",
    "select",
    "selectors",
    "threading",
    "multiprocessing",
    "subprocess",
    "time",
    "datetime",
    "http",
    "urllib",
    "httpx",
    "websockets",
    "aiohttp",
    "requests",
    "grpc",
}


def _modules() -> list[Path]:
    return sorted(PROTOCOL.rglob("*.py"))


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize("module", _modules(), ids=lambda p: p.name)
def test_protocol_module_performs_no_io_and_reads_no_clock(module: Path) -> None:
    offenders = _imported_roots(module) & FORBIDDEN
    assert not offenders, (
        f"{module.name} imports {sorted(offenders)}. The protocol machines consume "
        "frames and emit frames; a driver owns the socket, the event loop and the "
        "clock. Whatever needs one of those belongs in the driver, not here — the "
        "moment a machine reads the time, its own timeout can only be tested by "
        "waiting for it."
    )


def test_the_machines_are_reachable_without_an_event_loop() -> None:
    """Importing and driving both machines must not need asyncio running.

    The static check above is about our own verbs; this is the behavioural
    half. A machine that quietly needed a loop would still pass the import
    test and would still be untestable as an ordered script.
    """
    from funduq_provider_sdk.protocol import FunduqSide

    machine = FunduqSide(deliver_timeout=5.0)
    assert machine.next_deadline() is None
