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

    # Required, and deliberately without a default. funduq is an identity like
    # any other — providers pin it, and it signs a hop on every dispatch — so a
    # funduq without one is not a lighter deployment, it is one whose signature
    # nobody can check. A protection that depends on someone remembering an
    # optional setting is not a protection, and generating a key per process
    # would be worse still: the key would change on every restart and every
    # provider's pin would break.
    identity_private_key: str

