# PRD: Retry & Resilience

## Problem Statement

Data engineers running ELT jobs against Oracle databases encounter transient failures — network blips, connection drops, timeout errors (ORA-03113, ORA-03114, ORA-02396) — that kill the entire job. Because the engine has no retry logic, a momentary connectivity hiccup during a 10M-row load forces a full re-run. Operators must manually inspect audit logs, restart jobs, and verify that partially-loaded data (from prior committed steps) is consistent. This is fragile, slow, and discourages running large jobs unattended.

## Solution

Add configurable, step-level retry logic to the ELT engine. Each step (and pre/post SQL block) can declare a retry policy specifying max attempts and backoff strategy. A new error classifier distinguishes transient database errors from permanent ones — only transient errors trigger retries. When a retry occurs, the connection is reset (close + reconnect) before the next attempt, and each retry attempt is recorded in the audit table so operators can spot recurring transient issues. Permanent errors and exhausted retries still fail the step and propagate upward as before.

## User Stories

1. As a data engineer, I want to configure retry logic on a step, so that transient connection failures don't kill the entire job
2. As a data engineer, I want retry configuration to be optional with sensible defaults, so that existing jobs without retry config continue to work unchanged
3. As a data engineer, I want to set a maximum number of retry attempts per step, so that a genuinely broken connection doesn't retry forever
4. As a data engineer, I want fixed backoff between retries, so that the database has time to recover before the next attempt
5. As a data engineer, I want exponential backoff between retries, so that retries progressively give the system more recovery time
6. As a data engineer, I want to configure a maximum backoff duration, so that exponential backoff doesn't wait unreasonably long
7. As a data engineer, I want the framework to distinguish transient errors from permanent errors, so that syntax errors or constraint violations fail immediately without wasting retry attempts
8. As a data engineer, I want Oracle-specific error codes (ORA-03113, ORA-03114, ORA-02396, ORA-12571, ORA-03135) to be automatically classified as transient, so that common network and timeout issues trigger retries without manual configuration
9. As a data engineer, I want the framework to reconnect before retrying after a connection failure, so that the retry operates on a fresh database session
10. As a data engineer, I want each retry attempt recorded in the audit table, so that I can see patterns of transient failures across job runs
11. As a data engineer, I want the audit record for a retry to show the attempt number, so that I can distinguish the initial attempt from retries
12. As a data engineer, I want the final audit record to show "success" if a retry succeeded, not "retry_success", so that downstream monitoring treats it as a normal successful run
13. As a data engineer, I want pre-SQL and post-SQL blocks to support retry configuration, so that a transient failure during a stored procedure call doesn't leave the job in a partial state
14. As a data engineer, I want to configure retry at the job level as a default for all steps, so that I don't have to repeat the same retry config on every step
15. As a data engineer, I want step-level retry config to override job-level retry config, so that I can tune retry behavior per step when needed
16. As a data engineer, I want to see retry attempts in the CLI log output, so that I can monitor retry activity in real time during a job run
17. As a data engineer, I want the dry-run command to show retry configuration, so that I can verify my retry settings before executing
18. As a data engineer, I want to configure a backoff multiplier for exponential backoff, so that I can control how aggressively the wait time increases
19. As a data engineer, I want connection recovery to be transparent, so that a dropped connection is re-established without manual intervention
20. As a data engineer, I want the error classifier to be extensible per adapter, so that PostgreSQL or Snowflake adapters can define their own transient error codes
21. As a data engineer, I want non-retryable errors to fail immediately with no delay, so that I get fast feedback on configuration or schema problems
22. As a data engineer, I want the total retry duration to be bounded, so that a job can't spend hours retrying a step that will never succeed
23. As a data engineer, I want the engine to log the error classification (transient vs permanent), so that I can debug why a step did or did not retry
24. As a data engineer, I want retry on insert_batch failures mid-stream, so that a connection drop after loading 5 of 10 batches triggers a full step retry (re-extract and re-load from scratch, relying on pre-SQL truncate for idempotency)

## Implementation Decisions

### Module 1: Retry Policy

A new module (`retry.py`) containing a `RetryPolicy` data class:

- `max_attempts: int` — Total attempts including the first (default: 1, meaning no retry)
- `backoff_strategy: str` — `"fixed"` or `"exponential"` (default: `"fixed"`)
- `backoff_seconds: float` — Base delay between retries (default: 5.0)
- `backoff_multiplier: float` — Multiplier for exponential backoff (default: 2.0)
- `max_backoff_seconds: float` — Cap on backoff duration (default: 300.0)

