# app/services/datasources/registry.py
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
