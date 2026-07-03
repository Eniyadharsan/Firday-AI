# Implementation Plan: Personal AI Model (JARVIS-Style Assistant)

## Overview

This implementation plan builds the personal AI assistant system incrementally, starting with core infrastructure and interfaces, then implementing each subsystem (Voice Interface, LLM Engine, RAG Pipeline, Data Fetcher, Confidence Scorer, Session Manager, Knowledge Store), and finally wiring all components together through the Orchestrator. Each task builds on prior steps, ensuring no orphaned code.

## Tasks

- [ ] 1. Set up project structure, core interfaces, and shared types
  - [ ] 1.1 Initialize TypeScript project with Docker Compose scaffold
    - Create project root with `package.json`, `tsconfig.json`, `docker-compose.yml` skeleton
    - Set up directory structure: `src/`, `src/interfaces/`, `src/services/`, `src/models/`, `src/config/`, `tests/`
    - Install core dependencies: `typescript`, `express`, `ioredis`, `fast-check` (dev), `vitest` (dev)
    - _Requirements: 8.1_

  - [ ] 1.2 Define core interfaces and data models
    - Create `src/interfaces/api-gateway.ts` with `APIGateway`, `AuthResult`, `IncomingRequest` interfaces
    - Create `src/interfaces/orchestrator.ts` with `Orchestrator`, `UserQuery`, `AssistantResponse`, `SubTask`, `TaskResult` interfaces
    - Create `src/interfaces/voice-interface.ts` with `VoiceInterface`, `TranscriptionResult`, `VoiceConfig`, `ListeningState` interfaces
    - Create `src/interfaces/llm-engine.ts` with `LLMEngine`, `GenerationRequest`, `GenerationResult`, `ModelHealth` interfaces
    - Create `src/interfaces/rag-pipeline.ts` with `RAGPipeline`, `RetrievalConfig`, `RetrievalResult`, `RetrievedDocument`, `DocumentInput`, `IndexResult` interfaces
    - Create `src/interfaces/data-fetcher.ts` with `DataFetcher`, `DataQuery`, `DataCategory`, `DataFetchResult`, `DataItem` interfaces
    - Create `src/interfaces/confidence-scorer.ts` with `ConfidenceScorer`, `ScoringContext`, `ConfidenceResult`, `ResponseSegment` interfaces
    - Create `src/interfaces/session-manager.ts` with `SessionManager`, `Session`, `Exchange`, `ExchangeMetadata` interfaces
    - Create `src/interfaces/knowledge-store.ts` with `KnowledgeStoreManager`, `KnowledgeItem` interfaces
    - Create `src/models/entities.ts` with `UserProfile`, `ConversationLog`, `AccessLogEntry`, `StoredDocument`, `DocumentChunk`, `ModelVersion`, `TaskExecution`, `SubTaskRecord`, `AlertConfig` data models
    - _Requirements: 1.1–1.6, 2.1–2.6, 3.1–3.6, 4.1–4.7, 5.1–5.5, 6.1–6.7, 7.1–7.6, 8.1–8.7, 9.1–9.7_

  - [ ] 1.3 Create shared configuration and constants module
    - Create `src/config/defaults.ts` with default thresholds: confidence threshold (0.7), RAG top-k (5), relevance threshold (0.7), silence timeout (60s), retry limits, lockout parameters
    - Create `src/config/encryption.ts` with encryption configuration constants (AES-256, TLS 1.3)
    - _Requirements: 5.2, 4.1, 4.2, 8.4, 9.6_

