from datetime import datetime, timezone
from typing import Any

from elt.connections import ConnectionManager

_CREATE_TABLE_SQL = """\
CREATE TABLE elt_audit (
    run_id        NUMBER GENERATED ALWAYS AS IDENTITY,
    job_name      VARCHAR2(200) NOT NULL,
    step_name     VARCHAR2(200),
    status        VARCHAR2(20) NOT NULL,
    rows_affected NUMBER,
    started_at    TIMESTAMP NOT NULL,
    finished_at   TIMESTAMP,
    error_message VARCHAR2(4000),
    attempt       NUMBER
)
"""

_ADD_ATTEMPT_COLUMN_SQL = """\
ALTER TABLE elt_audit ADD attempt NUMBER
"""

_INSERT_SQL = """\
INSERT INTO elt_audit (job_name, step_name, status, rows_affected, started_at, finished_at, error_message, attempt)
VALUES (:job_name, :step_name, :status, :rows_affected, :started_at, :finished_at, :error_message, :attempt)
"""


class AuditLogger:
    """Records job execution outcomes to the elt_audit table."""

    def __init__(self, connection_manager: ConnectionManager, connection_name: str):
        self._cm = connection_manager
        self._connection_name = connection_name

    def ensure_table(self) -> None:
        """Create the audit table if it doesn't exist. Migrate if missing attempt column."""
        adapter = self._cm.get(self._connection_name)
        try:
            adapter.execute(_CREATE_TABLE_SQL)
        except Exception:
            pass  # Table already exists
        try:
            adapter.execute(_ADD_ATTEMPT_COLUMN_SQL)
        except Exception:
            pass  # Column already exists

    def record(
        self,
        job_name: str,
        step_name: str | None,
        status: str,
        rows_affected: int | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        error_message: str | None = None,
        attempt: int | None = None,
    ) -> None:
        adapter = self._cm.get(self._connection_name)
        now = datetime.now(timezone.utc)
        adapter.execute(
            _INSERT_SQL,
            {
                "job_name": job_name,
                "step_name": step_name,
                "status": status,
                "rows_affected": rows_affected,
                "started_at": started_at or now,
                "finished_at": finished_at or now,
                "error_message": error_message,
                "attempt": attempt,
            },
        )


class StepTimer:
    """Tracks timing for a single step execution."""

    def __init__(self):
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None

    def __enter__(self):
        self.started_at = datetime.now(timezone.utc)
        return self

    def __exit__(self, *args):
        self.finished_at = datetime.now(timezone.utc)

    @property
    def elapsed_seconds(self) -> float:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return 0.0
