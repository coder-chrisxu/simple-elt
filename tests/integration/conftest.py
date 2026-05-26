import os
import pytest
import re
import subprocess
from typing import Callable, Tuple

UV = "uv"


def run_sql(sql: str, user: str = "target_user", password: str = "TargetPass123") -> str:
    cmd = [
        "docker", "exec", "oracle-xe", "bash", "-c",
        f"source /home/oracle/.bashrc; echo 'SET PAGESIZE 200 FEEDBACK OFF HEADING OFF\n{sql}\n/\nQUIT' | sqlplus -s {user}/{password}@localhost:1521/XEPDB1"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.stdout


@pytest.fixture(autouse=True)
def clean_database():
    """Truncate all staging tables before and after each test case for isolation."""
    def truncate_all():
        for t in [
            "stg_orders", "stg_customers", "stg_products",
            "stg_transactions", "stg_archived_orders",
        ]:
            run_sql(f"TRUNCATE TABLE {t}")
    truncate_all()
    yield
    truncate_all()


@pytest.fixture
def run_job() -> Callable[..., Tuple[bool, str]]:
    """Fixture to execute an ELT job command and return (success, output)."""
    def _run(job_name: str, verbose: bool = False, extra_args: list[str] = None) -> Tuple[bool, str]:
        cmd = [UV, "run", "elt"]
        if verbose:
            cmd.append("--verbose")
        cmd.extend(["run", "--job", job_name])
        if extra_args:
            cmd.extend(extra_args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return result.returncode == 0, result.stdout + result.stderr
    return _run


@pytest.fixture
def table_counter() -> Callable[[str], int]:
    """Fixture to count rows in a target table (default target schema)."""
    def _count(table: str) -> int:
        out = run_sql(f"SELECT COUNT(*) FROM {table}")
        for line in out.splitlines():
            line = line.strip()
            if re.match(r'^\d+$', line):
                return int(line)
        return -1
    return _count


@pytest.fixture
def audit_counter() -> Callable[[str], int]:
    """Fixture to count audit records for a job name directly in DB."""
    def _count(job_name: str) -> int:
        import oracledb
        conn = oracledb.connect(
            user="source_user", password="SourcePass123",
            host="localhost", port=1521, service_name="XEPDB1"
        )
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM elt_audit WHERE job_name = :jn",
                {"jn": job_name}
            )
            count = cursor.fetchone()[0]
            cursor.close()
            return count
        finally:
            conn.close()
    return _count
