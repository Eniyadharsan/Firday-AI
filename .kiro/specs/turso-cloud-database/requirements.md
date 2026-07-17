# Requirements Document

## Introduction

This feature integrates Turso (cloud-hosted libSQL) as the primary persistent database for the Friday AI Assistant. The current deployment on Vercel uses ephemeral filesystem storage, meaning local SQLite data is lost on every redeploy. By connecting to a Turso cloud database, all user data (accounts, conversations, memories, documents, and plans) persists reliably across deployments and serverless function invocations.

## Glossary

- **Database_Module**: The `friday/db.py` module responsible for executing SQL queries against either Turso or local SQLite
- **Turso_Client**: The HTTP-based client that communicates with the Turso cloud database service via the pipeline API
- **Local_SQLite**: The fallback SQLite database stored at `/tmp/friday-data/friday.db` used when Turso is unavailable
- **Connection_Config**: The set of environment variables (`TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`) required to authenticate with Turso
- **Schema_Initializer**: The component that creates required database tables on application startup
- **Health_Endpoint**: The `/health` API route that reports system status including database connectivity

## Requirements

### Requirement 1: Turso Connection Configuration

**User Story:** As a developer, I want to configure Turso database credentials through environment variables, so that the application connects to the correct cloud database in each deployment environment.

#### Acceptance Criteria

1. WHEN `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` environment variables are both set to non-empty, non-whitespace-only strings, THE Database_Module SHALL use Turso as the primary database backend
2. IF either `TURSO_DATABASE_URL` or `TURSO_AUTH_TOKEN` is missing, empty, or contains only whitespace, THEN THE Database_Module SHALL fall back to Local_SQLite for all queries
3. WHEN `TURSO_DATABASE_URL` begins with the `libsql://` scheme, THE Database_Module SHALL replace `libsql://` with `https://` to form the HTTP API base URL
4. WHEN `TURSO_DATABASE_URL` begins with the `https://` scheme, THE Database_Module SHALL use it directly as the HTTP API base URL without modification
5. IF the Turso HTTP API becomes unreachable at runtime after initial configuration succeeds, THEN THE Database_Module SHALL fall back to Local_SQLite for failing queries and log the error at error severity

### Requirement 2: SQL Execution via Turso HTTP Pipeline API

**User Story:** As a developer, I want the database module to execute SQL statements against Turso using the HTTP pipeline API, so that no native binary dependencies are needed in the serverless environment.

#### Acceptance Criteria

1. WHEN a SQL statement is submitted with zero or more parameters, THE Turso_Client SHALL send a POST request to the `/v2/pipeline` endpoint containing the statement and parameters serialized in the Turso pipeline request format
2. THE Turso_Client SHALL include the `Authorization: Bearer <token>` header and `Content-Type: application/json` header in every request to the Turso HTTP API
3. THE Turso_Client SHALL serialize SQL parameters as typed values where text values use type "text", integer values use type "integer", floating-point values use type "float", null values use type "null", and binary values use type "blob"
4. WHEN the Turso HTTP API returns a 200 status code with a valid response body for a read operation (SELECT, PRAGMA), THE Turso_Client SHALL parse column names and row values into a list of dictionaries keyed by column name
5. WHEN the Turso HTTP API returns a 200 status code for a write operation (INSERT, UPDATE, DELETE, CREATE), THE Turso_Client SHALL return an empty list and consider the operation successful
6. IF the Turso HTTP API returns a non-200 status code, THEN THE Turso_Client SHALL log the error at error severity including the status code and execute the same query against Local_SQLite as a fallback
7. IF the Turso HTTP API request does not receive a response within 10 seconds, THEN THE Turso_Client SHALL log the timeout at error severity and execute the same query against Local_SQLite as a fallback
8. IF the TURSO_DATABASE_URL or TURSO_AUTH_TOKEN environment variable is empty or unset, THEN THE Turso_Client SHALL route all queries to Local_SQLite without attempting HTTP requests

### Requirement 3: Local SQLite Fallback

**User Story:** As a developer, I want the application to fall back to local SQLite when Turso is unreachable, so that the system remains functional during network issues or local development.

#### Acceptance Criteria

