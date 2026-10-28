DEFAULT_DB_SCHEMA = "public"

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./funduq.db"

EXPECTED_SCHEMA_REVISION = "b5d2e8f0a7c4"


def quoted_schema(db_schema: str) -> str:
    return f'"{db_schema}"'