Parsed from the `retry` key in step or job YAML:

```yaml
steps:
  - name: load_orders
    retry:
      max_attempts: 3
      backoff_strategy: exponential
      backoff_seconds: 2
      max_backoff_seconds: 60
```

Job-level retry config is set at the top level of the job YAML and applies to all steps and SQL blocks unless overridden. Validation rejects `max_attempts < 1` and unknown backoff strategies.

### Module 2: Error Classifier

A new module (`errors.py`) containing:

- `ErrorClassifier` ABC with a single method: `classify(exception) -> ErrorClass` where `ErrorClass` is an enum: `TRANSIENT` or `PERMANENT`.
- `OracleErrorClassifier` implementation mapping Oracle error codes to classifications. Transient codes include: ORA-03113 (end-of-file on communication channel), ORA-03114 (not connected to ORACLE), ORA-02396 (exceeded maximum idle time), ORA-12571 (TNS:packet writer failure), ORA-03135 (connection lost contact), ORA-02248 (invalid option for initialization), ORA-12514 (TNS:listener does not currently know of service), ORA-12170 (TNS:connect timeout occurred).
- The classifier also treats `ConnectionError`, `TimeoutError`, and `OSError` subclasses as transient regardless of error code.
- An `ADAPTER_ERROR_CLASSIFIERS` registry (mirroring `ADAPTER_MAP`) maps adapter type strings to classifier classes. The engine looks up the classifier based on the connection's adapter type.
- Unrecognized errors default to `PERMANENT` — safe default that avoids retrying on unknown failures.

### Module 3: Retry Executor

A new module (within `retry.py`) containing a `RetryExecutor` class:

- `__init__(policy: RetryPolicy, classifier: ErrorClassifier, on_retry: Callable[[int, Exception, float], None])` — Takes the retry policy, error classifier for the relevant adapter, and a callback invoked on each retry (used for logging and audit).
- `execute(callable, *args, **kwargs) -> result` — Runs the callable with retry logic. On `TRANSIENT` error, sleeps for backoff duration and retries. On `PERMANENT` error, re-raises immediately. Raises the final exception after exhausting `max_attempts`.
- `_calculate_backoff(attempt: int) -> float` — Computes delay: fixed returns `backoff_seconds`, exponential returns `min(backoff_seconds * (multiplier ** (attempt - 1)), max_backoff_seconds)`.
- The `on_retry` callback receives `(attempt_number, exception, backoff_seconds)` and is called before sleeping, giving the engine a chance to log and record audit before the delay.

### Module 4: Engine Modifications

The `Engine` class is modified to integrate retry:

- `_get_retry_policy(context: dict, job: dict) -> RetryPolicy | None` — Resolves retry config. Checks the step/SQL-block dict first, falls back to `job.get("retry")`, returns `None` if neither specifies retry.
- `_run_steps` wraps each `_execute_step` call: if a retry policy exists, creates a `RetryExecutor` and calls `executor.execute(self._execute_step, step, params)`. The `on_retry` callback reconnects affected connections and records a retry audit row.
- `_run_pre_sql` and `_run_post_sql` similarly wrap each SQL execution.
- Reconnection: the `on_retry` callback calls `ConnectionManager.reconnect()` for all connections referenced by the step or SQL block, ensuring a clean session.
- The `on_retry` callback records an audit row with `status="retry"`, `step_name` set to the step name, and `error_message` containing the transient error details. This creates an audit trail of retry attempts.
- After a successful retry, the normal "success" audit row is written (no "retry_success" status — the final outcome is what matters for monitoring).

### Module 5: ConnectionManager Modification

`ConnectionManager` gets a new method:

- `reconnect(name: str) -> None` — Closes the existing cached adapter for the given connection name (if present), removes it from the cache, then calls `get(name)` to create and connect a fresh adapter. If the connection name is not in the config, raises `ValueError` as before. If reconnection itself fails, the exception propagates (the retry executor will treat it as another attempt).

### Module 6: Audit Modifications

The `AuditLogger.record()` method gets an optional `attempt` parameter:

- `attempt: int | None = None` — When provided, indicates which attempt number this record corresponds to (1 = initial, 2+ = retries).
- The `elt_audit` table gets a new `attempt NUMBER` column. `ensure_table()` handles the migration: if the table exists without the column, `ALTER TABLE elt_audit ADD attempt NUMBER` is executed. New tables include the column from creation.
- Audit rows for initial attempts have `attempt=1`. Retry attempt rows have `attempt` matching the retry number and `status="retry"`. The final successful row has `attempt` matching whichever attempt succeeded and `status="success"`.

### Job YAML Schema Changes

Retry can be configured at two levels:

```yaml
# Job-level default (applies to all steps, pre_sql, post_sql)
job_name: load_orders
retry:
  max_attempts: 3
  backoff_strategy: fixed
  backoff_seconds: 5

steps:
  - name: load_orders
    # Inherits job-level retry
    source: ...
    target: ...

  - name: load_customers
    # Overrides job-level retry
    retry:
      max_attempts: 5
      backoff_strategy: exponential
    source: ...
    target: ...

  - name: load_products
    # Explicitly disables retry for this step
    retry:
      max_attempts: 1
    source: ...
    target: ...
```

Pre-SQL and Post-SQL blocks also support a `retry` key per statement:

```yaml
pre_sql:
  - connection: target_oracle
    query: "TRUNCATE TABLE stg_orders"
    retry:
      max_attempts: 2
```

### Config Validation Changes

`load_job()` in `config.py` validates the new `retry` key:
- If present, `max_attempts` must be a positive integer
- `backoff_strategy` must be `"fixed"` or `"exponential"` if present
- `backoff_seconds` must be a positive number if present
- `backoff_multiplier` must be a positive number if present (only meaningful with exponential strategy)
- `max_backoff_seconds` must be a positive number if present

### CLI Changes

- Dry-run output includes retry configuration: `Retry: 3 attempts, exponential backoff (2s base, 60s max)` for each step, or `Retry: none` if not configured.
- Verbose mode logs retry attempts in real time: `Retry attempt 2/3 for step 'load_orders' after TRANSIENT error (ORA-03113), waiting 4.0s`

## Testing Decisions

### What makes a good test

Tests should verify external behavior — given a retry policy configuration and an error, does the executor retry the correct number of times with the correct delays and classify errors correctly? Tests should not assert on internal method call sequences or private attribute state.

### Modules to test

1. **Retry Policy (unit)** — Parse `RetryPolicy` from YAML dicts. Verify default values (max_attempts=1, fixed backoff, 5s base). Verify validation rejects invalid configs (max_attempts=0, unknown strategy, negative backoff). Verify job-level inheritance and step-level override. Verify explicit disable (max_attempts=1). No database needed — pure data transformation tests.

### Prior art

The existing `tests/run_tests.py` integration test suite establishes the pattern: run CLI subprocess, query Oracle via `oracledb` to verify results. Unit tests complement this with fast, isolated tests using temp YAML files, similar to how the existing config tests would work.

## Out of Scope

- Retry with partial batch recovery (resuming from the failed batch within a step) — retries re-run the entire step from scratch, relying on pre-SQL truncate for idempotency
- Circuit breaker patterns (tracking failure rates across jobs and disabling steps)
- Dead letter queues or failed-row capture
- Retry budgets or rate limiting across concurrent jobs
- Notification on retry (Slack, email) — separate from retry logic
- Retry for the validate command (no execution, no failures to retry)
- Configurable custom error code lists per job (use the adapter-level classifier instead)
- Distributed locking or concurrency-aware retry coordination

## Further Notes

- Retry operates at the step level, not the batch level. If an `insert_batch` call fails mid-step (after 5 of 10 batches), the retry re-extracts from the source and re-loads all batches. This relies on pre-SQL truncation for idempotency — if a job doesn't truncate before loading, a retry will produce duplicate rows. This is documented as a responsibility of the job author.
- The error classifier defaults to `PERMANENT` for unrecognized errors. This is the safe choice: retrying on unknown failures can mask real problems. As new transient error patterns are discovered, they can be added to the adapter-specific classifier.
- The `attempt` column in `elt_audit` is nullable for backward compatibility. Existing rows (from before this feature) have `NULL` for attempt, which is treated as attempt 1 by convention.
- Connection reconnection in `on_retry` closes and recreates the adapter. This means any session-level state (temporary tables, transaction state) is lost. Since the framework commits per step (ADR 0001), this is safe — a retried step starts with a clean session.
