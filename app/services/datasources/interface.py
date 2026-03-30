# app/services/datasources/interface.py
from abc import ABC, abstractmethod
from typing import Any


class DataSourceBackend(ABC):
    """Abstract base class for all data source backends."""

    @abstractmethod
    def fetch(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        """
        Fetch data from the source matching the given query.

        Returns a list of records as dicts.
        """
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """Return True if the data source is reachable."""
        ...