1. WHEN Turso is unavailable and a query is executed, THE Database_Module SHALL execute the query against Local_SQLite at `/tmp/friday-data/friday.db`. Turso is considered unavailable when either the Turso connection environment variables are not configured, or the Turso HTTP request returns a non-200 status code, or the request fails due to a network error or exceeds a 10-second timeout.
2. WHEN the local database path `/tmp/friday-data/` does not exist at module initialization, THE Database_Module SHALL create the directory including any missing parent directories before attempting database access.
3. WHEN a SELECT or PRAGMA query is executed locally, THE Database_Module SHALL return results as a list of dictionaries where each dictionary key is the column name and each value is the corresponding row value.
4. WHEN an INSERT, UPDATE, or DELETE query is executed locally, THE Database_Module SHALL commit the transaction and return an empty list.
5. IF a Local_SQLite query fails due to a database error, THEN THE Database_Module SHALL log the error at error severity level and return an empty list without raising an exception to the caller.
6. WHEN Turso is available but a query execution returns a non-200 HTTP status or raises a connection exception, THE Database_Module SHALL fall back to Local_SQLite for that specific query and log the failure at error severity level.
7. WHEN a query with parameters is executed against Local_SQLite, THE Database_Module SHALL pass the parameters to the SQLite engine using parameterized query execution to prevent SQL injection.

### Requirement 4: Schema Initialization

**User Story:** As a developer, I want all required database tables to be created automatically on application startup, so that the database is always ready to use without manual migration.

#### Acceptance Criteria

1. WHEN the application starts, THE Schema_Initializer SHALL create the `users` table with columns: id (TEXT PRIMARY KEY), email (TEXT UNIQUE NOT NULL), name (TEXT NOT NULL), password_hash (TEXT NOT NULL), created_at (TEXT NOT NULL), last_login (TEXT)
2. WHEN the application starts, THE Schema_Initializer SHALL create the `conversations` table with columns: id (INTEGER PRIMARY KEY AUTOINCREMENT), user_id (TEXT NOT NULL), session_id (TEXT NOT NULL), role (TEXT NOT NULL), content (TEXT NOT NULL), timestamp (TEXT NOT NULL)
3. WHEN the application starts, THE Schema_Initializer SHALL create the `memories` table with columns: id (INTEGER PRIMARY KEY AUTOINCREMENT), user_id (TEXT NOT NULL), content (TEXT NOT NULL), category (TEXT DEFAULT 'general'), created_at (TEXT NOT NULL)
4. WHEN the application starts, THE Schema_Initializer SHALL create the `long_memory` table with columns: id (INTEGER PRIMARY KEY AUTOINCREMENT), user_id (TEXT NOT NULL), fact (TEXT NOT NULL), category (TEXT DEFAULT 'general'), source (TEXT DEFAULT 'auto'), created_at (TEXT NOT NULL)
5. WHEN the application starts, THE Schema_Initializer SHALL create the `documents` table with columns: id (TEXT PRIMARY KEY), user_id (TEXT NOT NULL), filename (TEXT NOT NULL), content (TEXT NOT NULL), chunks_count (INTEGER DEFAULT 0), uploaded_at (TEXT NOT NULL)
6. WHEN the application starts, THE Schema_Initializer SHALL create the `chunks` table with columns: id (INTEGER PRIMARY KEY AUTOINCREMENT), doc_id (TEXT NOT NULL), user_id (TEXT NOT NULL), chunk_index (INTEGER NOT NULL), content (TEXT NOT NULL)
7. WHEN the application starts, THE Schema_Initializer SHALL create the `plans` table with columns: id (INTEGER PRIMARY KEY AUTOINCREMENT), user_id (TEXT NOT NULL), title (TEXT NOT NULL), tasks (TEXT NOT NULL), progress (INTEGER DEFAULT 0), created_at (TEXT NOT NULL)
8. THE Schema_Initializer SHALL use `CREATE TABLE IF NOT EXISTS` to avoid errors on subsequent startups and to preserve existing data
9. IF a table creation statement fails, THEN THE Schema_Initializer SHALL log the error at error severity and continue initializing remaining tables
10. WHEN schema initialization completes, THE Schema_Initializer SHALL log whether the Turso or local backend was used

### Requirement 5: Data Persistence Across Deployments

**User Story:** As a user, I want my conversations, memories, and account data to persist when the application is redeployed, so that I do not lose my data.

#### Acceptance Criteria

