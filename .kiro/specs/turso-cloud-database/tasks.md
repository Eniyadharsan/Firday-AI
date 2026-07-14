# Tasks

## Task 1: Implement Turso Configuration and URL Normalization

- [x] Add `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` reading from environment variables with empty string defaults in `jarvis/db.py`
- [x] Implement URL scheme normalization: replace `libsql://` with `https://`, leave `https://` unchanged
- [x] Set `USE_TURSO = True` only when both env vars are non-empty and contain non-whitespace characters (use `.strip()` check)
- [x] Ensure no hardcoded or default credentials exist
- [x] Write Property 1 test (Configuration Detection) using Hypothesis in `tests/test_db_properties.py`
- [x] Write Property 2 test (URL Scheme Normalization) using Hypothesis in `tests/test_db_properties.py`

## Task 2: Implement Parameter Type Serialization

- [x] Create `_serialize_param(value)` function that maps Python types to Turso typed value format
- [x] Handle `str` → `{"type": "text", "value": str_value}`
- [x] Handle `int` → `{"type": "integer", "value": str(int_value)}`
- [x] Handle `float` → `{"type": "float", "value": float_value}`
- [x] Handle `None` → `{"type": "null"}`
- [x] Handle `bool` → `{"type": "integer", "value": "1"/"0"}` (must check before int since bool is subclass of int)
- [x] Handle unsupported types → `{"type": "text", "value": str(val)}`
- [x] Write Property 3 test (Parameter Type Serialization) using Hypothesis in `tests/test_db_properties.py`

## Task 3: Implement Turso HTTP Pipeline Execution with Proper Error Handling

- [x] Rewrite `_turso_execute()` to build correct pipeline request format with typed args from `_serialize_param`
- [x] Include `{"type": "close"}` request after the execute request in the pipeline
- [x] Set `Authorization: Bearer <token>` and `Content-Type: application/json` headers
- [x] Set 10-second timeout on `requests.post`
- [x] On non-200 response: log error with status code and truncated body (≤200 chars), fall back to local
- [x] On timeout/connection error: log error without exposing token, fall back to local
- [x] Parse successful response: extract cols and rows into list of dicts for SELECT/PRAGMA
- [x] Return empty list for write operations (INSERT/UPDATE/DELETE/CREATE)
- [x] Write Property 5 test (Auth Token Never Logged) using Hypothesis in `tests/test_db_properties.py`
- [x] Write Property 6 test (Error Response Log Truncation) using Hypothesis in `tests/test_db_properties.py`

## Task 4: Implement Local SQLite Fallback and execute_insert

- [x] Ensure `/tmp/jarvis-data/` directory is created with `mkdir(parents=True, exist_ok=True)` at module init
- [x] Implement `_local_execute()` with parameterized query execution (prevents SQL injection)
- [x] For SELECT/PRAGMA: return list of dicts with column-name keys
- [x] For INSERT/UPDATE/DELETE/CREATE: commit transaction and return empty list
- [x] Catch all sqlite3 errors, log at error severity, return empty list (never raise)
- [x] Implement `execute_insert(sql, params=None)` public function that routes to Turso or local with fallback
- [x] On double failure (Turso + SQLite), log both errors and return empty list
- [x] Write Property 7 test (SQL Injection Safety) using Hypothesis in `tests/test_db_properties.py`

## Task 5: Implement Schema Initialization and Response Parsing

- [x] Implement `init_tables()` using `CREATE TABLE IF NOT EXISTS` for all 7 tables (users, conversations, memories, long_memory, documents, chunks, plans)
- [x] Each table creation wrapped in try/except — log error and continue to next table on failure
- [x] Log which backend was used after initialization completes
- [x] Call `init_tables()` at module import time
- [x] Write Property 4 test (Response Parsing) using Hypothesis in `tests/test_db_properties.py`
- [x] Write unit test for init_tables idempotency in `tests/test_db_properties.py`

## Task 6: Update Health Endpoint and Remove libsql-experimental Dependency

- [x] Update `/health` route in `app.py` to include `"database": "turso" if USE_TURSO else "local_sqlite"` field
- [x] Import `USE_TURSO` from `jarvis.db` in the health endpoint
- [x] Remove `libsql-experimental==0.0.68` from `requirements.txt`
- [x] Add `hypothesis` to `requirements.txt` for property-based testing
- [x] Ensure `requests` is already in requirements.txt (it is)
- [x] Write integration test verifying health endpoint returns correct database field
