from pydantic_settings import BaseSettings, SettingsConfigDict

from funduq.db_schema import DEFAULT_DATABASE_URL, DEFAULT_DB_SCHEMA


class CoreSettings(BaseSettings):

    model_config = SettingsConfigDict(env_prefix="FUNDUQ_")


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

    identity_private_key: str | None = None

