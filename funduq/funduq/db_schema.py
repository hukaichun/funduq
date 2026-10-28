DEFAULT_DB_SCHEMA = "public"

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./funduq.db"

EXPECTED_SCHEMA_REVISION = "d4a7c2e9f150"


def quoted_schema(db_schema: str) -> str:
    return f'"{db_schema}"'
