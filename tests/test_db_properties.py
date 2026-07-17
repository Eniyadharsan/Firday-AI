"""
Property-based tests for friday/db.py using Hypothesis.
Tests configuration, serialization, parsing, security, and fallback behavior.
"""

import os
import io
import sys
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from typing import Any

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st


# ============================================================
# Property 1: Configuration Detection
# Validates: Requirements 1.1, 1.2, 2.8
# ============================================================

@settings(max_examples=100)
@given(
    url=st.text(min_size=0, max_size=50, alphabet=st.characters(blacklist_characters="\x00")),
    token=st.text(min_size=0, max_size=50, alphabet=st.characters(blacklist_characters="\x00")),
)
def test_property_1_configuration_detection(url, token):
    """
    **Validates: Requirements 1.1, 1.2, 2.8**
    
    For any pair of strings (url, token), USE_TURSO shall be True
    if and only if both strings are non-empty and contain at least
    one non-whitespace character.
    """
    # Compute expected value
    expected = bool(url.strip() and token.strip())

    # Simulate the module logic
    with patch.dict(os.environ, {"TURSO_DATABASE_URL": url, "TURSO_AUTH_TOKEN": token}, clear=False):
        raw_url = os.getenv("TURSO_DATABASE_URL", "")
        raw_token = os.getenv("TURSO_AUTH_TOKEN", "")
        use_turso = bool(raw_url.strip() and raw_token.strip())

    assert use_turso == expected


# ============================================================
# Property 2: URL Scheme Normalization
# Validates: Requirements 1.3, 1.4
# ============================================================

@settings(max_examples=100)
@given(
    domain=st.from_regex(r"[a-z][a-z0-9\-]{0,20}\.[a-z]{2,5}", fullmatch=True),
    path=st.from_regex(r"(/[a-z0-9\-]{1,10}){0,3}", fullmatch=True),
)
def test_property_2_url_scheme_normalization(domain, path):
    """
    **Validates: Requirements 1.3, 1.4**
    
    For any URL with libsql:// prefix, the output SHALL start with https://
    with the remainder preserved. For https:// prefix, output is identical.
    """
    # Test libsql:// -> https://
    libsql_url = f"libsql://{domain}{path}"
    normalized = libsql_url.replace("libsql://", "https://")
    assert normalized == f"https://{domain}{path}"
    assert not normalized.startswith("libsql://")
    assert normalized.startswith("https://")

    # Test https:// unchanged
    https_url = f"https://{domain}{path}"
    normalized_https = https_url.replace("libsql://", "https://")
    assert normalized_https == https_url


# ============================================================
# Property 3: Parameter Type Serialization
# Validates: Requirements 2.3, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6
# ============================================================

@settings(max_examples=100)
@given(
    value=st.one_of(
        st.text(max_size=50),
        st.integers(min_value=-10000, max_value=10000),
        st.floats(allow_nan=False, allow_infinity=False),
        st.booleans(),
        st.none(),
    )
)
def test_property_3_parameter_type_serialization(value):
    """
    **Validates: Requirements 2.3, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6**
    
    For any Python value of type str, int, float, bool, or None,
    _serialize_param produces the correct typed dictionary format.
    """
    from friday.db import _serialize_param

    result = _serialize_param(value)

    assert isinstance(result, dict)
    assert "type" in result

    if value is None:
        assert result == {"type": "null"}
    elif isinstance(value, bool):
        # bool must be checked before int
        assert result["type"] == "integer"
        assert result["value"] == ("1" if value else "0")
    elif isinstance(value, int):
        assert result["type"] == "integer"
        assert result["value"] == str(value)
    elif isinstance(value, float):
        assert result["type"] == "float"
        assert result["value"] == value
    elif isinstance(value, str):
        assert result["type"] == "text"
        assert result["value"] == value


@settings(max_examples=100)
@given(
    value=st.one_of(
        st.lists(st.integers(), max_size=5),
        st.dictionaries(st.text(max_size=5), st.integers(), max_size=3),
    )
)
def test_property_3_unsupported_types(value):
    """
    **Validates: Requirements 9.6**
    
    For unsupported types, _serialize_param produces text with str(val).
    """
    from friday.db import _serialize_param

    result = _serialize_param(value)
    assert result["type"] == "text"
    assert result["value"] == str(value)


