from elt.adapters.oracle import OracleAdapter

ADAPTER_MAP = {
    "oracle": OracleAdapter,
}


class ConnectionManager:
    """Creates, caches, and manages database adapter instances."""

    def __init__(self, connections_config: dict):
        self._config = connections_config
        self._cache: dict[str, object] = {}

    def get(self, name: str):
        """Return a cached adapter for the named connection, creating it if needed."""
        if name not in self._config:
            raise ValueError(f"Unknown connection: '{name}'")

        if name not in self._cache:
            config = self._config[name]
            adapter_cls = ADAPTER_MAP.get(config["type"])
            if adapter_cls is None:
                raise ValueError(
                    f"Unknown adapter type '{config['type']}' for connection '{name}'"
                )
            adapter = adapter_cls(config)
            adapter.connect()
            self._cache[name] = adapter

        return self._cache[name]

    def close_all(self) -> None:
        """Close all cached connections."""
        for adapter in self._cache.values():
            try:
                adapter.close()
            except Exception:
                pass
        self._cache.clear()