- [ ] 2. Implement API Gateway and Authentication Layer
  - [ ] 2.1 Implement authentication service with API key and lockout logic
    - Create `src/services/api-gateway.ts` implementing `APIGateway` interface
    - Implement API key validation logic
    - Implement failed attempt tracking (in-memory store keyed by source IP with timestamps)
    - Implement lockout logic: block source for 15 minutes after 5 consecutive failures within 10-minute window
    - Implement successful auth resetting the consecutive failure counter
    - Log all authentication attempts (success and failure) to access log
    - _Requirements: 8.5, 8.6, 9.6, 9.4_

  - [ ]* 2.2 Write property test for authentication lockout logic
    - **Property 26: Authentication Lockout Logic**
    - Test with arbitrary sequences of auth attempts with timestamps
    - Verify lockout triggers after exactly 5 consecutive failures within 10 minutes
    - Verify successful attempt resets counter
    - Verify lockout duration is at least 15 minutes
    - **Validates: Requirements 9.6**

  - [ ]* 2.3 Write property test for authentication access control
    - **Property 21: Authentication Access Control**
    - Test with valid and invalid credentials
    - Verify access granted only with valid credentials
    - Verify failed auth produces error response AND log entry
    - **Validates: Requirements 8.5, 8.6**

  - [ ]* 2.4 Write unit tests for API Gateway
    - Test specific lockout edge cases (exactly 5 failures, 4 failures with success reset)
    - Test access log entry format
    - Test TLS configuration setup
    - _Requirements: 8.5, 8.6, 9.4, 9.6_

- [ ] 3. Implement Voice Interface
  - [ ] 3.1 Implement speech-to-text service with Faster-Whisper integration
    - Create `src/services/voice-interface.ts` implementing `VoiceInterface` interface
    - Implement `transcribe()` method wrapping Faster-Whisper (CTranslate2) for STT
    - Return `TranscriptionResult` with text, confidence score, language, and duration
    - Implement confidence check: if confidence < 0.50, return low-confidence indicator
    - _Requirements: 1.1, 1.4_

  - [ ] 3.2 Implement text-to-speech service with Coqui TTS integration
    - Implement `synthesize()` method wrapping Coqui TTS (XTTS v2)
    - Accept `VoiceConfig` with speed (0.5–2.0), pitch (0.5–2.0), and voiceId
    - Validate voice configuration boundaries before synthesis
    - Return audio stream for playback
    - _Requirements: 1.2, 1.5_

  - [ ] 3.3 Implement continuous listening and session inactivity management
    - Implement `startListening()` and `stopListening()` methods
    - Track silence duration; trigger session end notification at 60 seconds of silence
    - Implement retry logic: prompt user to repeat on low confidence, up to 3 consecutive retries
    - After 3 failed retries, inform user speech could not be recognized
    - _Requirements: 1.3, 1.4, 1.6_

  - [ ]* 3.4 Write property test for voice configuration boundary validation
    - **Property 3: Voice Configuration Boundary Validation**
    - Generate random speed, pitch, and voiceId values
    - Verify acceptance for valid ranges and rejection for out-of-range values
    - **Validates: Requirements 1.5**

  - [ ]* 3.5 Write property test for transcription retry state machine
    - **Property 2: Transcription Retry State Machine**
    - Generate sequences of confidence scores
    - Verify retry prompt on each score < 0.50
    - Verify "recognition failed" state after exactly 3 consecutive low-confidence results
    - **Validates: Requirements 1.4**

  - [ ]* 3.6 Write property test for session inactivity timeout
    - **Property 1: Session Inactivity Timeout**
    - Generate arbitrary silence durations
    - Verify session marked inactive at >= 60 seconds, remains active below 60 seconds
    - **Validates: Requirements 1.3, 1.6**

- [ ] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Implement Session Manager
  - [ ] 5.1 Implement session lifecycle management with Redis backing
    - Create `src/services/session-manager.ts` implementing `SessionManager` interface
    - Implement `createSession()` — create new session with unique ID, store in Redis
    - Implement `getSession()` — retrieve session by ID from Redis
    - Implement `addExchange()` — append exchange, enforce 50-exchange rolling window
    - Implement `endSession()` — mark session inactive, confirm termination
    - Track `lastActivityAt` for session inactivity detection
    - _Requirements: 2.1, 2.4, 7.2_

  - [ ] 5.2 Implement session continuity for duplicate wake invocations
    - When a Wake_Invocation is received while a session is active, continue existing session
    - Do not create new session; preserve full history
    - Acknowledge invocation within response
    - _Requirements: 2.6_

  - [ ]* 5.3 Write property test for session history retention invariant
    - **Property 17: Session History Retention Invariant**
    - Generate sessions with N exchanges (varying N from 0 to 100+)
    - Verify at least 50 most recent retained when N > 50; all retained when N <= 50
    - **Validates: Requirements 7.2**

  - [ ]* 5.4 Write property test for session continuity on duplicate invocation
    - **Property 5: Session Continuity on Duplicate Invocation**
    - Simulate active session receiving wake invocations
    - Verify no new session created, history preserved, session count unchanged
    - **Validates: Requirements 2.6**