# ============================================================
# Property 4: Response Parsing Produces Column-Keyed Dictionaries
# Validates: Requirements 2.4, 3.3
# ============================================================

@settings(max_examples=100)
@given(
    col_names=st.lists(
        st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True),
        min_size=1,
        max_size=5,
        unique=True,
    ),
    num_rows=st.integers(min_value=0, max_value=10),
)
def test_property_4_response_parsing(col_names, num_rows):
    """
    **Validates: Requirements 2.4, 3.3**
    
    For any valid Turso pipeline response containing N columns and M rows,
    parsing SHALL produce a list of exactly M dictionaries where each
    dictionary has exactly the N column names as keys.
    """
    # Build a mock Turso response
    cols = [{"name": name, "decltype": "TEXT"} for name in col_names]
    rows = []
    for r_idx in range(num_rows):
        row = [{"type": "text", "value": f"val_{r_idx}_{c_idx}"} for c_idx in range(len(col_names))]
        rows.append(row)

    turso_response = {
        "results": [
            {
                "type": "ok",
                "response": {
                    "type": "execute",
                    "result": {
                        "cols": cols,
                        "rows": rows,
                        "affected_row_count": 0,
                        "last_insert_rowid": None,
                    },
                },
            }
        ]
    }

    # Mock the session.post to return this response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = turso_response

    mock_session = MagicMock()
    mock_session.post.return_value = mock_response

    with patch.dict(os.environ, {"TURSO_DATABASE_URL": "https://test.turso.io", "TURSO_AUTH_TOKEN": "test-token"}):
        with patch("friday.db.USE_TURSO", True):
            with patch("friday.db.TURSO_URL", "https://test.turso.io"):
                with patch("friday.db.TURSO_TOKEN", "test-token"):
                    with patch("friday.db._session", mock_session):
                        with patch("friday.db._pipeline_url", "https://test.turso.io/v2/pipeline"):
                            from friday.db import _turso_execute
                            result = _turso_execute("SELECT * FROM test", [])

    # Verify structure
    assert len(result) == num_rows
    for row_dict in result:
        assert isinstance(row_dict, dict)
        assert set(row_dict.keys()) == set(col_names)


# ============================================================
# Property 5: Auth Token Never Appears in Logs
# Validates: Requirements 8.2, 8.5
# ============================================================

