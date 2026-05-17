# PRD: Simple ELT Framework

## Problem Statement

Data engineers working with Oracle databases need a lightweight, configuration-driven tool to move data between schemas and databases. Existing solutions (Airflow, dbt, Fivetran) are heavyweight, require significant infrastructure, and impose workflows that don't fit simple extract-load-transform pipelines where transformation happens in-database via stored procedures. Teams need a tool that can be checked into source control alongside job definitions, run from a CLI, and require minimal setup.

## Solution

A Python CLI framework where each ELT job is a single YAML file defining source queries, target staging tables, and optional pre/post SQL blocks. The framework handles parameter resolution (static, CLI, and query-sourced), batch loading, IN-clause expansion (with Oracle 1000-item chunking), and audit logging. Adapters abstract database-specific behavior behind a clean interface, starting with Oracle and extensible to other databases.

## User Stories

1. As a data engineer, I want to define an ELT job in a YAML file, so that my data pipeline is version-controlled and reviewable alongside application code
2. As a data engineer, I want to run a job from the CLI with a single command, so that I can integrate it into scripts, cron, or CI/CD pipelines
3. As a data engineer, I want to extract data from one Oracle schema and load it into staging tables in another, so that I can decouple source reads from downstream transformations
4. As a data engineer, I want to call stored procedures after loading via post-SQL, so that I can transform staged data using existing PL/SQL logic
5. As a data engineer, I want to truncate staging tables before loading via pre-SQL, so that each run produces a clean, idempotent result
6. As a data engineer, I want to pass parameters from the CLI, so that I can override query filters without modifying job files
7. As a data engineer, I want query-sourced parameters, so that I can dynamically drive extraction logic from the database itself (e.g., active entity lists)
8. As a data engineer, I want list parameters expanded into IN clauses with 1000-item chunking, so that Oracle's IN clause limit is handled automatically
9. As a data engineer, I want to run multiple steps in a single job, so that I can load several related staging tables in one execution
10. As a data engineer, I want batch loading with configurable batch sizes, so that I can balance memory usage and throughput for large datasets
11. As a data engineer, I want an audit table recording every step execution, so that I can troubleshoot failures and verify run history
12. As a data engineer, I want to validate job YAML files without executing them, so that I can catch configuration errors before deployment
13. As a data engineer, I want a dry-run mode that previews execution without writing data, so that I can verify parameter resolution and query structure
14. As a data engineer, I want connection credentials sourced from environment variables, so that secrets don't appear in version-controlled YAML files
15. As a data engineer, I want to discover all jobs in a directory tree, so that I can organize jobs by domain (e.g., `jobs/ordering/`, `jobs/inventory/`)
16. As a data engineer, I want to load 10M+ rows with throughput exceeding 100K rows/sec, so that the framework handles production-scale data volumes
17. As a data engineer, I want NULL values preserved through the pipeline, so that data integrity is maintained
18. As a data engineer, I want empty result sets handled gracefully, so that zero-row extracts don't cause errors
19. As a data engineer, I want to implement incremental loads using watermarks, so that I can extract only new or changed data on subsequent runs
20. As a data engineer, I want to add adapters for PostgreSQL and Snowflake, so that I can move data between heterogeneous database platforms
21. As a data engineer, I want automatic target table creation based on source query metadata, so that I don't have to manually maintain staging table DDL
22. As a data engineer, I want source-to-target row count reconciliation, so that I can verify data completeness after each step
23. As a data engineer, I want configurable retry logic at the step level, so that transient connection failures don't kill the entire job
24. As a data engineer, I want parallel step execution for independent steps, so that multi-step jobs complete faster
25. As a data engineer, I want a watermark tracking table managed by the framework, so that incremental load state persists across runs
26. As a data engineer, I want job chaining or dependencies, so that I can run related jobs in sequence with downstream jobs only executing if upstream succeeds
27. As a data engineer, I want Slack/email notification on job failure, so that I'm alerted to issues without checking audit logs manually
28. As a data engineer, I want a `list` CLI command that shows all discovered jobs and their status, so that I can quickly see what's available
29. As a data engineer, I want YAML schema validation with clear error messages, so that I can fix misconfigured jobs quickly
30. As a data engineer, I want to override connection details at runtime, so that I can run the same job against dev/staging/prod environments

## Implementation Decisions

### Module Architecture

The framework is organized into seven deep modules, each with a clear interface:

1. **Adapters** — Abstract database interaction behind a `BaseAdapter` ABC with methods: `connect`, `close`, `execute`, `fetch_one`, `fetch_all`, `fetch_batches`, `insert_batch`, `get_columns`. The `OracleAdapter` implements this using `oracledb`. A `ConnectionManager` lazily creates, caches, and closes adapters. New adapters (PostgreSQL via `psycopg2`, Snowflake via `snowflake-connector-python`) implement the same ABC.

2. **Config** — Loads YAML job files, validates required fields (job_name, step source/target), discovers jobs by scanning a directory tree, and resolves `${ENV_VAR}` interpolation in all string values. Validation checks that referenced connections exist.

3. **Parameters** — `ParameterResolver` merges parameters from three sources (CLI > YAML > extras). `apply_to_sql` converts resolved parameters to Oracle bind variables (scalars) or expanded IN clauses (lists). IN-clause expansion auto-chunks at 1000 items for Oracle compatibility.

4. **Engine** — Orchestrates job execution: pre-SQL → steps → post-SQL. Each step is an extract-load loop: apply parameters to source query, fetch batches, insert into target. Commits per step per ADR 0001. Propagates failures upward.

