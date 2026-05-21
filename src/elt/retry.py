import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from elt.errors import ErrorClassifier, ErrorClass

logger = logging.getLogger("elt")

DEFAULT_MAX_ATTEMPTS = 1
DEFAULT_BACKOFF_STRATEGY = "fixed"
DEFAULT_BACKOFF_SECONDS = 5.0
DEFAULT_BACKOFF_MULTIPLIER = 2.0
DEFAULT_MAX_BACKOFF_SECONDS = 300.0

VALID_BACKOFF_STRATEGIES = ("fixed", "exponential")


@dataclass
class RetryPolicy:
    """Describes retry behavior for a step or SQL block."""

    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    backoff_strategy: str = DEFAULT_BACKOFF_STRATEGY
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS
    backoff_multiplier: float = DEFAULT_BACKOFF_MULTIPLIER
    max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RetryPolicy | None":
        """Parse a RetryPolicy from a YAML dict. Returns None if data is None."""
        if data is None:
            return None
        return cls(
            max_attempts=data.get("max_attempts", DEFAULT_MAX_ATTEMPTS),
            backoff_strategy=data.get("backoff_strategy", DEFAULT_BACKOFF_STRATEGY),
            backoff_seconds=data.get("backoff_seconds", DEFAULT_BACKOFF_SECONDS),
            backoff_multiplier=data.get("backoff_multiplier", DEFAULT_BACKOFF_MULTIPLIER),
            max_backoff_seconds=data.get("max_backoff_seconds", DEFAULT_MAX_BACKOFF_SECONDS),
        )

    @property
    def is_enabled(self) -> bool:
        return self.max_attempts > 1

    def calculate_backoff(self, attempt: int) -> float:
        """Calculate backoff delay in seconds for the given attempt (1-indexed)."""
        if self.backoff_strategy == "exponential":
            delay = self.backoff_seconds * (self.backoff_multiplier ** (attempt - 1))
            return min(delay, self.max_backoff_seconds)
        return self.backoff_seconds


def validate_retry_config(config: dict[str, Any]) -> list[str]:
    """Validate a retry config dict. Returns a list of error messages."""
    errors = []
    if "max_attempts" in config and config["max_attempts"] < 1:
        errors.append("retry.max_attempts must be >= 1")
    if "backoff_strategy" in config and config["backoff_strategy"] not in VALID_BACKOFF_STRATEGIES:
        errors.append(f"retry.backoff_strategy must be one of {VALID_BACKOFF_STRATEGIES}")
    if "backoff_seconds" in config and config["backoff_seconds"] <= 0:
        errors.append("retry.backoff_seconds must be > 0")
    if "backoff_multiplier" in config and config["backoff_multiplier"] <= 0:
        errors.append("retry.backoff_multiplier must be > 0")
    if "max_backoff_seconds" in config and config["max_backoff_seconds"] <= 0:
        errors.append("retry.max_backoff_seconds must be > 0")
    return errors


class RetryResult:
    """Carries the return value and the attempt number that succeeded."""

    __slots__ = ("value", "attempt")

    def __init__(self, value: Any, attempt: int):
        self.value = value
        self.attempt = attempt


class RetryExecutor:
    """Wraps a callable with retry logic."""

    def __init__(
        self,
        policy: RetryPolicy,
        classifier: ErrorClassifier,
        on_retry: Callable[[int, Exception, float], None] | None = None,
    ):
        self._policy = policy
        self._classifier = classifier
        self._on_retry = on_retry

    def execute(self, func: Callable, *args, **kwargs) -> RetryResult:
        """Execute func with retry logic according to the policy.

        Returns a RetryResult with the return value and the attempt that succeeded.
        """
        last_exception = None

        for attempt in range(1, self._policy.max_attempts + 1):
            try:
                result = func(*args, **kwargs)
                return RetryResult(result, attempt)
            except Exception as e:
                last_exception = e
                error_class = self._classifier.classify(e)

                if error_class == ErrorClass.PERMANENT:
                    logger.debug("Permanent error, not retrying: %s", e)
                    raise

                if attempt >= self._policy.max_attempts:
                    logger.debug(
                        "Exhausted %d attempts, raising last error: %s",
                        self._policy.max_attempts, e,
                    )
                    raise

                backoff = self._policy.calculate_backoff(attempt)
                logger.info(
                    "Retry attempt %d/%d after TRANSIENT error (%s), waiting %.1fs",
                    attempt + 1, self._policy.max_attempts, e, backoff,
                )

                if self._on_retry:
                    self._on_retry(attempt + 1, e, backoff)

                time.sleep(backoff)

        raise last_exception  # should not reach here