- [ ] 6. Implement RAG Pipeline and Knowledge Store
  - [ ] 6.1 Implement RAG retrieval with Qdrant vector search
    - Create `src/services/rag-pipeline.ts` implementing `RAGPipeline` interface
    - Implement `retrieve()` method: embed query using sentence-transformers, search Qdrant
    - Filter results by relevance threshold, return top-k sorted by descending score
    - If no documents meet threshold, set `allBelowThreshold: true`
    - Implement 10-second timeout; if exceeded, return timeout error
    - _Requirements: 4.1, 4.2, 4.3, 4.7_

  - [ ] 6.2 Implement document indexing and Knowledge Store management
    - Create `src/services/knowledge-store.ts` implementing `KnowledgeStoreManager` interface
    - Implement document processing: accept text, PDF, HTML formats (up to 50MB)
    - Chunk documents, generate embeddings, store in Qdrant
    - Implement `indexDocument()` with 60-second indexing target for documents <= 10MB
    - Implement `storeItem()` with 500-item capacity limit per user
    - Implement `removeItem()` for item deletion
    - Implement `getItemCount()` for capacity checking
    - _Requirements: 4.4, 4.5, 7.3_

  - [ ]* 6.3 Write property test for RAG retrieval filtering and ranking
    - **Property 10: RAG Retrieval Filtering and Ranking**
    - Generate random document sets with similarity scores, threshold, and k values
    - Verify at most k documents returned, all above threshold, sorted descending
    - Verify "no supporting sources" disclaimer when none meet threshold
    - **Validates: Requirements 4.1, 4.2, 4.3**

  - [ ]* 6.4 Write property test for Knowledge Store capacity enforcement
    - **Property 18: Knowledge Store Capacity Enforcement**
    - Generate sequences of store/delete operations
    - Verify items accepted while count < 500, rejected at 500
    - Verify deletion reduces count by exactly 1
    - **Validates: Requirements 7.3**

- [ ] 7. Implement Data Fetcher
  - [ ] 7.1 Implement real-time data retrieval with source fallback
    - Create `src/services/data-fetcher.ts` implementing `DataFetcher` interface
    - Implement `fetch()` method: query external sources (news, web search, structured data)
    - Filter results by freshness (max 15 minutes old)
    - Implement fallback: on primary source failure, try at least 2 alternatives per category
    - Track failed categories; if all fail, set `allFailed: true` with category list
    - Implement circuit breaker pattern (closed → open after 3 failures → half-open after 30s)
    - _Requirements: 3.1, 3.3, 3.4, 3.5_

  - [ ] 7.2 Implement source verification and citation formatting
    - For each data item, check if corroborated by 2+ independent sources → label "verified"
    - Items from single source → label "unverified"
    - Attach source name and retrieval timestamp to each item
    - Ensure outbound queries contain only search text, no conversation context or personal data
    - _Requirements: 3.2, 3.6, 9.2_

  - [ ]* 7.3 Write property test for data freshness filtering
    - **Property 6: Data Freshness Filtering**
    - Generate data items with various timestamps relative to request time
    - Verify only items within 15 minutes are included; older items excluded
    - **Validates: Requirements 3.1**

  - [ ]* 7.4 Write property test for source verification labeling
    - **Property 9: Source Verification Labeling**
    - Generate data items with varying numbers of corroborating sources
    - Verify "verified" label for 2+ sources, "unverified" for single source
    - **Validates: Requirements 3.6**

  - [ ]* 7.5 Write property test for data fetch fallback and terminal failure
    - **Property 8: Data Fetch Fallback and Terminal Failure**
    - Generate fetch scenarios with varying source availability
    - Verify at least 2 alternative attempts per category before failure
    - Verify error message lists all attempted categories on total failure
    - **Validates: Requirements 3.4, 3.5**

  - [ ]* 7.6 Write property test for data isolation in outbound queries
    - **Property 22: Data Isolation in Outbound Queries**
    - Generate outbound request payloads
    - Verify payload contains only search query text, no conversation context or personal data
    - **Validates: Requirements 9.2**

