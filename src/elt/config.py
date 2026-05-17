import os
import re
from pathlib import Path

import yaml


_ENV_PATTERN = re.compile(r"\$\{(\w+)\}")


def _interpolate_env(value: str) -> str:
    """Replace ${VAR} placeholders with environment variable values."""
    def _replace(match):
        var = match.group(1)
        env_val = os.environ.get(var)
        if env_val is None:
            raise ValueError(f"Environment variable {var} is not set")
        return env_val
    return _ENV_PATTERN.sub(_replace, value)


def _interpolate_config(config: dict) -> dict:
    """Recursively interpolate ${VAR} references in config values."""
    result = {}
    for key, value in config.items():
        if isinstance(value, dict):
            result[key] = _interpolate_config(value)
        elif isinstance(value, str):
            result[key] = _interpolate_env(value)
        else:
            result[key] = value
    return result


def load_connections(path: str | Path) -> dict:
    """Load and validate connections.yaml, interpolating env variables."""
    with open(path) as f:
        raw = yaml.safe_load(f)

    if not raw or "connections" not in raw:
        raise ValueError(f"Invalid connections file: {path}")

    connections = {}
    for name, config in raw["connections"].items():
        if "type" not in config:
            raise ValueError(f"Connection '{name}' missing 'type'")
        connections[name] = _interpolate_config(config)

    return connections


def load_job(path: str | Path) -> dict:
    """Load and validate a job YAML file."""
    with open(path) as f:
        job = yaml.safe_load(f)

    if not job:
        raise ValueError(f"Empty job file: {path}")

    if "job_name" not in job:
        raise ValueError(f"Job file missing 'job_name': {path}")

    if "steps" not in job or not job["steps"]:
        raise ValueError(f"Job '{job['job_name']}' has no steps")

    for i, step in enumerate(job["steps"]):
        if "source" not in step:
            raise ValueError(f"Step {i} missing 'source'")
        if "target" not in step:
            raise ValueError(f"Step {i} missing 'target'")
        if "connection" not in step["source"]:
            raise ValueError(f"Step {i} source missing 'connection'")
        if "connection" not in step["target"]:
            raise ValueError(f"Step {i} target missing 'connection'")
        if "query" not in step["source"]:
            raise ValueError(f"Step {i} source missing 'query'")
        if "table" not in step["target"]:
            raise ValueError(f"Step {i} target missing 'table'")

    for sql_block in ("pre_sql", "post_sql"):
        for item in job.get(sql_block, []):
            if "connection" not in item:
                raise ValueError(f"{sql_block} item missing 'connection'")
            if "query" not in item:
                raise ValueError(f"{sql_block} item missing 'query'")

    return job


def discover_jobs(jobs_dir: str | Path) -> dict[str, Path]:
    """Scan jobs directory recursively and return a mapping of job_name -> file path."""
    jobs_dir = Path(jobs_dir)
    if not jobs_dir.is_dir():
        raise ValueError(f"Jobs directory not found: {jobs_dir}")

    registry = {}
    for yaml_file in jobs_dir.rglob("*.yaml"):
        with open(yaml_file) as f:
            raw = yaml.safe_load(f)
        if raw and "job_name" in raw:
            name = raw["job_name"]
            if name in registry:
                raise ValueError(
                    f"Duplicate job name '{name}' found in {registry[name]} and {yaml_file}"
                )
            registry[name] = yaml_file
    return registry
