import os
import pytest
from elt.config import _interpolate_env
from elt.errors import OracleErrorClassifier, ErrorClass
from elt.parameters import _expand_in_clause, ParameterResolver
from elt.connections import ConnectionManager

def test_env_interpolation_defaults():
    # If not set, raise error
    if "TEST_ENV_VAR_XYZ" in os.environ:
        del os.environ["TEST_ENV_VAR_XYZ"]
    with pytest.raises(ValueError):
        _interpolate_env("${TEST_ENV_VAR_XYZ}")
        
    # If fallback is provided, use it
    assert _interpolate_env("${TEST_ENV_VAR_XYZ:-my_fallback}") == "my_fallback"
    
    # If set, use env value even if default is provided
    os.environ["TEST_ENV_VAR_XYZ"] = "real_value"
    assert _interpolate_env("${TEST_ENV_VAR_XYZ:-my_fallback}") == "real_value"
    del os.environ["TEST_ENV_VAR_XYZ"]

def test_regex_in_clause_expansion():
    # Whitespace and case variations
    sql = "SELECT * FROM t WHERE id IN (:my_list)"
    expanded = _expand_in_clause(sql, "my_list", [1, 2, 3])
    assert expanded == "SELECT * FROM t WHERE id IN (1, 2, 3)"
    
    sql_space = "SELECT * FROM t WHERE id   in   (  :my_list  )"
    expanded_space = _expand_in_clause(sql_space, "my_list", [1, 2, 3])
    assert expanded_space == "SELECT * FROM t WHERE id   IN (1, 2, 3)"

def test_prefix_placeholder_matching():
    # Verify prefix mismatch bug is solved
    sql = "SELECT * FROM t WHERE filter = :status_filter_id AND original = :status_filter"
    resolver = ParameterResolver(ConnectionManager({}))
    
    # Extracting status_filter should not match status_filter_id!
    placeholder = resolver._find_placeholder(sql, "status_filter")
    assert placeholder == ":status_filter"
    
    # Check that status_filter_id exact matches too
    placeholder_id = resolver._find_placeholder(sql, "status_filter_id")
    assert placeholder_id == ":status_filter_id"

def test_oracle_error_classifier_dpy_and_strings():
    classifier = OracleErrorClassifier()
    
    # ConnectionError/OSError is transient
    assert classifier.classify(ConnectionError("conn")) == ErrorClass.TRANSIENT
    
    # Transient ORA- code in string representation
    exc_ora = Exception("Database failed: ORA-12514: listener does not know service")
    assert classifier.classify(exc_ora) == ErrorClass.TRANSIENT
    
    # Transient DPY- code in string representation
    exc_dpy = Exception("DPY-6001: cannot connect to database")
    assert classifier.classify(exc_dpy) == ErrorClass.TRANSIENT
    
    # Permanent error code
    exc_perm = Exception("ORA-01017: invalid username/password")
    assert classifier.classify(exc_perm) == ErrorClass.PERMANENT
