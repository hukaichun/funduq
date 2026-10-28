DEFAULT_DB_SCHEMA = "public"

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./funduq.db"

EXPECTED_SCHEMA_REVISION = "c8e1f3a6b902"


def quoted_schema(db_schema: str) -> str:
    return f'"{db_schema}"'
