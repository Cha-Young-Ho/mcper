# app/services/datasources/registry.py
import os
from typing import Any
from app.services.datasources.interface import DataSourceBackend

_registry: dict[str, DataSourceBackend] = {}


def register(name: str, backend: DataSourceBackend) -> None:
    """Register a named data source backend."""
    _registry[name] = backend


def get(name: str) -> DataSourceBackend:
    """Retrieve a registered backend by name. Raises KeyError if not found."""
    if name not in _registry:
        raise KeyError(f"DataSource '{name}' is not registered.")
    return _registry[name]


def list_sources() -> list[str]:
    """Return all registered data source names."""
    return list(_registry.keys())


def setup_from_config(datasources_config: list[dict[str, Any]]) -> None:
    """
    Initialize backends from config list.

    Each config entry must have 'name' and 'type' keys.
    Supported types: 'postgres', 'sheets', 'notion'
    """
    from app.services.datasources.backends.postgres import PostgresBackend

    type_map = {
        "postgres": PostgresBackend,
    }

    for ds in datasources_config:
        name = ds["name"]
        ds_type = ds["type"]
        cls = type_map.get(ds_type)
        if cls is None:
            import logging
            logging.getLogger("mcper.datasources").warning(
                "Unknown datasource type '%s' for '%s', skipping.", ds_type, name
            )
            continue
        register(name, cls(ds))
