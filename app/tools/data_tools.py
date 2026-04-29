# app/tools/data_tools.py
"""MCP tools for querying registered data sources."""

from app.db.database import SessionLocal
from app.tools._auth_check import check_read


def register_data_tools(mcp) -> None:
    @mcp.tool()
    def get_data(source: str, query: str = "", limit: int = 50) -> dict:
        """
        Query a registered data source by name.

        Args:
            source: Name of the registered data source (see list_data_sources).
            query: Search string (ILIKE on all text columns for SQL backends).
            limit: Maximum number of records to return (default 50).

        Returns:
            dict with 'records' list and 'count'.
        """
        from app.services.datasources.registry import get
        # Hold the session open across the authz check AND the data fetch so
        # that no TOCTOU window exists between "may this caller read?" and
        # the actual query. (Audit S05)
        with SessionLocal() as db:
            denied = check_read(db)
            if denied:
                return {"error": denied}
            try:
                backend = get(source)
                records = backend.fetch(query, limit=limit)
                return {
                    "source": source,
                    "count": len(records),
                    "records": records,
                }
            except KeyError:
                return {
                    "error": f"Data source '{source}' not found.",
                    "available": [],
                }

    @mcp.tool()
    def list_data_sources() -> dict:
        """
        List all registered data source names.

        Returns:
            dict with 'sources' list.
        """
        from app.services.datasources.registry import list_sources
        with SessionLocal() as db:
            denied = check_read(db)
            if denied:
                return {"error": denied}
        return {"sources": list_sources()}
