from typing import Callable, Tuple

def test_full_pipeline(run_job: Callable[..., Tuple[bool, str]], table_counter: Callable[[str], int]):
    """TEST 5: Full pipeline (pre-sql + steps + post-sql + params)"""
    ok, out = run_job("test_full_pipeline")
    assert ok, f"Job failed: {out}"
    assert "Job completed successfully" in out
    
    count_stg = table_counter("stg_orders")
    assert count_stg >= 2, f"Expected staging orders to be loaded, got {count_stg}"
    
    count_dim = table_counter("dim_orders")
    assert count_dim >= 2, f"Expected dim orders to be transformed, got {count_dim}"
    
    count_cust = table_counter("dim_customers")
    assert count_cust >= 2, f"Expected dim customers to be transformed, got {count_cust}"


def test_null_data(run_job: Callable[..., Tuple[bool, str]], table_counter: Callable[[str], int]):
    """TEST 6: NULL data handling"""
    ok, out = run_job("test_null_data")
    assert ok, f"Job failed: {out}"
    assert "Job completed successfully" in out
    
    count = table_counter("stg_products")
    assert count == 5, f"Expected 5 products loaded, got {count}"
    
    null_count = table_counter(
        "(SELECT * FROM stg_products WHERE name IS NULL OR price IS NULL OR category IS NULL)"
    )
    assert null_count == 2, f"Expected exactly 2 products with NULL values preserved, got {null_count}"


def test_audit_trail(audit_counter: Callable[[str], int]):
    """TEST 11: Audit trail verification"""
    audit_full = audit_counter("test_full_pipeline")
    assert audit_full >= 5, f"Expected at least 5 audit records for full pipeline, got {audit_full}"
    
    audit_empty = audit_counter("test_empty_result")
    assert audit_empty >= 2, f"Expected at least 2 audit records for empty result, got {audit_empty}"
