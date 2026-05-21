import logging
import sys
from pathlib import Path

import click
import yaml

from elt.audit import AuditLogger
from elt.config import discover_jobs, load_connections, load_job
from elt.connections import ConnectionManager
from elt.engine import Engine
from elt.parameters import ParameterResolver
from elt.retry import RetryPolicy

DEFAULT_JOBS_DIR = "jobs"
DEFAULT_CONNECTIONS_FILE = "connections.yaml"
DEFAULT_AUDIT_CONNECTION = "__first__"


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _parse_cli_params(params: tuple[str, ...] | None) -> dict | None:
    if not params:
        return None
    result = {}
    for p in params:
        if "=" not in p:
            raise click.BadParameter(f"Parameter must be key=value, got: {p}")
        key, value = p.split("=", 1)
        if "," in value:
            result[key] = [v.strip() for v in value.split(",")]
        else:
            result[key] = value
    return result


def _build_engine(connections_file: str, audit_connection: str | None) -> tuple[Engine, ConnectionManager]:
    connections_config = load_connections(connections_file)
    cm = ConnectionManager(connections_config)

    audit_conn = audit_connection
    if audit_conn is None or audit_conn == DEFAULT_AUDIT_CONNECTION:
        audit_conn = next(iter(connections_config))

    audit_logger = AuditLogger(cm, audit_conn)
    param_resolver = ParameterResolver(cm)
    engine = Engine(cm, param_resolver, audit_logger)
    return engine, cm


def _format_retry(policy: RetryPolicy) -> str:
    if not policy.is_enabled:
        return "none"
    parts = [f"{policy.max_attempts} attempts"]
    parts.append(f"{policy.backoff_strategy} backoff")
    parts.append(f"{policy.backoff_seconds}s base")
    if policy.backoff_strategy == "exponential":
        parts.append(f"{policy.max_backoff_seconds}s max")
    return ", ".join(parts)


def _show_retry_config(job: dict, echo) -> None:
    job_policy = RetryPolicy.from_dict(job.get("retry"))
    if job_policy and job_policy.is_enabled:
        echo(f"Job retry: {_format_retry(job_policy)}")

    for step in job.get("steps", []):
        step_policy = RetryPolicy.from_dict(step.get("retry"))
        effective = step_policy if step_policy is not None else job_policy
        if effective and effective.is_enabled:
            source = "step" if step_policy is not None else "job default"
            echo(f"  Step '{step.get('name', '?')}' retry ({source}): {_format_retry(effective)}")
        else:
            echo(f"  Step '{step.get('name', '?')}' retry: none")

    for block_name in ("pre_sql", "post_sql"):
        for item in job.get(block_name, []):
            item_policy = RetryPolicy.from_dict(item.get("retry"))
            effective = item_policy if item_policy is not None else job_policy
            if effective and effective.is_enabled:
                source = "item" if item_policy is not None else "job default"
                echo(f"  {block_name} retry ({source}): {_format_retry(effective)}")


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def cli(verbose):
    """ELT Framework - Extract, Load, Transform."""
    _setup_logging(verbose)


@cli.command()
@click.option("--job", "-j", "job_name", required=True, help="Job name to run")
@click.option("--jobs-dir", default=DEFAULT_JOBS_DIR, help="Jobs directory")
@click.option("--connections", "-c", default=DEFAULT_CONNECTIONS_FILE, help="Connections config file")
@click.option("--audit-connection", default=None, help="Connection name for audit table")
@click.option("--param", "-p", "params", multiple=True, help="CLI parameter (key=value or key=v1,v2,v3)")
@click.option("--params-file", type=click.Path(exists=True), help="YAML file with parameter overrides")
@click.option("--dry-run", is_flag=True, help="Show what would run without executing")
def run(job_name, jobs_dir, connections, audit_connection, params, params_file, dry_run):
    """Run an ELT job."""
    logger = logging.getLogger("elt")

    try:
        registry = discover_jobs(jobs_dir)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if job_name not in registry:
        click.echo(f"Job not found: {job_name}", err=True)
        click.echo(f"Available jobs: {', '.join(sorted(registry.keys()))}", err=True)
        sys.exit(1)

    job = load_job(registry[job_name])
    cli_params = _parse_cli_params(params)

    if params_file:
        with open(params_file) as f:
            file_params = yaml.safe_load(f) or {}
        if cli_params:
            file_params.update(cli_params)
        cli_params = file_params

    if dry_run:
        click.echo(f"DRY RUN: {job_name}")
        click.echo(f"Steps: {len(job.get('steps', []))}")
        click.echo(f"Pre-SQL: {len(job.get('pre_sql', []))} statements")
        click.echo(f"Post-SQL: {len(job.get('post_sql', []))} statements")
        click.echo(f"Parameters: {list((job.get('parameters') or {}).keys())}")
        if cli_params:
            click.echo(f"CLI overrides: {list(cli_params.keys())}")
        _show_retry_config(job, click.echo)
        return

    try:
        engine, cm = _build_engine(connections, audit_connection)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    try:
        engine._audit.ensure_table()
        engine.run(job, cli_params)
        click.echo(f"Job '{job_name}' completed successfully.")
    except Exception as e:
        logger.exception("Job execution failed")
        click.echo(f"Job failed: {e}", err=True)
        sys.exit(1)
    finally:
        cm.close_all()


@cli.command()
@click.option("--job", "-j", "job_name", help="Specific job name to validate")
@click.option("--jobs-dir", default=DEFAULT_JOBS_DIR, help="Jobs directory")
@click.option("--connections", "-c", default=DEFAULT_CONNECTIONS_FILE, help="Connections config file")
def validate(job_name, jobs_dir, connections):
    """Validate job configs and connections."""
    try:
        registry = discover_jobs(jobs_dir)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if not registry:
        click.echo("No jobs found.")
        return

    try:
        engine, cm = _build_engine(connections, None)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    try:
        if job_name:
            if job_name not in registry:
                click.echo(f"Job not found: {job_name}", err=True)
                click.echo(f"Available jobs: {', '.join(sorted(registry.keys()))}", err=True)
                sys.exit(1)
            target_jobs = {job_name: registry[job_name]}
        else:
            target_jobs = registry
        all_ok = True
        for name, path in target_jobs.items():
            try:
                job = load_job(path)
                warnings = engine.validate(job)
                if warnings:
                    click.echo(f"  {name}: ISSUES")
                    for w in warnings:
                        click.echo(f"    - {w}")
                    all_ok = False
                else:
                    click.echo(f"  {name}: OK")
            except Exception as e:
                click.echo(f"  {name}: INVALID - {e}")
                all_ok = False

        sys.exit(0 if all_ok else 1)
    finally:
        cm.close_all()
