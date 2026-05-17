# Commit per step, not per job

Each step in a job commits independently after loading. There is no transaction spanning the entire job. If a step fails, all previously completed steps remain committed and the job stops.

## Status

Accepted

## Context

A job runs pre-sql → step 1 → step 2 → ... → post-sql. We considered wrapping the entire job in a single transaction for all-or-nothing semantics.

## Decision

Commit after each step completes. Do not attempt to roll back completed steps on failure.

## Why

1. Oracle TRUNCATE is DDL and cannot be rolled back. Since pre-sql commonly truncates staging tables, an all-or-nothing transaction is impossible in the typical case.
2. Large data loads can exceed Oracle undo tablespace limits when held in a single transaction.
3. Each step loads into its own staging table, making per-step commits operationally safe — a partial run leaves behind clearly identifiable, self-contained staging data.
4. Post-sql (stored procedures) should manage their own transaction boundaries internally, as is standard PL/SQL practice.

## Consequences

- On failure, operators must inspect the audit table to understand which steps completed and which did not.
- Restarting a failed job requires understanding that pre-sql (e.g., truncate) will clear all staging tables, even those loaded successfully in the prior run. This is acceptable because the job is idempotent when pre-sql truncates first.
