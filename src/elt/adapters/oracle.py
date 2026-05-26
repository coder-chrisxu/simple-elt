import oracledb
from typing import Any, Iterator

from .base import BaseAdapter


class OracleAdapter(BaseAdapter):

    def connect(self) -> None:
        self._connection = oracledb.connect(
            user=self.config["username"],
            password=self.config["password"],
            host=self.config["host"],
            port=self.config.get("port", 1521),
            service_name=self.config["service_name"],
        )
        self._connection.autocommit = False

    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            finally:
                self._connection = None

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, params or {})
            self.connection.commit()
        finally:
            cursor.close()

    def fetch_one(self, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, params or {})
            columns = [col[0].lower() for col in cursor.description]
            row = cursor.fetchone()
            if row is None:
                return None
            return dict(zip(columns, row))
        finally:
            cursor.close()

    def fetch_all(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, params or {})
            columns = [col[0].lower() for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def fetch_batches(
        self, sql: str, params: dict[str, Any] | None = None, batch_size: int = 5000
    ) -> Iterator[list[dict[str, Any]]]:
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, params or {})
            columns = [col[0].lower() for col in cursor.description]
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break
                yield [dict(zip(columns, row)) for row in rows]
        finally:
            cursor.close()

    def commit(self) -> None:
        if self._connection is not None:
            self._connection.commit()

    def rollback(self) -> None:
        if self._connection is not None:
            self._connection.rollback()

    def insert_batch(self, table: str, rows: list[dict[str, Any]], commit: bool = True) -> int:
        if not rows:
            return 0
        columns = list(rows[0].keys())
        placeholders = ", ".join(f":{c}" for c in columns)
        col_list = ", ".join(columns)
        sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
        cursor = self.connection.cursor()
        try:
            data = [{c: row[c] for c in columns} for row in rows]
            cursor.executemany(sql, data)
            if commit:
                self.connection.commit()
            return cursor.rowcount
        finally:
            cursor.close()

    def get_columns(self, table: str) -> list[str]:
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "SELECT column_name FROM all_tab_columns "
                "WHERE owner = UPPER(:owner) AND table_name = UPPER(:table_name) "
                "ORDER BY column_id",
                {"owner": self.config.get("username", "").upper(), "table_name": table.upper()},
            )
            return [row[0].lower() for row in cursor.fetchall()]
        finally:
            cursor.close()
