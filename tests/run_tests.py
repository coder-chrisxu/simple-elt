"""Run all ELT test cases and verify results."""
import re
import subprocess
import sys

UV = "uv"


def run_cmd(cmd: list[str]) -> tuple[bool, str]:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    ok = result.returncode == 0
    output = result.stdout + result.stderr
    return ok, output


def run_sql(sql: str, user: str = "target_user", password: str = "TargetPass123") -> str:
    cmd = [
        "docker", "exec", "oracle-xe", "bash", "-c",
        f"source /home/oracle/.bashrc; echo 'SET PAGESIZE 200 FEEDBACK OFF HEADING OFF\n{sql}\n/\nQUIT' | sqlplus -s {user}/{password}@localhost:1521/XEPDB1"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.stdout


def count_table(table: str, user: str = "target_user") -> int:
    out = run_sql(f"SELECT COUNT(*) FROM {table}", user=user)
    for line in out.splitlines():
        line = line.strip()
        if re.match(r'^\d+$', line):
            return int(line)
    return -1


def count_audit(job_name: str) -> int:
    """Count audit records using oracledb directly.

    Note: audit table lives in source_user schema because it defaults to
    the first connection in connections.yaml (source_oracle).
    """
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


class TestResult:
    def __init__(self, name):
        self.name = name
        self.passed = False
        self.details = ""

    def __repr__(self):
        icon = "PASS" if self.passed else "FAIL"
        return f"  [{icon}] {self.name}: {self.details}"


results: list[TestResult] = []


def test(name, condition, details=""):
    r = TestResult(name)
    r.passed = condition
    r.details = details
    results.append(r)
    icon = "PASS" if condition else "FAIL"
    print(f"  [{icon}] {name}: {details}")
    return condition


def clean_all():
    """Truncate all staging tables for a clean slate."""
    for t in [
        "stg_orders", "stg_customers", "stg_products",
        "stg_transactions", "stg_archived_orders",
    ]:
        run_sql(f"TRUNCATE TABLE {t}")


# Start clean
clean_all()

# ============================================================
print("=" * 60)
print("TEST 1: Basic extract-load (no pre/post SQL, no params)")
print("=" * 60)
ok, out = run_cmd([UV, "run", "elt", "run", "--job", "test_basic_extract_load"])
test("job exits 0", ok, out.strip().split("\n")[-1] if out else "no output")
count = count_table("stg_products")
test("loaded 5 products", count == 5, f"got {count} rows")
clean_all()

# ============================================================
print("\n" + "=" * 60)
print("TEST 2: Batch chunking (200 rows, batch_size=50)")
print("=" * 60)
ok, out = run_cmd([UV, "run", "elt", "--verbose", "run", "--job", "test_batch_chunking"])
test("job exits 0", ok, out.strip().split("\n")[-1] if out else "no output")
count = count_table("stg_transactions")
test("loaded 200 transactions", count == 200, f"got {count} rows")
test("shows batch progress in log",
     out.count("Loaded") >= 3, f"saw {out.count('Loaded')} batch log lines (expect >=3)")
clean_all()

# ============================================================
print("\n" + "=" * 60)
print("TEST 3: Query-sourced parameters")
print("=" * 60)
ok, out = run_cmd([UV, "run", "elt", "run", "--job", "test_query_params"])
test("job exits 0", ok, out.strip().split("\n")[-1] if out else "no output")
count = count_table("stg_orders")
test("loaded rows via query param", count >= 5, f"got {count} rows")
clean_all()

# ============================================================
print("\n" + "=" * 60)
print("TEST 4: Empty result set")
print("=" * 60)
ok, out = run_cmd([UV, "run", "elt", "run", "--job", "test_empty_result"])
test("job exits 0 (empty is OK)", ok, out.strip().split("\n")[-1] if out else "no output")
count = count_table("stg_archived_orders")
test("loaded 0 rows", count == 0, f"got {count} rows")
clean_all()

# ============================================================
print("\n" + "=" * 60)
print("TEST 5: Full pipeline (pre-sql + steps + post-sql + params)")
print("=" * 60)
ok, out = run_cmd([UV, "run", "elt", "run", "--job", "test_full_pipeline"])
test("job exits 0", ok, out.strip().split("\n")[-1] if out else "no output")
count_stg = count_table("stg_orders")
test("staging orders loaded", count_stg >= 2, f"got {count_stg} rows")
count_dim = count_table("dim_orders")
test("dim orders transformed by SP", count_dim >= 2, f"got {count_dim} rows")
count_cust = count_table("dim_customers")
test("dim customers transformed by SP", count_cust >= 2, f"got {count_cust} rows")
clean_all()

# ============================================================
print("\n" + "=" * 60)
print("TEST 6: NULL data handling")
print("=" * 60)
ok, out = run_cmd([UV, "run", "elt", "run", "--job", "test_null_data"])
test("job exits 0", ok, out.strip().split("\n")[-1] if out else "no output")
count = count_table("stg_products")
test("loaded 5 products with NULLs", count == 5, f"got {count} rows")
null_count = count_table(
    "(SELECT * FROM stg_products WHERE name IS NULL OR price IS NULL OR category IS NULL)"
)
test("NULL values preserved", null_count == 2, f"got {null_count} rows with NULLs")
clean_all()

# ============================================================
print("\n" + "=" * 60)
print("TEST 7: CLI parameter override")
print("=" * 60)
ok, out = run_cmd([
    UV, "run", "elt", "run", "--job", "test_cli_params",
    "--param", "status_filter=ACTIVE"
])
test("job exits 0", ok, out.strip().split("\n")[-1] if out else "no output")
count = count_table("stg_orders")
test("loaded only ACTIVE orders", count == 3, f"got {count} rows")
clean_all()

# ============================================================
print("\n" + "=" * 60)
print("TEST 8: Multi-step with mixed param sources")
print("=" * 60)
ok, out = run_cmd([UV, "run", "elt", "run", "--job", "test_multi_step"])
test("job exits 0", ok, out.strip().split("\n")[-1] if out else "no output")
count_prod = count_table("stg_products")
test("loaded Electronics products only", count_prod == 3, f"got {count_prod} rows")
count_txn = count_table("stg_transactions")
test("loaded transactions for active entities", count_txn > 0, f"got {count_txn} rows")
clean_all()

# ============================================================
print("\n" + "=" * 60)
print("TEST 9: Dry run (no data written)")
print("=" * 60)
ok, out = run_cmd([UV, "run", "elt", "run", "--job", "test_basic_extract_load", "--dry-run"])
test("dry run exits 0", ok, "")
count = count_table("stg_products")
test("no data written", count == 0, f"got {count} rows (expected 0)")

# ============================================================
print("\n" + "=" * 60)
print("TEST 10: Validate command")
print("=" * 60)
ok, out = run_cmd([UV, "run", "elt", "validate"])
test("validate exits 0", ok, out.strip().split("\n")[-1] if out else "no output")
test("all jobs listed", "OK" in out, "jobs validated OK")

# ============================================================
print("\n" + "=" * 60)
print("TEST 11: Audit trail verification")
print("=" * 60)
audit_full = count_audit("test_full_pipeline")
test("audit records written for full pipeline",
     audit_full >= 5, f"got {audit_full} records (expect 5+: 2 pre + 2 steps + 2 post)")

audit_empty = count_audit("test_empty_result")
test("audit records written for empty result job",
     audit_empty >= 2, f"got {audit_empty} records (expect 2+: 1 pre + 1 step)")

# ============================================================
print("\n" + "=" * 60)
print("TEST 12: Large volume (10M rows)")
print("=" * 60)
ok, out = run_cmd([UV, "run", "elt", "run", "--job", "test_large_volume"])
test("10M row job exits 0", ok, out.strip().split("\n")[-1] if out else "no output")
count = count_table("stg_large_events")
test("loaded 10M rows", count == 10_000_000, f"got {count:,} rows")
test("step completion logged",
     "10,000,000 rows" in out or "10000000 rows" in out,
     "row count confirmed in log")

# Extract timing from log
import re
time_match = re.search(r"complete: 10000000 rows in ([\d.]+)s", out)
if time_match:
    elapsed = float(time_match.group(1))
    rate = 10_000_000 / elapsed
    test("throughput > 100K rows/s", rate > 100_000, f"{rate:,.0f} rows/s in {elapsed:.1f}s")
else:
    test("throughput check", False, "could not parse timing from log")

# ============================================================
print("\n" + "=" * 60)
print("TEST 13: Job not found error")
print("=" * 60)
ok, out = run_cmd([UV, "run", "elt", "run", "--job", "nonexistent_job"])
test("exits non-zero for missing job", not ok, f"exit code {'0' if ok else 'non-zero'}")
test("error message mentions job", "not found" in out.lower(), "error message shown")

# ============================================================
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
passed = sum(1 for r in results if r.passed)
failed = sum(1 for r in results if not r.passed)
print(f"\n  Total: {len(results)}  Passed: {passed}  Failed: {failed}")
if failed:
    print("\n  Failures:")
    for r in results:
        if not r.passed:
            print(f"    {r}")
    sys.exit(1)
else:
    print("\n  All tests passed!")
