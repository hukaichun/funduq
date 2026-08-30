from __future__ import annotations

import argparse

from alembic import command
from alembic.config import Config


def migrate(database_url: str | None = None, db_schema: str | None = None) -> None:
    """Bring the database to the current schema head; a fresh database is created at head."""
    cfg = Config()
    cfg.set_main_option("script_location", "funduq:alembic")
    if database_url is not None:
        cfg.attributes["funduq_database_url"] = database_url
    if db_schema is not None:
        cfg.attributes["funduq_db_schema"] = db_schema
    command.upgrade(cfg, "head")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m funduq.migrate",
        description="Create or upgrade a funduq database to the current schema head.",
    )
    parser.add_argument(
        "database_url",
        nargs="?",
        default=None,
        help="SQLAlchemy URL; defaults to FUNDUQ_DATABASE_URL",
    )
    migrate(parser.parse_args().database_url)


if __name__ == "__main__":
    main()
