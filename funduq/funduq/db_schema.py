DEFAULT_DB_SCHEMA = "public"

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./funduq.db"

EXPECTED_SCHEMA_REVISION = "c4d9e17b52aa"


def quoted_schema(db_schema: str) -> str:
    return f'"{db_schema}"'
