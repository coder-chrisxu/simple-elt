from abc import ABC, abstractmethod
from typing import Any, Iterator


class BaseAdapter(ABC):
    """Abstract interface for database adapters."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._connection = None

    @abstractmethod
    def connect(self) -> None:
        """Establish a database connection."""

    @abstractmethod
    def close(self) -> None:
        """Close the database connection."""

    @abstractmethod
    def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        """Execute a single SQL statement (DDL, DML, or PL/SQL call)."""

    @abstractmethod
    def fetch_one(self, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Execute a query and return a single row as a dict, or None."""

    @abstractmethod
    def fetch_all(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a query and return all rows as a list of dicts."""

    @abstractmethod
    def fetch_batches(
        self, sql: str, params: dict[str, Any] | None = None, batch_size: int = 5000
    ) -> Iterator[list[dict[str, Any]]]:
        """Execute a query and yield rows in batches."""

    @abstractmethod
    def commit(self) -> None:
        """Commit the current transaction."""

    @abstractmethod
    def rollback(self) -> None:
        """Rollback the current transaction."""

    @abstractmethod
    def insert_batch(self, table: str, rows: list[dict[str, Any]], commit: bool = True) -> int:
        """Insert a batch of rows into a table. Returns the number of rows inserted."""

    @abstractmethod
    def get_columns(self, table: str) -> list[str]:
        """Return column names for a table in insertion order."""

    @property
    def connection(self):
        if self._connection is None:
            raise RuntimeError("Not connected. Call connect() first.")
        return self._connection
