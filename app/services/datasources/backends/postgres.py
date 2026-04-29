# app/services/datasources/backends/postgres.py
import re
from typing import Any

from app.services.datasources.interface import DataSourceBackend

# Whitelist for PostgreSQL identifiers (table names). Optionally allows a
# `schema.table` form. Each segment must be a valid unquoted identifier.
_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _validate_table_identifier(raw: str) -> str:
    """
    Validate a PostgreSQL table identifier against a strict whitelist.

    Accepts `table` or `schema.table`. Each segment must match
    ``^[a-zA-Z_][a-zA-Z0-9_]*$``. Returns a safely-quoted identifier suitable
    for embedding in a SQL statement (each segment wrapped in double quotes).
    """
    if not isinstance(raw, str) or not raw:
        raise ValueError("Postgres backend 'table' config must be a non-empty string")
    segments = raw.split(".")
    if len(segments) not in (1, 2):
        raise ValueError(
            f"Invalid table identifier '{raw}': expected 'table' or 'schema.table'"
        )
    for seg in segments:
        if not _IDENT_RE.match(seg):
            raise ValueError(
                f"Invalid table identifier segment '{seg}': must match "
                f"^[a-zA-Z_][a-zA-Z0-9_]*$"
            )
    # Quote each segment defensively even though the whitelist already
    # prohibits special characters. Doubles any embedded quotes for safety.
    return ".".join(f'"{seg.replace(chr(34), chr(34) * 2)}"' for seg in segments)


class PostgresBackend(DataSourceBackend):
    """
    Read-only PostgreSQL data source backend.

    Config keys:
        url (str): PostgreSQL connection URL
        table (str): Table or view name to query (validated against whitelist)
        limit (int, optional): Max rows to return (default 100)
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._url = config["url"]
        # Validate and pre-quote the identifier at construction time so we
        # fail fast on misconfiguration and never interpolate raw input into
        # SQL at query time.
        self._table_raw = config["table"]
        self._table_sql = _validate_table_identifier(self._table_raw)
        self._limit = int(config.get("limit", 100))

    def fetch(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        """
        Execute a simple ILIKE search on all text columns.

        Falls back to full table scan if query is empty.
        """
        import sqlalchemy as sa

        engine = sa.create_engine(self._url)
        limit = int(kwargs.get("limit", self._limit))
        # self._table_sql is validated + quoted; not derived from user input.
        table = self._table_sql
        with engine.connect() as conn:
            if query:
                sql = sa.text(
                    f"SELECT * FROM {table} "  # noqa: S608
                    f"WHERE CAST(ROW({table}.*) AS TEXT) ILIKE :q "
                    f"LIMIT :lim"
                )
                rows = conn.execute(sql, {"q": f"%{query}%", "lim": limit})
            else:
                sql = sa.text(f"SELECT * FROM {table} LIMIT :lim")  # noqa: S608
                rows = conn.execute(sql, {"lim": limit})
            keys = list(rows.keys())
            return [dict(zip(keys, row)) for row in rows]

    def health_check(self) -> bool:
        import sqlalchemy as sa
        try:
            engine = sa.create_engine(self._url)
            with engine.connect() as conn:
                conn.execute(sa.text("SELECT 1"))
            return True
        except Exception:
            return False
