from __future__ import annotations

import os

from pydantic import BaseModel

from funduq.db_schema import DEFAULT_DATABASE_URL, DEFAULT_DB_SCHEMA


ENV_PREFIX = "FUNDUQ_"


class CoreSettings(BaseModel):
    """Everything core needs to be told, and it must be told rather than find out.

    This used to be a `BaseSettings`, which reads the process environment on
    every construction. That is invisible coupling of the worst kind: the same
    call produces a different object depending on ambient state nothing in the
    caller mentions, two instances in one process cannot be configured
    differently without mutating `os.environ`, and a test passes or fails on
    what ran before it.

    It is also the same rule core already lives by elsewhere. Core implements
    no transport, cannot verify liveness, and does not authenticate anyone —
    each because the thing in question needs something core does not have.
    Reading the environment is that shape too: the environment belongs to a
    *process*, and core is a library that does not own one.

    So configuration arrives as an argument. `from_env` is still here, because
    reading the environment is a perfectly good thing for a deployment to do —
    it is just an act with a name now, performed by whoever owns the process.
    """


    database_url: str = DEFAULT_DATABASE_URL
    db_schema: str = DEFAULT_DB_SCHEMA


    stale_hidden_window_seconds: int = 60 * 60 * 24 * 7

    thread_queue_limit: int | None = 8

    # How much abnormality a provider is allowed before funduq stops serving
    # it: when any one of its quality counters (misdeclared, abandoned,
    # undelivered, unanswered, answered_late) reaches this figure, the provider is
    # withdrawn from service — uniformly, whatever the event type — and
    # re-registration is the way back, record intact. None disables the
    # judgment (counters still count). Policy, so it is a setting.
    provider_quality_tolerance: int | None = 3


    token_signing_secret: str

    # Required, and deliberately without a default. funduq is an identity like
    # any other — providers pin it, and it signs a hop on every dispatch — so a
    # funduq without one is not a lighter deployment, it is one whose signature
    # nobody can check. A protection that depends on someone remembering an
    # optional setting is not a protection, and generating a key per process
    # would be worse still: the key would change on every restart and every
    # provider's pin would break.
    identity_private_key: str

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "CoreSettings":
        """Builds settings from `FUNDUQ_`-prefixed environment variables.

        For whoever owns the process — a server's entry point, a CLI, a test
        harness — and never for a library reaching behind its caller's back.
        `environ` is injectable so that reading it is testable without a
        process to mutate.

        A variable set to the empty string is treated as unset, which is what
        an unset-but-declared variable looks like in a shell or a compose
        file. Everything else is handed to pydantic, so a bad value fails with
        the same message a bad argument would.
        """
        source = os.environ if environ is None else environ
        values = {
            name: source[key]
            for name in cls.model_fields
            if (key := ENV_PREFIX + name.upper()) in source and source[key] != ""
        }
        return cls.model_validate(values)
