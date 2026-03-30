# app/services/datasources/backends/postgres.py
from typing import Any
from app.services.datasources.interface import DataSourceBackend


class PostgresBackend(DataSourceBackend):
    """
    Read-only PostgreSQL data source backend.

    Config keys:
        url (str): PostgreSQL connection URL
        table (str): Table or view name to query
        limit (int, optional): Max rows to return (default 100)
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._url = config["url"]
        self._table = config["table"]
        self._limit = int(config.get("limit", 100))

    def fetch(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        """
        Execute a simple ILIKE search on all text columns.

        Falls back to full table scan if query is empty.
        """
        import sqlalchemy as sa

        engine = sa.create_engine(self._url)
        limit = int(kwargs.get("limit", self._limit))
        with engine.connect() as conn:
            if query:
                sql = sa.text(
                    f"SELECT * FROM {self._table} "  # noqa: S608
                    f"WHERE CAST(ROW({self._table}.*) AS TEXT) ILIKE :q "
                    f"LIMIT :lim"
                )
                rows = conn.execute(sql, {"q": f"%{query}%", "lim": limit})
            else:
                sql = sa.text(f"SELECT * FROM {self._table} LIMIT :lim")  # noqa: S608
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
