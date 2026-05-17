# Data Load ELT Framework

A reusable Python framework for Extract-Load-Transform pipelines. Extracts data from source databases (primarily Oracle), loads into target staging tables, then transforms in-place via SQL and stored procedures.

## Language

**Job**:
A complete ELT pipeline defined in a single YAML file, containing one or more steps plus optional pre/post SQL blocks.
_Avoid_: Pipeline, workflow, task

**Step**:
A single extract→load operation within a job. One source query loading into one target staging table.
_Avoid_: Task, stage, operation

**Connection**:
A named database endpoint configured in connections.yaml, referenced by jobs. Abstracted behind an adapter interface to support multiple database types.
_Avoid_: Database, datasource, endpoint

**Adapter**:
A database-specific implementation of the connection interface (e.g., Oracle adapter). Handles SQL dialect, parameter binding, and batch operations.
_Avoid_: Driver, plugin, connector

**Pre-SQL**:
A list of SQL statements executed before all steps in a job. Typically used for staging table preparation (truncate, drop indexes).
_Avoid_: Pre-processing, setup SQL, initialization

**Post-SQL**:
A list of SQL statements executed after all steps complete. Typically calls PL/SQL stored procedures to transform staged data.
_Avoid_: Post-processing, transformation SQL, finalization

**Parameter**:
A named value substituted into SQL queries at runtime. Can be sourced statically (YAML), from the command line, or dynamically from a database query.
_Avoid_: Variable, argument, placeholder

**List Parameter**:
A parameter whose value is a list, expanded into SQL IN clauses via string interpolation with safe quoting. Auto-chunked to respect Oracle's 1000-item IN clause limit.
_Avoid_: Array parameter, multi-value

**Watermark**:
A timestamp or value used for incremental extraction. Implemented as a query-sourced parameter — no special framework feature.
_Avoid_: High-water mark, cursor, checkpoint, offset

**Audit Record**:
A row in the framework's audit table recording the outcome of each job step — status, rows affected, timing, and error details.
_Avoid_: Log entry, history row, run record

## Relationships

- A **Job** contains zero or more **Pre-SQL** statements, one or more **Steps**, and zero or more **Post-SQL** statements, executed in that order
- Each **Step** references one **Connection** as source and one **Connection** as target
- A **Job** may reference multiple **Connections** across its steps and SQL blocks
- A **Parameter** may be resolved from a **Connection** (query-sourced) or provided statically/externally
- Each **Step** execution produces one **Audit Record**

## Example dialogue

> **Dev:** "When the `load_customer_orders` job runs, what happens first?"
> **Domain expert:** "Pre-SQL truncates the staging tables. Then each step extracts from source and loads into its target staging table. After all steps complete, Post-SQL calls the stored procedures that transform the staged data into the final tables."

> **Dev:** "How do we handle incremental loads?"
> **Domain expert:** "Define a **Watermark** — a query-sourced **Parameter** that reads the max timestamp from the target. Use it in the source query's WHERE clause. After the job, update the watermark table in Post-SQL."

## Flagged ambiguities

- "ELT" vs "ETL" — resolved: this is explicitly ELT. Transformation happens in the target database after loading, not in Python.