- [ ] 8. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Implement LLM Inference Engine
  - [ ] 9.1 Implement LLM inference service with vLLM integration
    - Create `src/services/llm-engine.ts` implementing `LLMEngine` interface
    - Implement `generate()` method: send prompt + context + history to vLLM server
    - Enforce 10-second timeout; terminate and return error on timeout
    - Implement `healthCheck()` reporting GPU utilization, VRAM usage, queue depth
    - Implement `getModelVersion()` returning active model version
    - _Requirements: 6.4, 6.5, 6.6_

  - [ ] 9.2 Implement fine-tuning management and model version control
    - Create `src/services/fine-tuning-manager.ts`
    - Implement incremental fine-tuning trigger (when 50+ new examples provided)
    - Track evaluation score on held-out test set
    - Implement rollback logic: if evaluation score < 60% after fine-tuning, revert to previous version
    - Store model versions with metadata (base model, training examples, eval score, status)
    - _Requirements: 6.2, 6.3, 6.7_

  - [ ]* 9.3 Write property test for generation timeout enforcement
    - **Property 14: Generation Timeout Enforcement**
    - Simulate generation requests with varying durations
    - Verify termination and error return for durations > 10 seconds
    - Verify no partial response delivered on timeout
    - **Validates: Requirements 6.6**

  - [ ]* 9.4 Write property test for model rollback decision logic
    - **Property 15: Model Rollback Decision Logic**
    - Generate fine-tuning results with various evaluation scores
    - Verify rollback triggered when score < 60%, new model retained when >= 60%
    - **Validates: Requirements 6.7**

- [ ] 10. Implement Confidence Scorer
  - [ ] 10.1 Implement confidence scoring and response segment labeling
    - Create `src/services/confidence-scorer.ts` implementing `ConfidenceScorer` interface
    - Implement `score()` method: compare response against retrieved documents and fetched data
    - Compute overall confidence score (0.0–1.0) based on evidence support
    - Label each response segment as "retrieved_evidence" or "model_knowledge"
    - Set `needsDisclaimer: true` when overall score < configured threshold (default 0.7)
    - Label unsupported claims as "unverified"
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [ ]* 10.2 Write property test for confidence score validity and threshold disclaimer
    - **Property 12: Confidence Score Validity and Threshold Disclaimer**
    - Generate responses with varying evidence support levels
    - Verify score always in [0.0, 1.0]
    - Verify disclaimer present when score < threshold, absent when >= threshold
    - **Validates: Requirements 5.1, 5.2**

  - [ ]* 10.3 Write property test for response segment source labeling
    - **Property 13: Response Segment Source Labeling**
    - Generate responses with mixed segments
    - Verify every segment labeled with exactly one source basis
    - Verify unsupported segments labeled as "unverified"
    - **Validates: Requirements 5.3, 5.4, 5.5**