1. WHEN a user signs up, THE Database_Module SHALL store the user record in Turso so that the record is retrievable by user ID or email after the application is redeployed
2. WHEN a user sends a chat message, THE Database_Module SHALL store the conversation message in Turso so that the full conversation history for that session is retrievable after the application is redeployed
3. WHEN a user creates a memory, THE Database_Module SHALL store the memory in Turso so that the memory is retrievable by user ID after the application is redeployed
4. WHEN a user uploads a document, THE Database_Module SHALL store the document metadata and all its text chunks in Turso so that the document and chunks are retrievable by user ID after the application is redeployed
5. WHEN a user creates a plan, THE Database_Module SHALL store the plan title, tasks, and progress in Turso so that the plan is retrievable by user ID after the application is redeployed
6. WHEN the application starts after a redeployment, THE Database_Module SHALL initialize all required tables (users, conversations, memories, long_memory, documents, chunks, plans) in Turso without deleting existing data
7. IF the Turso database is unreachable during a write operation, THEN THE Database_Module SHALL fall back to Local_SQLite and log the failure at error severity
8. WHEN data is written to Turso, THE Database_Module SHALL ensure the record is queryable within 5 seconds of the write operation completing

### Requirement 6: Insert Operations Support

**User Story:** As a developer, I want a dedicated insert function that handles write operations correctly for both Turso and local backends, so that data mutations are reliable.

#### Acceptance Criteria

1. THE Database_Module SHALL provide an `execute_insert` function that accepts a SQL statement string and an optional list of parameters for INSERT, UPDATE, and DELETE operations
2. WHEN `execute_insert` is called with Turso active, THE Turso_Client SHALL send the mutation via the pipeline API with a 10-second timeout and return an empty list on success
3. WHEN `execute_insert` is called with local fallback active, THE Database_Module SHALL execute the statement against Local_SQLite, commit the transaction, and return an empty list
4. IF an insert operation fails on Turso due to a non-200 status code or network error, THEN THE Database_Module SHALL log the error at error severity and attempt the same operation on Local_SQLite
5. IF the fallback to Local_SQLite also fails, THEN THE Database_Module SHALL log the error at error severity and return an empty list without raising an exception

### Requirement 7: Health Check with Database Status

**User Story:** As a developer, I want the health endpoint to report which database backend is active, so that I can verify Turso connectivity after deployment.

#### Acceptance Criteria

1. WHEN a GET request is made to the `/health` endpoint, THE Health_Endpoint SHALL return a JSON response containing a `database` field with a string value of either `turso` or `local_sqlite`
2. IF both `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` environment variables are set to non-empty strings, THEN THE Health_Endpoint SHALL report `turso` as the `database` field value
3. IF either `TURSO_DATABASE_URL` or `TURSO_AUTH_TOKEN` environment variable is empty or unset, THEN THE Health_Endpoint SHALL report `local_sqlite` as the `database` field value
4. WHEN a GET request is made to the `/health` endpoint, THE Health_Endpoint SHALL return the response within 2 seconds with HTTP status code 200

### Requirement 8: Secure Credential Handling

**User Story:** As a developer, I want database credentials to be handled securely, so that the auth token is not exposed in logs or error messages.

#### Acceptance Criteria

1. THE Database_Module SHALL read `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` exclusively from environment variables at module initialization time
2. THE Database_Module SHALL NOT log the `TURSO_AUTH_TOKEN` value or any substring of it in any log output at any severity level
3. WHEN logging Turso errors, THE Database_Module SHALL truncate response bodies to a maximum of 200 characters to prevent credential leakage in error responses
4. THE Connection_Config SHALL NOT include default or hardcoded credentials for the Turso service; default values SHALL be empty strings
5. IF any API response from Turso contains credentials or tokens in its body, THEN THE Database_Module SHALL NOT log those response portions verbatim

### Requirement 9: Parameter Type Handling

**User Story:** As a developer, I want SQL parameters to be correctly typed when sent to Turso, so that queries execute without type coercion issues.

#### Acceptance Criteria

1. WHEN a parameter value is of Python type `str`, THE Turso_Client SHALL serialize it as `{"type": "text", "value": "<string_value>"}`
2. WHEN a parameter value is of Python type `int`, THE Turso_Client SHALL serialize it as `{"type": "integer", "value": "<integer_as_string>"}`
3. WHEN a parameter value is `None`, THE Turso_Client SHALL serialize it as `{"type": "null"}`
4. WHEN a parameter value is of Python type `float`, THE Turso_Client SHALL serialize it as `{"type": "float", "value": <float_value>}`
5. WHEN a parameter value is of Python type `bool`, THE Turso_Client SHALL serialize it as `{"type": "integer", "value": "1"}` for True and `{"type": "integer", "value": "0"}` for False
6. IF a parameter value is of an unsupported type (not str, int, float, bool, or None), THEN THE Turso_Client SHALL convert it to a string using `str()` and serialize it as type "text"
