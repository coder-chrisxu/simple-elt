import re
from typing import Callable, Tuple

def test_large_volume(run_job: Callable[..., Tuple[bool, str]], table_counter: Callable[[str], int]):
    """TEST 12: Large volume (10M rows)"""
    ok, out = run_job("test_large_volume")
    assert ok, f"Job failed: {out}"
    assert "Job completed successfully" in out
    
    count = table_counter("stg_large_events")
    assert count == 10_000_000, f"Expected 10M rows in staging table, got {count:,}"
    assert "10,000,000 rows" in out or "10000000 rows" in out, "Expected row count in execution log"
    
    time_match = re.search(r"complete: 10000000 rows in ([\d.]+)s", out)
    assert time_match is not None, "Expected elapsed timing in execution log"
    
    elapsed = float(time_match.group(1))
    rate = 10_000_000 / elapsed
    assert rate > 100_000, f"Throughput too low: {rate:,.0f} rows/s in {elapsed:.1f}s"
