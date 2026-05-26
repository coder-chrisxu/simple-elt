from typing import Callable, Tuple

def test_query_sourced_params(run_job: Callable[..., Tuple[bool, str]], table_counter: Callable[[str], int]):
    """TEST 3: Query-sourced parameters"""
    ok, out = run_job("test_query_params")
    assert ok, f"Job failed: {out}"
    assert "Job completed successfully" in out
    
    count = table_counter("stg_orders")
    assert count >= 5, f"Expected at least 5 orders, got {count}"


def test_cli_param_override(run_job: Callable[..., Tuple[bool, str]], table_counter: Callable[[str], int]):
    """TEST 7: CLI parameter override"""
    ok, out = run_job("test_cli_params", extra_args=["--param", "status_filter=ACTIVE"])
    assert ok, f"Job failed: {out}"
    assert "Job completed successfully" in out
    
    count = table_counter("stg_orders")
    assert count == 3, f"Expected exactly 3 ACTIVE orders, got {count}"


def test_multi_step_mixed_params(run_job: Callable[..., Tuple[bool, str]], table_counter: Callable[[str], int]):
    """TEST 8: Multi-step with mixed param sources"""
    ok, out = run_job("test_multi_step")
    assert ok, f"Job failed: {out}"
    assert "Job completed successfully" in out
    
    count_prod = table_counter("stg_products")
    assert count_prod == 3, f"Expected exactly 3 Electronics products, got {count_prod}"
    
    count_txn = table_counter("stg_transactions")
    assert count_txn > 0, f"Expected > 0 active transactions, got {count_txn}"


def test_parameter_edge_cases(run_job: Callable[..., Tuple[bool, str]], table_counter: Callable[[str], int], audit_counter: Callable[[str], int]):
    """TEST 14: Parameter Edge Cases (collisions, spacing, lists >1000, quotes, NULLs, pre/post parameters)"""
    ok, out = run_job("test_parameter_edge_cases", verbose=True)
    assert ok, f"Job failed: {out}"
    assert "Job completed successfully: test_parameter_edge_cases" in out

    count_orders = table_counter("stg_orders")
    assert count_orders == 9, f"Expected exactly 9 orders (4 from step 1 + 5 from step 5), got {count_orders}"

    count_products = table_counter("stg_products")
    assert count_products == 6, f"Expected exactly 6 products (4 from step 2 + 2 from step 4), got {count_products}"

    count_txns = table_counter("stg_transactions")
    assert count_txns == 1005, f"Expected exactly 1005 transactions, got {count_txns}"

    audit_count = audit_counter("test_parameter_edge_cases")
    assert audit_count >= 7, f"Expected at least 7 audit records, got {audit_count}"