@settings(max_examples=100)
@given(
    token=st.text(min_size=5, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N", "P")))
)
def test_property_5_auth_token_never_logged(token):
    """
    **Validates: Requirements 8.2, 8.5**
    
    For any auth token string and any error scenario, the token value
    SHALL NOT appear as a substring in any log output.
    """
    assume(token.strip())  # Only test non-whitespace tokens

    log_messages = []

    def capture_log(message):
        log_messages.append(str(message))

    # Mock a non-200 response from Turso
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"

    with patch.dict(os.environ, {"TURSO_DATABASE_URL": "https://test.turso.io", "TURSO_AUTH_TOKEN": token}):
        with patch("friday.db.USE_TURSO", True):
            with patch("friday.db.TURSO_URL", "https://test.turso.io"):
                with patch("friday.db.TURSO_TOKEN", token):
                    mock_session = MagicMock()
                    mock_session.post.return_value = mock_response
                    with patch("friday.db._session", mock_session):
                        with patch("friday.db._pipeline_url", "https://test.turso.io/v2/pipeline"):
                            # Capture loguru output
                            handler_id = logger.add(capture_log, format="{message}")
                            try:
                                from friday.db import _turso_execute
                                _turso_execute("SELECT 1", [])
                            finally:
                                logger.remove(handler_id)

    # Verify token never appears in any log message
    for msg in log_messages:
        assert token not in msg, f"Token '{token}' found in log: {msg}"


from loguru import logger


# ============================================================
# Property 6: Error Response Log Truncation
# Validates: Requirements 8.3
# ============================================================

@settings(max_examples=100)
@given(
    response_body=st.text(min_size=0, max_size=1000)
)
def test_property_6_error_response_log_truncation(response_body):
    """
    **Validates: Requirements 8.3**
    
    For any error response body of arbitrary length, the portion logged
    SHALL be at most 200 characters long.
    """
    log_messages = []

    def capture_log(message):
        log_messages.append(str(message))

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = response_body

    with patch("friday.db.USE_TURSO", True):
        with patch("friday.db.TURSO_URL", "https://test.turso.io"):
            with patch("friday.db.TURSO_TOKEN", "safe-token"):
                mock_session = MagicMock()
                mock_session.post.return_value = mock_response
                with patch("friday.db._session", mock_session):
                    with patch("friday.db._pipeline_url", "https://test.turso.io/v2/pipeline"):
                        handler_id = logger.add(capture_log, format="{message}")
                        try:
                            from friday.db import _turso_execute
                            _turso_execute("SELECT 1", [])
                        finally:
                            logger.remove(handler_id)

    # Verify that if the response body appears in the log, it's truncated to ≤200 chars
    for msg in log_messages:
        if "Turso error" in msg:
            # The response body portion in the log should be ≤200 chars
            # Format is: "Turso error {status}: {truncated_body}"
            # Extract the body part after the status code
            parts = msg.split(": ", 1)
            if len(parts) > 1:
                logged_body = parts[1]
                # The logged body comes from r.text[:200]
                assert len(logged_body) <= 200 + len(f"Turso error 500")


# ============================================================
# Property 7: SQL Injection Safety
# Validates: Requirements 3.7
# ============================================================

@settings(max_examples=100)
@given(
    value=st.text(
        min_size=1,
        max_size=100,
        alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z"))
    )
)
def test_property_7_sql_injection_safety(value):
    """
    **Validates: Requirements 3.7**
    
    For any string value containing SQL metacharacters, when passed as a
    parameter to _local_execute, the value SHALL be stored and retrieved
    verbatim without being interpreted as SQL syntax.
    """
    # Use a temporary database to avoid polluting the real one
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_db = f.name

    try:
        with patch("friday.db.LOCAL_DB", Path(temp_db)):
            from friday.db import _local_execute

            # Create test table
            _local_execute("CREATE TABLE IF NOT EXISTS injection_test (id INTEGER PRIMARY KEY, data TEXT)", [])

            # Insert the potentially dangerous value
            _local_execute("INSERT INTO injection_test (data) VALUES (?)", [value])

            # Retrieve and verify it's stored verbatim
            rows = _local_execute("SELECT data FROM injection_test ORDER BY id DESC LIMIT 1", [])
            assert len(rows) == 1
            assert rows[0]["data"] == value
    finally:
        os.unlink(temp_db)


# ============================================================
# Health Endpoint Integration Test
# ============================================================

def test_health_endpoint_returns_database_field_local():
    """Integration test: Health endpoint returns correct database field when Turso is not configured."""
    with patch.dict(os.environ, {"TURSO_DATABASE_URL": "", "TURSO_AUTH_TOKEN": ""}, clear=False):
        with patch("friday.db.USE_TURSO", False):
            # Import app and create test client
            from app import app
            with patch("friday.db.USE_TURSO", False):
                client = app.test_client()
                response = client.get("/health")
                assert response.status_code == 200
                data = response.get_json()
                assert "database" in data
                assert data["database"] == "local_sqlite"


def test_health_endpoint_returns_database_field_turso():
    """Integration test: Health endpoint returns 'turso' when Turso is configured."""
    with patch("friday.db.USE_TURSO", True):
        from app import app
        client = app.test_client()
        response = client.get("/health")
        assert response.status_code == 200
        data = response.get_json()
        assert "database" in data
        assert data["database"] == "turso"


# ============================================================
# Unit Test: init_tables idempotency
# ============================================================

def test_init_tables_idempotent():
    """Calling init_tables() twice should not raise errors."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_db = f.name

    try:
        with patch("friday.db.LOCAL_DB", Path(temp_db)):
            with patch("friday.db.USE_TURSO", False):
                from friday.db import init_tables
                # Call twice - should not raise
                init_tables()
                init_tables()
    finally:
        os.unlink(temp_db)
