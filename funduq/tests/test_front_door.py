"""The front door is a promise, so it is walked rather than trusted."""

from __future__ import annotations

import subprocess
import sys

import funduq


def test_every_advertised_name_resolves():
    """`__all__` and `_FRONT_DOOR` are hand-written, and a name in a hand-written
    list is a name that can be wrong. Import each one."""
    for name in funduq.__all__:
        assert getattr(funduq, name) is not None, name


def test_the_front_door_lists_exactly_what_it_can_serve():
    assert set(funduq.__all__) == {"migrate", *funduq._FRONT_DOOR}
    assert funduq.__dir__() == sorted(funduq.__all__)


def test_an_unknown_name_is_an_attribute_error_not_an_import_error():
    """A typo should read as a typo. `__getattr__` that tried to import first
    would report whatever the import said instead."""
    try:
        funduq.NoSuchThing
    except AttributeError as e:
        assert "NoSuchThing" in str(e)
    else:
        raise AssertionError("expected AttributeError")


def test_importing_funduq_does_not_drag_the_doors_in():
    """The reason the names are lazy: `python -m funduq.migrate` is a
    deployment's first command, and it should not pay for the A2A stack to run
    a migration. Measured at roughly 0.2s against 1.2s when the doors come too,
    which is worth one `__getattr__`.
    """
    probe = (
        "import sys, funduq; "
        "print(any(m.startswith('a2a') or m.startswith('google.protobuf') "
        "for m in sys.modules))"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "False", (
        "importing funduq pulled the A2A stack in — a name in _FRONT_DOOR was "
        "imported eagerly, or something else in the package now imports a door"
    )
