DEFAULT_DB_SCHEMA = "public"

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./funduq.db"

EXPECTED_SCHEMA_REVISION = "e7b3a94c1f60"


def quoted_schema(db_schema: str) -> str:
    return f'"{db_schema}"'
