/**
 * Shared configuration defaults and constants for the Personal AI Assistant.
 *
 * All values are derived from system requirements and can be overridden
 * via environment variables or runtime configuration where noted.
 */

// --- Hallucination Mitigation (Requirement 5.2) ---

/** Confidence threshold below which a disclaimer is shown (configurable 0.0–1.0) */
export const CONFIDENCE_THRESHOLD: number = 0.7;

/** Minimum confidence score value */
export const CONFIDENCE_MIN: number = 0.0;

/** Maximum confidence score value */
export const CONFIDENCE_MAX: number = 1.0;

// --- RAG Pipeline (Requirement 4.1, 4.2) ---

/** Number of top documents to retrieve from the Knowledge Store (configurable 1–20) */
export const RAG_TOP_K: number = 5;

/** Minimum value for RAG top-k */
export const RAG_TOP_K_MIN: number = 1;

/** Maximum value for RAG top-k */
export const RAG_TOP_K_MAX: number = 20;

/** Similarity score threshold for document relevance (configurable 0.0–1.0) */
export const RAG_RELEVANCE_THRESHOLD: number = 0.7;

/** Minimum value for relevance threshold */
export const RAG_RELEVANCE_THRESHOLD_MIN: number = 0.0;

/** Maximum value for relevance threshold */
export const RAG_RELEVANCE_THRESHOLD_MAX: number = 1.0;

// --- Voice Interface ---

/** Session silence timeout in seconds before session ends */
export const SESSION_SILENCE_TIMEOUT_SECONDS: number = 60;

/** Transcription confidence threshold below which user is asked to repeat */
export const TRANSCRIPTION_CONFIDENCE_THRESHOLD: number = 0.50;

/** Maximum consecutive retry prompts for unrecognized speech */
export const MAX_TRANSCRIPTION_RETRIES: number = 3;

/** Minimum voice speed multiplier */
export const VOICE_SPEED_MIN: number = 0.5;

/** Maximum voice speed multiplier */
export const VOICE_SPEED_MAX: number = 2.0;

/** Minimum voice pitch multiplier */
export const VOICE_PITCH_MIN: number = 0.5;

/** Maximum voice pitch multiplier */
export const VOICE_PITCH_MAX: number = 2.0;

// --- Authentication & Lockout (Requirement 9.6) ---

/** Number of consecutive failed auth attempts before lockout */
export const AUTH_LOCKOUT_ATTEMPTS: number = 5;

/** Time window (in minutes) for counting consecutive failures */
export const AUTH_LOCKOUT_WINDOW_MINUTES: number = 10;

/** Duration (in minutes) to block a source after lockout is triggered */
export const AUTH_LOCKOUT_DURATION_MINUTES: number = 15;

// --- Data Freshness ---

/** Maximum age of fetched data in minutes before it's considered stale */
export const DATA_FRESHNESS_MAX_AGE_MINUTES: number = 15;

// --- Knowledge Store ---

/** Maximum number of stored items per user */
export const KNOWLEDGE_STORE_MAX_ITEMS: number = 500;

// --- Session ---

/** Maximum number of exchanges (user + assistant pairs) retained in a session */
export const SESSION_MAX_EXCHANGES: number = 50;

// --- Task Handling ---

/** Maximum number of subtasks for task decomposition */
export const MAX_SUBTASKS: number = 10;

// --- Timeouts ---

/** LLM generation timeout in seconds */
export const LLM_GENERATION_TIMEOUT_SECONDS: number = 10;

/** Knowledge Store query timeout in seconds */
export const KNOWLEDGE_STORE_TIMEOUT_SECONDS: number = 10;

/** Data Fetcher retrieval timeout in seconds */
export const DATA_FETCH_TIMEOUT_SECONDS: number = 10;

// --- Resource Monitoring (Requirement 8.4) ---

/** Resource usage percentage that triggers an alert */
export const RESOURCE_ALERT_THRESHOLD_PERCENT: number = 80;

// --- Access Logging ---

/** Number of days to retain access logs */
export const ACCESS_LOG_RETENTION_DAYS: number = 90;

// --- Recovery ---

/** Maximum recovery retry attempts on Cloud Server failure */
export const RECOVERY_MAX_RETRIES: number = 3;

// --- Model Fine-Tuning ---

/** Evaluation score threshold that triggers model rollback */
export const MODEL_ROLLBACK_THRESHOLD: number = 0.60;

/** Minimum number of examples required for incremental fine-tuning */
export const FINE_TUNING_MIN_EXAMPLES: number = 50;

/** Minimum LLM context window size in tokens */
export const MIN_CONTEXT_WINDOW_TOKENS: number = 8000;
