from __future__ import annotations

import os

from pydantic import BaseModel

from funduq.db_schema import DEFAULT_DATABASE_URL, DEFAULT_DB_SCHEMA

# How long a run may sit queued with nobody serving its agent; how long a
# provider gets to answer an offer; how long a claimed run may go without
# its provider reporting anything.
UNSERVED_TIMEOUT_SECONDS = 45.0
DELIVER_TIMEOUT_SECONDS = 5.0
UNDELIVERED_WINDOW_SECONDS = 1800.0


ENV_PREFIX = "FUNDUQ_"


class CoreSettings(BaseModel):
    """Everything core needs to be told, and it must be told rather than find out."""


    database_url: str = DEFAULT_DATABASE_URL
    db_schema: str = DEFAULT_DB_SCHEMA


    stale_hidden_window_seconds: int = 60 * 60 * 24 * 7

    thread_queue_limit: int | None = 8

    # How much abnormality a provider is allowed before funduq stops serving it: when any one of its quality counters (misdeclared, abandoned, undelivered, unanswered, answered_late) reaches this figure, the provider is withdrawn from service — uniformly, whatever the event type — and re-registration is the way back, record intact.
    provider_quality_tolerance: int | None = 3

    # The broker's three waits — embedder policy, the way quality tolerance
    # is. Defined here once; RunBroker's own keyword defaults are these same
    # names, so a broker built bare and one built by Funduq agree.
    unserved_timeout_seconds: float = UNSERVED_TIMEOUT_SECONDS
    deliver_timeout_seconds: float = DELIVER_TIMEOUT_SECONDS
    undelivered_window_seconds: float = UNDELIVERED_WINDOW_SECONDS


    token_signing_secret: str

    # Required, and deliberately without a default.
    identity_private_key: str

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "CoreSettings":
        """Builds settings from `FUNDUQ_`-prefixed environment variables."""
        source = os.environ if environ is None else environ
        values = {
            name: source[key]
            for name in cls.model_fields
            if (key := ENV_PREFIX + name.upper()) in source and source[key] != ""
        }
        return cls.model_validate(values)
