"""Unit tests for RetryPolicy parsing, defaults, validation, and inheritance."""
import pytest

from elt.retry import (
    DEFAULT_BACKOFF_MULTIPLIER,
    DEFAULT_BACKOFF_SECONDS,
    DEFAULT_BACKOFF_STRATEGY,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_BACKOFF_SECONDS,
    RetryPolicy,
    validate_retry_config,
)


class TestRetryPolicyDefaults:
    def test_default_values(self):
        policy = RetryPolicy()
        assert policy.max_attempts == DEFAULT_MAX_ATTEMPTS
        assert policy.backoff_strategy == DEFAULT_BACKOFF_STRATEGY
        assert policy.backoff_seconds == DEFAULT_BACKOFF_SECONDS
        assert policy.backoff_multiplier == DEFAULT_BACKOFF_MULTIPLIER
        assert policy.max_backoff_seconds == DEFAULT_MAX_BACKOFF_SECONDS

    def test_not_enabled_by_default(self):
        policy = RetryPolicy()
        assert not policy.is_enabled

    def test_enabled_when_max_attempts_gt_1(self):
        policy = RetryPolicy(max_attempts=3)
        assert policy.is_enabled


class TestRetryPolicyFromDict:
    def test_none_returns_none(self):
        assert RetryPolicy.from_dict(None) is None

    def test_empty_dict_uses_defaults(self):
        policy = RetryPolicy.from_dict({})
        assert policy.max_attempts == DEFAULT_MAX_ATTEMPTS
        assert policy.backoff_strategy == DEFAULT_BACKOFF_STRATEGY

    def test_full_config(self):
        policy = RetryPolicy.from_dict({
            "max_attempts": 5,
            "backoff_strategy": "exponential",
            "backoff_seconds": 2.0,
            "backoff_multiplier": 3.0,
            "max_backoff_seconds": 60.0,
        })
        assert policy.max_attempts == 5
        assert policy.backoff_strategy == "exponential"
        assert policy.backoff_seconds == 2.0
        assert policy.backoff_multiplier == 3.0
        assert policy.max_backoff_seconds == 60.0

    def test_partial_config(self):
        policy = RetryPolicy.from_dict({"max_attempts": 3})
        assert policy.max_attempts == 3
        assert policy.backoff_strategy == DEFAULT_BACKOFF_STRATEGY
        assert policy.backoff_seconds == DEFAULT_BACKOFF_SECONDS

    def test_explicit_disable(self):
        policy = RetryPolicy.from_dict({"max_attempts": 1})
        assert not policy.is_enabled


class TestRetryPolicyBackoff:
    def test_fixed_backoff(self):
        policy = RetryPolicy(backoff_strategy="fixed", backoff_seconds=5.0, jitter=False)
        assert policy.calculate_backoff(1) == 5.0
        assert policy.calculate_backoff(2) == 5.0
        assert policy.calculate_backoff(10) == 5.0

    def test_exponential_backoff(self):
        policy = RetryPolicy(
            backoff_strategy="exponential",
            backoff_seconds=2.0,
            backoff_multiplier=2.0,
            jitter=False,
        )
        assert policy.calculate_backoff(1) == 2.0   # 2 * 2^0
        assert policy.calculate_backoff(2) == 4.0   # 2 * 2^1
        assert policy.calculate_backoff(3) == 8.0   # 2 * 2^2
        assert policy.calculate_backoff(4) == 16.0  # 2 * 2^3

    def test_exponential_respects_max(self):
        policy = RetryPolicy(
            backoff_strategy="exponential",
            backoff_seconds=10.0,
            backoff_multiplier=10.0,
            max_backoff_seconds=60.0,
            jitter=False,
        )
        assert policy.calculate_backoff(1) == 10.0
        assert policy.calculate_backoff(2) == 60.0  # would be 100, capped at 60
        assert policy.calculate_backoff(3) == 60.0  # would be 1000, capped at 60

    def test_exponential_with_multiplier_3(self):
        policy = RetryPolicy(
            backoff_strategy="exponential",
            backoff_seconds=1.0,
            backoff_multiplier=3.0,
            jitter=False,
        )
        assert policy.calculate_backoff(1) == 1.0   # 1 * 3^0
        assert policy.calculate_backoff(2) == 3.0   # 1 * 3^1
        assert policy.calculate_backoff(3) == 9.0   # 1 * 3^2
        assert policy.calculate_backoff(4) == 27.0  # 1 * 3^3


class TestValidateRetryConfig:
    def test_valid_config(self):
        assert validate_retry_config({"max_attempts": 3}) == []

    def test_max_attempts_zero(self):
        errors = validate_retry_config({"max_attempts": 0})
        assert len(errors) == 1
        assert "max_attempts" in errors[0]

    def test_max_attempts_negative(self):
        errors = validate_retry_config({"max_attempts": -1})
        assert len(errors) == 1

    def test_invalid_backoff_strategy(self):
        errors = validate_retry_config({"backoff_strategy": "random"})
        assert len(errors) == 1
        assert "backoff_strategy" in errors[0]

    def test_valid_backoff_strategies(self):
        assert validate_retry_config({"backoff_strategy": "fixed"}) == []
        assert validate_retry_config({"backoff_strategy": "exponential"}) == []

    def test_negative_backoff_seconds(self):
        errors = validate_retry_config({"backoff_seconds": -1})
        assert len(errors) == 1
        assert "backoff_seconds" in errors[0]

    def test_zero_backoff_seconds(self):
        errors = validate_retry_config({"backoff_seconds": 0})
        assert len(errors) == 1

    def test_negative_backoff_multiplier(self):
        errors = validate_retry_config({"backoff_multiplier": -0.5})
        assert len(errors) == 1

    def test_negative_max_backoff(self):
        errors = validate_retry_config({"max_backoff_seconds": -1})
        assert len(errors) == 1

    def test_multiple_errors(self):
        errors = validate_retry_config({
            "max_attempts": 0,
            "backoff_strategy": "bad",
            "backoff_seconds": -1,
        })
        assert len(errors) == 3

    def test_empty_config(self):
        assert validate_retry_config({}) == []


class TestRetryPolicyJitter:
    def test_jitter_within_bounds(self):
        policy = RetryPolicy(backoff_strategy="fixed", backoff_seconds=10.0, jitter=True)
        # Verify 100 samples are all within [9.0, 11.0] and not exactly 10.0
        exact_count = 0
        for _ in range(100):
            val = policy.calculate_backoff(1)
            assert 9.0 <= val <= 11.0
            if val == 10.0:
                exact_count += 1
        assert exact_count < 10, "Should have randomized variation"