5. **Audit** — `AuditLogger` creates and writes to an `elt_audit` table (run_id, job_name, step_name, status, rows_affected, started_at, finished_at, error_message). `StepTimer` context manager captures timing.

6. **CLI** — Click-based with `run` and `validate` commands. Thin orchestration layer that wires config, connections, parameters, engine, and audit together.

7. **Connections** — `ConnectionManager` maps connection names to adapter instances. An `ADAPTER_MAP` registry maps type strings (`"oracle"`, future: `"postgresql"`, `"snowflake"`) to adapter classes.

### Job YAML Schema

Jobs define `job_name`, optional `parameters` (static or query-sourced), optional `pre_sql` (connection + query list), required `steps` (name, source connection/query, target connection/table/batch_size), and optional `post_sql` (connection + query list).

### Parameter Resolution Order

CLI `--param` overrides take highest priority, then YAML-defined parameters (static values or query results), then extra CLI params not defined in YAML are added as-is.

### Commit Strategy

Per ADR 0001: commit after each step. No job-level transaction. On failure, completed steps remain committed. Pre-SQL truncation makes jobs idempotent.

### Audit Storage

Audit records are written to a connection designated by `--audit-connection` (defaults to the first connection in `connections.yaml`). The `elt_audit` table is auto-created if absent.

### Planned: Watermark Module

A new module managing incremental load state. A `watermarks` table stores `(job_name, step_name, watermark_column, watermark_value, updated_at)`. Steps with a `watermark` config read the last value and use it as a parameter in the source query. After successful step completion, the watermark is updated.

### Planned: Retry Module

Step-level retry configuration: `retry: max_attempts: 3, backoff_seconds: 5`. The engine wraps step execution with retry logic. Only retries on transient errors (connection failures, timeouts), not on data/schema errors.

### Planned: Reconciliation Module

After each step, compare source row count (from query metadata or COUNT) with target row count (from insert_batch return value or COUNT query). Log discrepancies to audit. Optionally fail the step if counts don't match.

### Planned: PostgreSQL Adapter

Implement `BaseAdapter` using `psycopg2`. Handle dialect differences: `%s` parameter style instead of `:name`, `COPY` for bulk inserts, `information_schema` for column discovery.

### Planned: Snowflake Adapter

Implement `BaseAdapter` using `snowflake-connector-python`. Handle dialect differences: `%s` or `:name` parameter style, `COPY INTO` for bulk loading, Snowflake information schema for column discovery.

## Testing Decisions

### What makes a good test

Tests should verify external behavior (inputs and outputs), not implementation details. A test for `ParameterResolver` should assert that given these YAML definitions and CLI params, the resolved parameter dict matches expected values — not that internal resolution order is preserved. Adapter tests should verify that `fetch_all` returns the expected data shape, not that a specific SQL string was constructed.

### Modules to test

1. **Parameters** — Unit tests for `ParameterResolver.resolve()` with various source combinations, `apply_to_sql()` with scalar and list params, `_expand_in_clause()` with sub-1000 and super-1000 lists. No database needed.

2. **Config** — Unit tests for `load_job()` validation (missing fields, duplicate job names, invalid parameter types), `discover_jobs()` with nested directories, `${ENV_VAR}` interpolation. Uses temp YAML files.

3. **Adapters** — Integration tests for `OracleAdapter` against Oracle XE in Docker. Tests for `insert_batch` round-trip, `fetch_batches` cursor behavior, `get_columns` metadata, NULL handling. The `BaseAdapter` ABC itself is tested indirectly through concrete implementations.

4. **Engine** — Integration tests using mock adapters. Verify step execution order, parameter application, error propagation, pre/post SQL execution.

5. **Audit** — Integration tests against Oracle for `ensure_table()` idempotency and `record()` field persistence. Unit tests for `StepTimer` timing accuracy.

6. **CLI** — End-to-end integration tests running `elt` as a subprocess and verifying exit codes, stdout/stderr content, and side effects in the database. This is the existing test pattern in `tests/run_tests.py`.

### Prior art

The existing `tests/run_tests.py` integration test suite (13 tests) establishes the pattern: run CLI subprocess, query Oracle via `oracledb` to verify results. New unit tests should complement this with faster, isolated tests that don't require a database.

## Out of Scope

- Real-time / streaming data ingestion (this is a batch ELT tool)
- Built-in scheduling or orchestration (delegate to cron, Airflow, or systemd)
- Data quality rules or great-expectations-style assertions
- Schema migration / DDL generation beyond staging table auto-creation
- GUI or web interface
- Multi-process or distributed execution
- Change Data Capture (CDC) from Oracle logs
- Data masking or encryption in transit (delegate to database-level features)
- Support for non-relational sources (CSV, JSON files, APIs)

## Further Notes

- The framework explicitly follows the ELT pattern: transformation happens in the target database via SQL/stored procedures, not in Python. This is a design constraint, not a limitation.
- Watermarks are currently implemented as query-sourced parameters (per CONTEXT.md). The planned watermark module formalizes this pattern with framework-managed state.
- The adapter registry pattern (`ADAPTER_MAP`) makes adding new database types straightforward — implement the ABC and register the type string.
- All Oracle-specific behavior (1000-item IN clause limit, TRUNCATE DDL semantics, bind variable syntax) is isolated to the Oracle adapter or the parameters module, keeping the core engine database-agnostic.
