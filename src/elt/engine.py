import logging
from typing import Any

from elt.audit import AuditLogger, StepTimer
from elt.connections import ConnectionManager
from elt.errors import CLASSIFIER_MAP
from elt.parameters import ParameterResolver
from elt.retry import RetryExecutor, RetryPolicy

logger = logging.getLogger("elt")

DEFAULT_BATCH_SIZE = 5000


class Engine:
    """Orchestrates ELT job execution: resolve params, run pre-sql, steps, post-sql."""

    def __init__(
        self,
        connection_manager: ConnectionManager,
        parameter_resolver: ParameterResolver,
        audit_logger: AuditLogger,
    ):
        self._cm = connection_manager
        self._params = parameter_resolver
        self._audit = audit_logger

    def run(self, job: dict, cli_params: dict[str, Any] | None = None) -> None:
        """Execute a complete job."""
        job_name = job["job_name"]
        logger.info("Starting job: %s", job_name)

        resolved = self._params.resolve(job.get("parameters"), cli_params)
        logger.info("Resolved parameters: %s", list(resolved.keys()))

        try:
            self._run_pre_sql(job, resolved, job_name)
            self._run_steps(job, resolved, job_name)
            self._run_post_sql(job, resolved, job_name)
            logger.info("Job completed successfully: %s", job_name)
        except Exception:
            logger.exception("Job failed: %s", job_name)
            raise

    def validate(self, job: dict) -> list[str]:
        """Validate a job config without executing. Returns list of warnings."""
        warnings = []
        job_name = job.get("job_name", "unknown")

        for step in job.get("steps", []):
            conn = step["source"]["connection"]
            try:
                self._cm.get(conn)
            except ValueError as e:
                warnings.append(f"Step '{step.get('name', '?')}': {e}")

            conn = step["target"]["connection"]
            try:
                self._cm.get(conn)
            except ValueError as e:
                warnings.append(f"Step '{step.get('name', '?')}': {e}")

        for block_name in ("pre_sql", "post_sql"):
            for item in job.get(block_name, []):
                try:
                    self._cm.get(item["connection"])
                except ValueError as e:
                    warnings.append(f"{block_name}: {e}")

        if not warnings:
            logger.info("Validation passed for job: %s", job_name)
        else:
            for w in warnings:
                logger.warning("Validation issue: %s", w)

        return warnings

    def _get_retry_policy(self, context: dict, job: dict) -> RetryPolicy | None:
        """Resolve retry policy: context-level overrides job-level."""
        policy = RetryPolicy.from_dict(context.get("retry"))
        if policy is not None:
            return policy
        return RetryPolicy.from_dict(job.get("retry"))

    def _get_classifier(self, connection_name: str):
        """Get the error classifier for a connection's adapter type."""
        config = self._cm._config.get(connection_name, {})
        adapter_type = config.get("type", "oracle")
        classifier_cls = CLASSIFIER_MAP.get(adapter_type)
        if classifier_cls is None:
            return None
        return classifier_cls()

    def _make_retry_callback(self, job_name: str, step_name: str, connections: list[str]):
        """Create an on_retry callback that reconnects connections and logs to audit."""
        def on_retry(attempt: int, exception: Exception, backoff: float) -> None:
            for conn_name in connections:
                try:
                    self._cm.reconnect(conn_name)
                    logger.debug("Reconnected: %s", conn_name)
                except Exception as reconnect_err:
                    logger.warning("Reconnection failed for %s: %s", conn_name, reconnect_err)
            self._audit.record(
                job_name=job_name,
                step_name=step_name,
                status="retry",
                error_message=f"Attempt {attempt} failed: {exception}",
                attempt=attempt,
            )
        return on_retry

    def _run_pre_sql(self, job: dict, params: dict, job_name: str) -> None:
        for item in job.get("pre_sql", []):
            sql, bind = self._params.apply_to_sql(item["query"], params)
            timer = StepTimer()
            with timer:
                logger.info("Running pre-sql on %s", item["connection"])
                self._execute_with_retry(
                    job, item, job_name, "pre_sql",
                    lambda: self._cm.get(item["connection"]).execute(sql, bind or None),
                    [item["connection"]],
                )
            self._audit.record(
                job_name=job_name, step_name="pre_sql",
                status="success", started_at=timer.started_at,
                finished_at=timer.finished_at, attempt=1,
            )

    def _run_post_sql(self, job: dict, params: dict, job_name: str) -> None:
        for item in job.get("post_sql", []):
            sql, bind = self._params.apply_to_sql(item["query"], params)
            timer = StepTimer()
            with timer:
                logger.info("Running post-sql on %s", item["connection"])
                self._execute_with_retry(
                    job, item, job_name, "post_sql",
                    lambda: self._cm.get(item["connection"]).execute(sql, bind or None),
                    [item["connection"]],
                )
            self._audit.record(
                job_name=job_name, step_name="post_sql",
                status="success", started_at=timer.started_at,
                finished_at=timer.finished_at, attempt=1,
            )

    def _run_steps(self, job: dict, params: dict, job_name: str) -> None:
        for step in job["steps"]:
            step_name = step.get("name", "unnamed")
            logger.info("Running step: %s", step_name)

            timer = StepTimer()
            try:
                with timer:
                    rows_loaded = self._execute_step_with_retry(job, step, params, job_name, step_name)
                logger.info(
                    "Step '%s' complete: %d rows in %.1fs",
                    step_name, rows_loaded, timer.elapsed_seconds,
                )
                self._audit.record(
                    job_name=job_name, step_name=step_name,
                    status="success", rows_affected=rows_loaded,
                    started_at=timer.started_at, finished_at=timer.finished_at,
                    attempt=1,
                )
            except Exception as e:
                logger.error("Step '%s' failed: %s", step_name, e)
                self._audit.record(
                    job_name=job_name, step_name=step_name,
                    status="error", started_at=timer.started_at,
                    finished_at=timer.finished_at, error_message=str(e),
                )
                raise

    def _execute_step(self, step: dict, params: dict) -> int:
        """Execute a single extract→load step. Returns total rows loaded."""
        source = step["source"]
        target = step["target"]
        batch_size = target.get("batch_size", DEFAULT_BATCH_SIZE)

        sql, bind = self._params.apply_to_sql(source["query"], params)

        source_adapter = self._cm.get(source["connection"])
        target_adapter = self._cm.get(target["connection"])

        total_rows = 0
        for batch in source_adapter.fetch_batches(sql, bind or None, batch_size):
            count = target_adapter.insert_batch(target["table"], batch)
            total_rows += count
            logger.debug("Loaded %d rows (total: %d)", count, total_rows)

        return total_rows

    def _execute_step_with_retry(
        self, job: dict, step: dict, params: dict, job_name: str, step_name: str,
    ) -> int:
        """Execute a step, optionally with retry logic."""
        policy = self._get_retry_policy(step, job)
        if policy is None or not policy.is_enabled:
            return self._execute_step(step, params)

        connections = [step["source"]["connection"], step["target"]["connection"]]
        classifier = self._get_classifier(connections[0])
        if classifier is None:
            return self._execute_step(step, params)

        callback = self._make_retry_callback(job_name, step_name, connections)
        executor = RetryExecutor(policy, classifier, on_retry=callback)
        return executor.execute(self._execute_step, step, params)

    def _execute_with_retry(
        self, job: dict, context: dict, job_name: str, step_name: str,
        func, connections: list[str],
    ) -> None:
        """Execute a function, optionally with retry logic."""
        policy = self._get_retry_policy(context, job)
        if policy is None or not policy.is_enabled:
            func()
            return

        classifier = self._get_classifier(connections[0])
        if classifier is None:
            func()
            return

        callback = self._make_retry_callback(job_name, step_name, connections)
        executor = RetryExecutor(policy, classifier, on_retry=callback)
        executor.execute(func)