- [ ] 11. Implement Orchestrator and Task Decomposition
  - [ ] 11.1 Implement orchestrator core query processing
    - Create `src/services/orchestrator.ts` implementing `Orchestrator` interface
    - Implement `processQuery()`: classify intent, route to appropriate subsystems
    - For factual queries: invoke RAG pipeline, pass context to LLM, score confidence
    - For real-time queries: invoke Data Fetcher, include in LLM context
    - Assemble final `AssistantResponse` with citations, source labels, disclaimers
    - Include RAG citations referencing supporting document IDs for each claim
    - _Requirements: 4.6, 5.1–5.5_

  - [ ] 11.2 Implement multi-step task decomposition and execution
    - Implement `decomposeTask()`: break complex requests into 1–10 subtasks
    - Implement `executeSubTasks()`: run subtasks sequentially, report each outcome
    - On subtask failure: preserve prior results, identify failed step, offer retry/skip
    - Support task categories: information lookup, summarization, scheduling reminders, calculations, creative writing
    - If capability is missing, state what's unavailable and suggest alternatives
    - _Requirements: 7.1, 7.4, 7.5, 7.6_

  - [ ]* 11.3 Write property test for task decomposition bounds
    - **Property 16: Task Decomposition Bounds**
    - Generate complex user requests of varying complexity
    - Verify subtask count always between 1 and 10 inclusive
    - **Validates: Requirements 7.1**

  - [ ]* 11.4 Write property test for subtask failure preservation
    - **Property 19: Subtask Failure Preservation**
    - Generate multi-step task executions with failures at various positions
    - Verify results of completed subtasks (1 through N-1) preserved on failure of subtask N
    - Verify failed subtask correctly identified
    - **Validates: Requirements 7.6**

  - [ ]* 11.5 Write property test for RAG citation inclusion
    - **Property 11: RAG Citation Inclusion**
    - Generate responses to factual queries with RAG-retrieved documents
    - Verify every factual claim references at least one supporting document ID
    - **Validates: Requirements 4.6**

- [ ] 12. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 13. Implement Cloud Infrastructure, Security, and Monitoring
  - [ ] 13.1 Implement resource monitoring and alerting
    - Create `src/services/resource-monitor.ts`
    - Monitor CPU, memory, GPU, and disk utilization
    - Emit alert via configured notification channel when any metric exceeds 80%
    - Deliver alert within 60 seconds of threshold breach
    - Support notification channels: email, webhook, SMS
    - _Requirements: 8.3_

  - [ ] 13.2 Implement data encryption, access control, and privacy enforcement
    - Create `src/services/security.ts`
    - Configure AES-256 encryption at rest for all stored data (conversation logs, vectors, model weights)
    - Configure TLS 1.3 for all in-transit communication
    - Enforce data access restriction: only authenticated user's session can access their data
    - Ensure conversation data not sent to third parties (except search queries to Data Fetcher)
    - Implement data deletion: permanently erase specified data within 24 hours, return confirmation with timestamp
    - Implement training opt-in check: reject training data ingestion if opt-in is false
    - _Requirements: 8.4, 8.5, 9.1, 9.2, 9.3, 9.5, 9.7_

  - [ ] 13.3 Implement access logging and retention
    - Create `src/services/access-logger.ts`
    - Log all authentication attempts (success and failure) with timestamp, source IP, method, result
    - Retain logs for minimum 90 days
    - Reject deletion of log entries younger than 90 days
    - Provide user-accessible query endpoint for access logs
    - _Requirements: 9.4_

  - [ ] 13.4 Implement server health, auto-recovery, and uptime management
    - Create `src/services/health-manager.ts`
    - Implement health check endpoint for all services
    - Implement auto-recovery: on failure, retry up to 3 times, resume within 5 minutes
    - If all recovery attempts fail, notify user of temporary unavailability
    - Track uptime metrics for 99.5% monthly target
    - _Requirements: 2.2, 2.3, 2.5, 8.7_

  - [ ]* 13.5 Write property test for resource alert threshold
    - **Property 20: Resource Alert Threshold**
    - Generate resource utilization values
    - Verify alert emitted when any metric > 80%, no alert at <= 80%
    - **Validates: Requirements 8.3**

  - [ ]* 13.6 Write property test for access log retention
    - **Property 24: Access Log Retention**
    - Generate log entries with various ages
    - Verify entries retained for at least 90 days
    - Verify deletion rejected for entries younger than 90 days
    - **Validates: Requirements 9.4**

  - [ ]* 13.7 Write property test for training opt-in enforcement
    - **Property 25: Training Opt-In Enforcement**
    - Generate training requests with opt-in true/false
    - Verify training proceeds only when opt-in is true, rejected when false
    - **Validates: Requirements 9.5**

  - [ ]* 13.8 Write property test for deletion completeness and confirmation
    - **Property 23: Deletion Completeness and Confirmation**
    - Generate deletion requests for sets of items
    - Verify items no longer queryable after deletion
    - Verify confirmation includes deleted items list and timestamp
    - **Validates: Requirements 9.3**

  - [ ]* 13.9 Write property test for data access authorization
    - **Property 27: Data Access Authorization**
    - Generate access requests from authenticated owner and other sessions
    - Verify access permitted only for authenticated owner, denied for others
    - **Validates: Requirements 9.7**

  - [ ]* 13.10 Write property test for server recovery retry logic
    - **Property 4: Server Recovery Retry Logic**
    - Generate sequences of recovery attempts (success/failure)
    - Verify retry up to 3 times, resume on success, notify on all failures
    - **Validates: Requirements 2.3**

