from __future__ import annotations

import ast
from pathlib import Path

import pytest

from funduq.config import CoreSettings
from funduq.core import Funduq

_CORE = Path(__file__).resolve().parent.parent / "funduq"

# alembic/env.py is the one exception and an honest one: it is a script the
# alembic CLI executes, the CLI has no other way to be told, and it already
# prefers `config.attributes` with the environment only as a fallback.
_ALLOWED = {"alembic/env.py"}


def test_no_core_module_reads_the_process_environment():
    """Reading `os.environ` is a process's act, and core is a library that does
    not own one. The same call must not produce a different object because of
    ambient state its caller never mentioned. No exceptions inside the
    library: `from_env` used to be the named escape hatch and is gone —
    configuration is an argument, and a deployment that keeps it in the
    environment reads the environment itself.

    Scanned rather than trusted to review: `CoreSettings` was a `BaseSettings`
    for a long time and nothing said so at the call site — `Funduq()` quietly
    configured itself from the environment, and no test noticed because every
    test happened to set the variables it wanted.
    """
    offenders = []
    for module in sorted(_CORE.rglob("*.py")):
        relative = module.relative_to(_CORE).as_posix()
        if relative in _ALLOWED or "__pycache__" in relative:
            continue
        source = module.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            reads_environ = (
                isinstance(node, ast.Attribute)
                and node.attr in {"environ", "getenv"}
                and isinstance(node.value, ast.Name)
                and node.value.id == "os"
            )
            if reads_environ:
                offenders.append(f"{relative}:{node.lineno}")

    assert not offenders, (
        f"core modules reading the environment: {offenders}. Configuration is an "
        "argument; a deployment that wants the environment reads it itself and "
        "constructs CoreSettings with the values."
    )


def test_settings_have_no_environment_reader():
    """`from_env` was the one named road from the environment into settings,
    and it was ruled out entirely: its existence made the environment a
    configuration surface, and a surface is read by whoever finds it."""
    assert not hasattr(CoreSettings, "from_env")


def test_settings_do_not_absorb_the_environment_on_construction(monkeypatch):
    monkeypatch.setenv("FUNDUQ_DATABASE_URL", "postgresql+psycopg://ambient/state")

    settings = CoreSettings(token_signing_secret="s", identity_private_key="a" * 64)

    assert "ambient" not in settings.database_url, (
        "constructing settings picked up an environment variable nobody passed"
    )


def test_funduq_cannot_be_built_without_being_told():
    """`Funduq()` used to mean "read the environment". Nothing at that call
    site said so, which is the whole objection."""
    with pytest.raises(TypeError):
        Funduq()


def test_the_brokers_waits_are_settings_and_reach_the_broker():
    """The three waits are embedder policy: told to `CoreSettings` like
    everything else, they must arrive on the broker `Funduq` builds."""
    settings = CoreSettings(
        token_signing_secret="s",
        identity_private_key="a" * 64,
        deliver_timeout_seconds=0.5,
        unserved_timeout_seconds=9,
        undelivered_window_seconds=60,
    )
    funduq = Funduq(settings)

    assert funduq.broker.deliver_timeout_seconds == 0.5
    assert funduq.broker.unserved_timeout_seconds == 9.0
    assert funduq.broker.undelivered_window_seconds == 60.0


def test_a_bare_broker_and_a_settings_built_one_agree_on_the_defaults():
    """One definition: `RunBroker()`'s keyword defaults are the same names
    `CoreSettings` carries, so nothing has to be kept in sync by hand."""
    from funduq.broker import RunBroker

    bare = RunBroker()
    fields = CoreSettings.model_fields
    assert bare.deliver_timeout_seconds == fields["deliver_timeout_seconds"].default
    assert bare.unserved_timeout_seconds == fields["unserved_timeout_seconds"].default
    assert bare.undelivered_window_seconds == fields["undelivered_window_seconds"].default
