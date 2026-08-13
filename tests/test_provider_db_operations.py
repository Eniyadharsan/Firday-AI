"""Unit tests for the multi-provider database schema and operations (spec task 17.2).

Covers the tables/migrations added in friday/db.py:
- provider_configs      (CRUD round-trip)
- provider_metrics      (recording rows, incl. the FK to provider_configs)
- user_provider_prefs   (per-user active provider/model prefs)
- conversations         (provider + model columns added by _add_conversation_provider_columns)

Each test runs against an isolated temp SQLite file with USE_TURSO forced off, so
no cloud I/O happens and the real .friday-data DB is never touched.
"""

from __future__ import annotations

import time
import tempfile
from pathlib import Path

import pytest

import friday.db as db


@pytest.fixture
def temp_db(monkeypatch):
    """Point friday.db at a fresh temp SQLite file and initialize the schema.

    The module keeps a thread-local connection, so we reset it before and after
    to guarantee the temp path is actually used by execute/execute_insert.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = Path(f.name)

    monkeypatch.setattr(db, "USE_TURSO", False)
    monkeypatch.setattr(db, "LOCAL_DB", temp_path)
    # Drop any pooled connection so the new LOCAL_DB path is used.
    if hasattr(db._local_storage, "conn"):
        db._local_storage.conn = None

    db.init_tables()

    yield temp_path

    if hasattr(db._local_storage, "conn"):
        conn = db._local_storage.conn
        if conn is not None:
            conn.close()
        db._local_storage.conn = None
    try:
        temp_path.unlink()
    except OSError:
        pass


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _table_names(_) -> set[str]:
    rows = db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {r["name"] for r in rows}


class TestSchemaExists:
    def test_multi_provider_tables_created(self, temp_db):
        names = _table_names(temp_db)
        assert "provider_configs" in names
        assert "provider_metrics" in names
        assert "user_provider_prefs" in names

    def test_conversations_has_provider_and_model_columns(self, temp_db):
        cols = {row["name"] for row in db.execute("PRAGMA table_info(conversations)")}
        assert "provider" in cols
        assert "model" in cols


class TestProviderConfigsCrud:
    def test_insert_and_select_round_trip(self, temp_db):
        now = _now()
        db.execute_insert(
            "INSERT INTO provider_configs "
            "(provider_type, enabled, default_model, base_url, extra_settings, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ["openai", 1, "gpt-4o", "https://api.openai.com", "{}", now, now],
        )

        rows = db.execute(
            "SELECT * FROM provider_configs WHERE provider_type = ?", ["openai"]
        )
        assert len(rows) == 1
        assert rows[0]["provider_type"] == "openai"
        assert rows[0]["default_model"] == "gpt-4o"
        assert rows[0]["base_url"] == "https://api.openai.com"

    def test_update_config(self, temp_db):
        now = _now()
        db.execute_insert(
            "INSERT INTO provider_configs (provider_type, enabled, default_model, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ["anthropic", 1, "claude-3-5-sonnet", now, now],
        )
        db.execute_insert(
            "UPDATE provider_configs SET default_model = ?, enabled = ? WHERE provider_type = ?",
            ["claude-3-opus", 0, "anthropic"],
        )
        row = db.execute(
            "SELECT default_model, enabled FROM provider_configs WHERE provider_type = ?",
            ["anthropic"],
        )[0]
        assert row["default_model"] == "claude-3-opus"
        assert row["enabled"] == 0

    def test_delete_config(self, temp_db):
        now = _now()
        db.execute_insert(
            "INSERT INTO provider_configs (provider_type, created_at, updated_at) VALUES (?, ?, ?)",
            ["gemini", now, now],
        )
        db.execute_insert("DELETE FROM provider_configs WHERE provider_type = ?", ["gemini"])
        rows = db.execute("SELECT * FROM provider_configs WHERE provider_type = ?", ["gemini"])
        assert rows == []

    def test_provider_type_unique_constraint(self, temp_db):
        now = _now()
        db.execute_insert(
            "INSERT INTO provider_configs (provider_type, created_at, updated_at) VALUES (?, ?, ?)",
            ["ollama", now, now],
        )
        # Duplicate provider_type violates the UNIQUE constraint; the second row
        # must not be inserted (local execute swallows the IntegrityError).
        db.execute_insert(
            "INSERT INTO provider_configs (provider_type, created_at, updated_at) VALUES (?, ?, ?)",
            ["ollama", now, now],
        )
        rows = db.execute("SELECT * FROM provider_configs WHERE provider_type = ?", ["ollama"])
        assert len(rows) == 1


class TestProviderMetricsRecording:
    def test_record_metrics_row(self, temp_db):
        now = _now()
        db.execute_insert(
            "INSERT INTO provider_metrics "
            "(provider_type, total_requests, successful_requests, failed_requests, total_latency_ms, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ["openai", 10, 9, 1, 1234.5, now],
        )
        rows = db.execute("SELECT * FROM provider_metrics WHERE provider_type = ?", ["openai"])
        assert len(rows) == 1
        r = rows[0]
        assert r["total_requests"] == 10
        assert r["successful_requests"] == 9
        assert r["failed_requests"] == 1
        assert float(r["total_latency_ms"]) == pytest.approx(1234.5)

    def test_multiple_metric_records_accumulate(self, temp_db):
        now = _now()
        for i in range(3):
            db.execute_insert(
                "INSERT INTO provider_metrics (provider_type, total_requests, recorded_at) VALUES (?, ?, ?)",
                ["grok", i + 1, now],
            )
        rows = db.execute("SELECT * FROM provider_metrics WHERE provider_type = ?", ["grok"])
        assert len(rows) == 3
        total = db.execute(
            "SELECT SUM(total_requests) AS s FROM provider_metrics WHERE provider_type = ?",
            ["grok"],
        )[0]["s"]
        assert int(total) == 6


class TestUserProviderPrefs:
    def test_insert_and_read_prefs(self, temp_db):
        now = _now()
        db.execute_insert(
            "INSERT INTO user_provider_prefs (user_id, active_provider, active_model, backup_order, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ["user-1", "openai", "gpt-4o", "anthropic,gemini", now],
        )
        row = db.execute("SELECT * FROM user_provider_prefs WHERE user_id = ?", ["user-1"])[0]
        assert row["active_provider"] == "openai"
        assert row["active_model"] == "gpt-4o"
        assert row["backup_order"] == "anthropic,gemini"

    def test_update_prefs_for_existing_user(self, temp_db):
        now = _now()
        db.execute_insert(
            "INSERT INTO user_provider_prefs (user_id, active_provider, active_model, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ["user-2", "openai", "gpt-4o", now],
        )
        db.execute_insert(
            "UPDATE user_provider_prefs SET active_provider = ?, active_model = ? WHERE user_id = ?",
            ["anthropic", "claude-3-5-sonnet", "user-2"],
        )
        row = db.execute("SELECT * FROM user_provider_prefs WHERE user_id = ?", ["user-2"])[0]
        assert row["active_provider"] == "anthropic"
        assert row["active_model"] == "claude-3-5-sonnet"

    def test_user_id_is_primary_key(self, temp_db):
        now = _now()
        db.execute_insert(
            "INSERT INTO user_provider_prefs (user_id, active_provider, updated_at) VALUES (?, ?, ?)",
            ["user-3", "openai", now],
        )
        # Re-inserting the same PK must not create a duplicate row.
        db.execute_insert(
            "INSERT INTO user_provider_prefs (user_id, active_provider, updated_at) VALUES (?, ?, ?)",
            ["user-3", "gemini", now],
        )
        rows = db.execute("SELECT * FROM user_provider_prefs WHERE user_id = ?", ["user-3"])
        assert len(rows) == 1


class TestConversationsProviderColumns:
    def test_insert_conversation_with_provider_and_model(self, temp_db):
        now = _now()
        db.execute_insert(
            "INSERT INTO conversations (user_id, session_id, role, content, timestamp, provider, model) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ["user-1", "sess-1", "assistant", "hello", now, "openai", "gpt-4o"],
        )
        row = db.execute(
            "SELECT provider, model FROM conversations WHERE session_id = ?", ["sess-1"]
        )[0]
        assert row["provider"] == "openai"
        assert row["model"] == "gpt-4o"

    def test_provider_and_model_default_to_null(self, temp_db):
        now = _now()
        db.execute_insert(
            "INSERT INTO conversations (user_id, session_id, role, content, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            ["user-1", "sess-2", "user", "hi", now],
        )
        row = db.execute(
            "SELECT provider, model FROM conversations WHERE session_id = ?", ["sess-2"]
        )[0]
        assert row["provider"] is None
        assert row["model"] is None


class TestMigrationIdempotency:
    def test_add_columns_is_idempotent(self, temp_db):
        # Running the column migration again must not raise or duplicate columns.
        db._add_conversation_provider_columns()
        db._add_conversation_provider_columns()
        cols = [row["name"] for row in db.execute("PRAGMA table_info(conversations)")]
        assert cols.count("provider") == 1
        assert cols.count("model") == 1

    def test_init_tables_idempotent(self, temp_db):
        db.init_tables()
        db.init_tables()
        names = _table_names(temp_db)
        assert {"provider_configs", "provider_metrics", "user_provider_prefs"} <= names