- [ ] 14. Implement Wake Invocation and End-to-End Wiring
  - [ ] 14.1 Implement wake invocation handler and session startup
    - Create `src/services/wake-handler.ts`
    - On Wake_Invocation: authenticate → create/resume session → acknowledge within 3 seconds
    - If session already active, continue existing session (delegate to Session Manager)
    - On session end: confirm termination within 2 seconds, return to idle listening
    - _Requirements: 2.1, 2.4, 2.6_

  - [ ] 14.2 Wire all components through orchestrator end-to-end flow
    - Update `src/services/orchestrator.ts` to integrate all services:
      - Wake → Auth → Session → Voice STT → Intent Classification → RAG/DataFetch → LLM → Confidence → Voice TTS
    - Implement graceful degradation: if RAG unavailable, continue with disclaimer
    - Implement error propagation strategy per design (local recovery first, then escalate)
    - Ensure session preservation across errors
    - _Requirements: 8.1, all requirements integrated_

  - [ ] 14.3 Configure Docker Compose for full deployment
    - Update `docker-compose.yml` with all services: API Gateway, Orchestrator, vLLM, Qdrant, Redis, Faster-Whisper, Coqui TTS
    - Configure GPU allocation for LLM inference
    - Set up persistent volumes for Qdrant, Redis AOF, logs, model weights
    - Configure networking with TLS between services
    - Add health check probes for all containers
    - _Requirements: 8.1, 8.2, 8.4_

  - [ ]* 14.4 Write property test for citation formatting completeness
    - **Property 7: Citation Formatting Completeness**
    - Generate data items included in responses
    - Verify each formatted output contains source name AND retrieval timestamp
    - **Validates: Requirements 3.2**

  - [ ]* 14.5 Write integration tests for end-to-end flow
    - Test full request path: voice input → STT → orchestrator → RAG → LLM → confidence → TTS → voice output
    - Test degraded mode: RAG unavailable, data fetch unavailable
    - Test multi-step task with subtask failure
    - Test session lifecycle: create, multi-turn conversation, inactivity timeout, end
    - _Requirements: 1.1–1.6, 2.1–2.6, 3.1–3.6, 4.1–4.7, 5.1–5.5, 7.1–7.6_

- [ ] 15. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The system uses TypeScript throughout, with Docker Compose for deployment orchestration
- All property tests use `fast-check` library with minimum 100 iterations per test
- Circuit breaker pattern is implemented in Data Fetcher and Knowledge Store for resilience

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["2.1", "3.1", "5.1"] },
    { "id": 3, "tasks": ["2.2", "2.3", "2.4", "3.2", "3.3", "5.2"] },
    { "id": 4, "tasks": ["3.4", "3.5", "3.6", "5.3", "5.4", "6.1", "6.2", "7.1"] },
    { "id": 5, "tasks": ["6.3", "6.4", "7.2"] },
    { "id": 6, "tasks": ["7.3", "7.4", "7.5", "7.6", "9.1"] },
    { "id": 7, "tasks": ["9.2", "10.1"] },
    { "id": 8, "tasks": ["9.3", "9.4", "10.2", "10.3"] },
    { "id": 9, "tasks": ["11.1", "13.1", "13.2", "13.3", "13.4"] },
    { "id": 10, "tasks": ["11.2", "13.5", "13.6", "13.7", "13.8", "13.9", "13.10"] },
    { "id": 11, "tasks": ["11.3", "11.4", "11.5"] },
    { "id": 12, "tasks": ["14.1"] },
    { "id": 13, "tasks": ["14.2", "14.3"] },
    { "id": 14, "tasks": ["14.4", "14.5"] }
  ]
}
```
