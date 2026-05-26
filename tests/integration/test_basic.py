from typing import Callable, Tuple

def test_basic_extract_load(run_job: Callable[..., Tuple[bool, str]], table_counter: Callable[[str], int]):
    """TEST 1: Basic extract-load (no pre/post SQL, no params)"""
    ok, out = run_job("test_basic_extract_load")
    assert ok, f"Job failed: {out}"
    assert "Job completed successfully" in out
    
    count = table_counter("stg_products")
    assert count == 5, f"Expected 5 products, got {count}"


def test_batch_chunking(run_job: Callable[..., Tuple[bool, str]], table_counter: Callable[[str], int]):
    """TEST 2: Batch chunking (200 rows, batch_size=50)"""
    ok, out = run_job("test_batch_chunking", verbose=True)
    assert ok, f"Job failed: {out}"
    assert "Job completed successfully" in out
    
    count = table_counter("stg_transactions")
    assert count == 200, f"Expected 200 transactions, got {count}"
    assert out.count("Loaded") >= 3, f"Expected batch progress log statements, got: {out}"


def test_empty_result(run_job: Callable[..., Tuple[bool, str]], table_counter: Callable[[str], int]):
    """TEST 4: Empty result set (empty is OK)"""
    ok, out = run_job("test_empty_result")
    assert ok, f"Job failed: {out}"
    assert "Job completed successfully" in out
    
    count = table_counter("stg_archived_orders")
    assert count == 0, f"Expected 0 rows, got {count}"


def test_dry_run(run_job: Callable[..., Tuple[bool, str]], table_counter: Callable[[str], int]):
    """TEST 9: Dry run (no data written)"""
    ok, out = run_job("test_basic_extract_load", extra_args=["--dry-run"])
    assert ok, f"Dry run failed: {out}"
    
    count = table_counter("stg_products")
    assert count == 0, f"Expected 0 rows in dry run, got {count}"
