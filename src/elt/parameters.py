import re
from typing import Any

from elt.connections import ConnectionManager

_ORACLE_IN_LIMIT = 1000
_PARAM_PATTERN = re.compile(r":(\w+)")


def _quote_value(val) -> str:
    """Quote a value for SQL string interpolation."""
    if isinstance(val, str):
        escaped = val.replace("'", "''")
        return f"'{escaped}'"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, bool):
        return "1" if val else "0"
    return f"'{val}'"


def _expand_list(values: list) -> str:
    """Expand a list into comma-separated, quoted values."""
    return ", ".join(_quote_value(v) for v in values)


def _chunk_list(values: list, chunk_size: int = _ORACLE_IN_LIMIT) -> list[list]:
    """Split a list into chunks respecting Oracle's IN clause limit."""
    return [values[i:i + chunk_size] for i in range(0, len(values), chunk_size)]


def _expand_in_clause(sql: str, param_name: str, values: list) -> str:
    """Expand :param_name in an IN clause, handling Oracle's 1000-item limit."""
    # Find matching column IN ( :param_name ) allowing any whitespace
    pattern = re.compile(
        r"([\w\".]+)\s+in\s*\(\s*:" + re.escape(param_name) + r"\s*\)",
        re.IGNORECASE
    )
    match = pattern.search(sql)

    if match:
        column = match.group(1)
        match_idx = match.start()
        match_end = match.end()

        if len(values) <= _ORACLE_IN_LIMIT:
            expanded = ", ".join(_quote_value(v) for v in values)
            return sql[:match_idx] + f"{column} IN ({expanded})" + sql[match_end:]

        chunks = _chunk_list(values)
        chunk_exprs = [
            f"({', '.join(_quote_value(v) for v in chunk)})"
            for chunk in chunks
        ]
        full_expr = " OR ".join(
            f"{column} IN {expr}" for expr in chunk_exprs
        )
        return sql[:match_idx] + f"({full_expr})" + sql[match_end:]

    # Fallback: just replace the placeholder itself using word boundaries
    placeholder_pattern = re.compile(r":" + re.escape(param_name) + r"\b", re.IGNORECASE)
    placeholder_match = placeholder_pattern.search(sql)
    if placeholder_match:
        placeholder_idx = placeholder_match.start()
        end = placeholder_match.end()
        if len(values) <= _ORACLE_IN_LIMIT:
            expanded = ", ".join(_quote_value(v) for v in values)
            return sql[:placeholder_idx] + f"({expanded})" + sql[end:]

    raise ValueError(f"Cannot find 'IN (:{param_name})' in SQL for list expansion")


def _find_in_column(sql: str, param_name: str) -> str:
    """Extract the column name before 'IN (:param_name)' in the SQL."""
    pattern = re.compile(r"(\w+)\s+IN\s*\(\s*:" + re.escape(param_name) + r"\s*\)", re.IGNORECASE)
    match = pattern.search(sql)
    if match:
        return match.group(1)
    return "COLUMN"


class ParameterResolver:
    """Resolves parameters from static config, CLI overrides, and database queries."""

    def __init__(self, connection_manager: ConnectionManager):
        self._cm = connection_manager

    def resolve(
        self,
        param_defs: dict[str, Any],
        cli_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resolve all parameter definitions into concrete values."""
        resolved = {}

        # First, resolve YAML-defined params
        for name, definition in (param_defs or {}).items():
            if cli_params and name in cli_params:
                resolved[name] = cli_params[name]
                continue

            if isinstance(definition, dict):
                source = definition.get("source", definition.get("type"))
                if source == "query":
                    resolved[name] = self._resolve_query(definition)
                elif source == "static":
                    resolved[name] = definition.get("value")
                else:
                    resolved[name] = definition
            else:
                resolved[name] = definition

        # Add any CLI params not already resolved from YAML definitions
        for name, value in (cli_params or {}).items():
            if name not in resolved:
                resolved[name] = value

        return resolved

    def _resolve_query(self, definition: dict) -> Any:
        """Execute a query to resolve a parameter value."""
        connection_name = definition["connection"]
        sql = definition["query"]
        adapter = self._cm.get(connection_name)

        if "column" in definition:
            rows = adapter.fetch_all(sql)
            return [row[definition["column"]] for row in rows]

        row = adapter.fetch_one(sql)
        if row is None:
            raise ValueError(f"Query returned no results for parameter: {sql}")
        values = list(row.values())
        return values[0] if len(values) == 1 else values

    @staticmethod
    def _find_placeholder(sql: str, name: str) -> str | None:
        """Find the actual placeholder text in SQL, case-insensitive with word boundary."""
        pattern = re.compile(r":" + re.escape(name) + r"\b", re.IGNORECASE)
        match = pattern.search(sql)
        return match.group(0) if match else None

    def apply_to_sql(self, sql: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """
        Apply resolved parameters to SQL.

        List parameters are expanded via string interpolation.
        Scalar parameters are returned as bind variables for the adapter.

        Returns (modified_sql, bind_params).
        """
        bind_params = {}
        modified_sql = sql

        for name, value in params.items():
            placeholder = self._find_placeholder(modified_sql, name)
            if placeholder is None:
                continue

            if isinstance(value, list):
                modified_sql = _expand_in_clause(modified_sql, name, value)
            else:
                # Use the actual placeholder name as it appears in SQL for the bind key
                actual_name = placeholder[1:]  # strip the ':'
                bind_params[actual_name] = value

        return modified_sql, bind_params
