from __future__ import annotations

from pydantic import BaseModel

from funduq.db_schema import DEFAULT_DATABASE_URL, DEFAULT_DB_SCHEMA

# How long a run may sit queued with nobody serving its agent; how long a
# provider gets to answer an offer; how long a claimed run may go without
# its provider reporting anything.
UNSERVED_TIMEOUT_SECONDS = 45.0
DELIVER_TIMEOUT_SECONDS = 5.0
UNDELIVERED_WINDOW_SECONDS = 1800.0


class CoreSettings(BaseModel):
    """Everything core needs to be told, and it must be told rather than find out.

    Told explicitly: there is no environment reader here. A deployment that
    keeps configuration in the environment reads it itself and constructs
    this object with the values — configuration is an argument, never
    ambient state.
    """


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
