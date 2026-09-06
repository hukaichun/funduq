DEFAULT_DB_SCHEMA = "public"

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./funduq.db"

EXPECTED_SCHEMA_REVISION = "a1f4c9d27e3b"


def quoted_schema(db_schema: str) -> str:
    return f'"{db_schema}"'
