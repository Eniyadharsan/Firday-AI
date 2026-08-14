# Implementation Plan: FRIDAY Desktop Agent

## Overview

This plan implements the FRIDAY Desktop Agent as a standalone local Python process plus small additions to the existing Flask backend and browser UI. Work proceeds bottom-up: shared data models first, then the independent enforcement components (token auth, registry, validator, authorization, audit log, state machine), then the loopback server that wires the enforcement gauntlet together, then the OS command executor and confirmation/screen-observer features, then the backend Intent_Parser and client bridge, and finally the UI controls and end-to-end wiring.

The Desktop_Agent is Python (pytest + Hypothesis for property tests, following existing `tests/` conventions). UI-facing pieces use vitest. OS side effects are isolated behind handler seams and mocked in tests.

## Tasks

- [x] 1. Set up desktop agent package structure and core data models
  - Create the `friday/desktop_agent/` package directory with `__init__.py`
  - Implement all immutable dataclasses and enums from the design: `RiskClass`, `CommandStatus`, `AgentState`, `RegisteredCommand`, `StructuredCommand`, `IntentResult`, `SessionToken`, `AuthResult`, `ExecutionResult`, `AuditEntry`, `ConfirmationPrompt`
  - Follow the frozen-dataclass conventions from `friday/modules/tool_calling/models.py`
  - _Requirements: 1.8, 3.5, 4.8, 5.5, 1.4, 1.6_

- [x] 2. Implement session token authentication and rate limiting
  - [x] 2.1 Implement Session Token Authenticator
    - Write `issue_token()` using `secrets.token_urlsafe(32)` (≥128-bit entropy) with `expires_at ≤ issued_at + 3600`
    - Write `validate_token(presented, now)` rejecting missing/invalid/expired tokens
    - Write `register_failure(now)` / `is_locked_out(now)` implementing the >5-failures-in-60s lockout for ≥60s
    - _Requirements: 1.4, 1.5, 1.6, 1.7, 11.3, 11.4, 11.5_

  - [x] 2.2 Write property test for token entropy and uniqueness
    - **Property 2: Session token entropy and uniqueness**
    - **Validates: Requirements 1.4**

  - [x] 2.3 Write property test for token validation and expiry
    - **Property 3: Token validation and expiry**
    - **Validates: Requirements 1.5, 1.6, 11.3, 11.4, 11.5**

  - [x] 2.4 Write property test for lockout after repeated invalid tokens
    - **Property 4: Lockout after repeated invalid tokens**
    - **Validates: Requirements 1.7**

- [x] 3. Implement the Command_Registry allow-list
  - [x] 3.1 Implement Command_Registry and registered command definitions
    - Build the immutable allow-list of `RegisteredCommand` entries (launch app, open path, web search, media control, dictation, window management, lock PC) each with parameter schema and `standard`/`risky` classification
    - Write `lookup(command_id) -> RegisteredCommand | None`
    - Exclude by construction any unlock/bypass command
    - _Requirements: 3.1, 3.2, 3.3, 3.5, 12.1, 12.4_

  - [x] 3.2 Write property test for risk classification invariant
    - **Property 7: Risk classification invariant**
    - **Validates: Requirements 3.5**

  - [x] 3.3 Write property test for registry excludes unlock/bypass capabilities
    - **Property 24: Registry excludes unlock/bypass capabilities**
    - **Validates: Requirements 12.1, 12.4**

  - [x] 3.4 Write unit test for registry contents
    - Assert the registry contains the documented command set and no arbitrary-shell command
    - _Requirements: 3.1, 3.4_

- [x] 4. Implement the Parameter Validator
  - [x] 4.1 Implement parameter schema validation
    - Reuse the approach from `tool_calling/router.py::_validate_parameters` (required fields, string length bounds, enum membership) plus numeric range checks including volume clamped to `[0, 100]`
    - Return a `validation-error` status on failure
    - _Requirements: 3.6, 4.4_

  - [x] 4.2 Write property test for parameter schema validation
    - **Property 8: Parameter schema validation**
    - **Validates: Requirements 3.6**

  - [x] 4.3 Write property test for media volume bounds
    - **Property 10: Media volume is bounded**
    - **Validates: Requirements 4.4**

- [x] 5. Implement the Authorization Manager
  - [x] 5.1 Implement authorization state and gating
    - Hold `User_Authorization` state/scope with `require_authorization()` gate that blocks execution while absent
    - Write `grant(scope, now)` recording the event/scope/timestamp and `revoke(now)` that stops accepting commands within 1s
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 5.2 Write property test for the authorization gate
    - **Property 5: Authorization gate**
    - **Validates: Requirements 2.1, 2.2, 2.4, 2.5**

  - [x] 5.3 Write unit test for revoke timing bound
    - Assert command execution is refused within 1s of revocation using a monotonic clock
    - _Requirements: 2.5_

- [x] 6. Implement the Audit_Log
  - [x] 6.1 Implement append-only local audit log
    - Write `append(entry)` to a local JSON Lines file in the agent data directory that never mutates or removes prior entries
    - Record executions, declines, authorize/revoke, kill-switch, capture, vision-failure, and lockout events with required fields
    - Write `read_reverse_chronological()`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 6.2 Write property test for required audit fields on every outcome
    - **Property 17: Every outcome is audited with required fields**
    - **Validates: Requirements 7.1, 7.3**

  - [x] 6.3 Write property test for append-only audit log
    - **Property 18: Audit log is append-only**
    - **Validates: Requirements 7.2**

  - [x] 6.4 Write property test for reverse-chronological history
    - **Property 19: History is reverse chronological**
    - **Validates: Requirements 7.5**

  - [x] 6.5 Write smoke test for local audit file location
    - Assert the audit file resides in the local data directory
    - _Requirements: 7.4_

- [x] 7. Implement the Agent State Machine
  - [x] 7.1 Implement state machine and kill-switch behavior
    - Model `enabled`/`observing`/`disabled` states with transitions that publish within 1s
    - Enforce disabled behavior: decline all execution requests with a `disabled` status while kill-switched, and record kill-switch activation
    - _Requirements: 8.2, 8.4, 8.5, 9.4_

  - [x] 7.2 Write property test for disabled agent declining all commands
    - **Property 20: Disabled agent declines all commands**
    - **Validates: Requirements 8.2, 8.5**

  - [x] 7.3 Write unit test for kill-switch timing and audit
    - Assert new requests refused within 1s and activation recorded
    - _Requirements: 8.2, 8.4_

- [x] 8. Implement the Command Executor (OS handlers)
  - [x] 8.1 Implement OS command handlers behind seams
    - Dispatch validated commands to handlers: launch app, open file/folder (default handler), web search (default browser), media control incl. volume clamp, dictation into active input, window management, lock PC
    - Wrap `os.startfile`/`subprocess`/`webbrowser`/Win32/keyboard injection behind mockable seams; catch handler exceptions and return a `success`/`failure` execution-result
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

  - [x] 8.2 Write property test for web-search URL construction
    - **Property 9: Web-search URL construction**
    - **Validates: Requirements 4.3**

  - [x] 8.3 Write property test for execution result being success or failure
    - **Property 11: Execution result is success or failure**
    - **Validates: Requirements 4.8**

  - [x] 8.4 Write unit tests for command dispatch to each handler
    - Verify each handler is invoked with a mocked OS seam (launch, open path, dictation, window management, lock)
    - _Requirements: 4.1, 4.2, 4.5, 4.6, 4.7_

- [x] 9. Implement the Local_Channel loopback server and enforcement gauntlet
  - [x] 9.1 Implement loopback server and ordered enforcement gauntlet
    - Bind a listening socket to `127.0.0.1` only and expose command, authorization, kill-switch, screen-awareness, and audit-history endpoints
    - Implement `is_loopback(remote_addr)` gate and the ordered gauntlet: origin → token → enabled → authorization → registry lookup → parameter validation → risk gate → execute + audit, recording every rejection
    - Wire in the token authenticator, authorization manager, registry, validator, state machine, executor, and audit log
    - _Requirements: 1.2, 1.3, 3.2, 3.3, 3.4, 11.1, 11.2, 12.2_

  - [x] 9.2 Write property test for loopback-only origin enforcement
    - **Property 1: Loopback-only origin enforcement**
    - **Validates: Requirements 1.3, 11.1, 11.2**

  - [x] 9.3 Write property test for allow-list enforcement
    - **Property 6: Allow-list enforcement**
    - **Validates: Requirements 3.2, 3.3, 3.4, 12.2**

  - [x] 9.4 Write smoke tests for bind address and process user
    - Assert the command interface is bound to `127.0.0.1`, the process runs under the invoking user, and no credential field is persisted
    - _Requirements: 1.1, 1.2, 1.8, 11.1, 12.3_

- [x] 10. Implement the Confirmation Manager for risky actions
  - [x] 10.1 Implement confirmation flow with timeout
    - For a `Risky_Action`, raise a `Confirmation_Prompt` and withhold execution while pending
    - Resolve on approve (execute + record), decline (cancel + record), or 30s timeout (cancel + record)
    - Integrate the risk gate into the enforcement gauntlet
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 10.2 Write property test for risky action withheld until approved
    - **Property 14: Risky action withheld until approved**
    - **Validates: Requirements 6.1, 6.2**

  - [x] 10.3 Write property test for approval executing and recording
    - **Property 15: Approval executes and records**
    - **Validates: Requirements 6.3**

  - [x] 10.4 Write property test for unapproved risky action never executing
    - **Property 16: Unapproved risky action never executes**
    - **Validates: Requirements 6.4, 6.5**

- [x] 11. Implement the Screen_Observer (opt-in)
  - [x] 11.1 Implement opt-in screen capture and vision lifecycle
    - Keep disabled by default; require explicit opt-in consent before the first capture and never capture while disabled/without consent
    - On capture, send content to the Vision_Provider (reuse the Gemini adapter), record the capture event + timestamp, retain the frame only until the response resolves, then discard
    - On vision failure, discard the frame, return `vision-unavailable`, and record the failure; stop capturing within 1s of disable/kill-switch and drive the observing state
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 8.3_

  - [x] 11.2 Write property test for no screen capture without consent
    - **Property 22: No screen capture without consent**
    - **Validates: Requirements 10.1, 10.2, 10.3**

  - [x] 11.3 Write property test for capture lifecycle and retention
    - **Property 23: Capture lifecycle and retention**
    - **Validates: Requirements 10.5, 10.8, 10.9**

  - [x] 11.4 Write unit test for kill-switch stopping the observer
    - Assert the Screen_Observer stops within 1s on disable/kill-switch and records activation
    - _Requirements: 8.3, 10.7_

- [x] 12. Checkpoint - Ensure all agent-side tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Implement the backend Intent_Parser
  - [x] 13.1 Register desktop tool definitions and implement intent parsing
    - Add desktop tool definitions (launch app, open path, web search, media control, dictation, window management, lock PC) to the existing `IntentRouter`/`ToolRegistry`
    - Implement `parse_intent(text) -> IntentResult` returning a `StructuredCommand` with confidence in `[0.0, 1.0]`, an `unrecognized-command` status when nothing maps, and an `ambiguous-command` status when the top two candidates differ by ≤ 0.10
    - _Requirements: 5.1, 5.2, 5.3, 5.5_

  - [x] 13.2 Write property test for parser output invariants
    - **Property 12: Parser output invariants**
    - **Validates: Requirements 5.1, 5.5**

  - [x] 13.3 Write property test for ambiguity detection threshold
    - **Property 13: Ambiguity detection threshold**
    - **Validates: Requirements 5.3**

  - [x] 13.4 Write unit test for unrecognized command
    - Assert `unrecognized-command` status when the parser finds no candidate
    - _Requirements: 5.2_

- [x] 14. Implement the Desktop Agent client bridge in the backend
  - [x] 14.1 Implement backend-to-agent client bridge
    - Forward a `StructuredCommand` to the Desktop_Agent over the Local_Channel with the current session token
    - Relay `execution-result`, `authorization-required`, `disabled`, `unsupported-command`, `validation-error`, and `ambiguous-command` statuses back to the UI
    - _Requirements: 4.8, 2.2, 8.5, 3.3, 3.6, 5.4_

- [x] 15. Implement FRIDAY_UI controls
  - [x] 15.1 Implement Active_Indicator, Kill_Switch, Confirmation_Prompt, history, and ambiguity prompts
    - Add the Active_Indicator reflecting enabled/observing/disabled, the Kill_Switch control, the Confirmation_Prompt dialog, the Audit_Log history view (reverse chronological), and the ambiguity/unrecognized prompts in `public/index.html`
    - _Requirements: 6.1, 7.5, 8.1, 9.1, 9.2, 9.3, 9.4, 5.4_

  - [x] 15.2 Write property test for state-to-indicator mapping
    - **Property 21: State maps to a distinct indicator**
    - **Validates: Requirements 9.1, 9.2, 9.3, 10.6**

  - [x] 15.3 Write vitest frontend tests for UI controls
    - Test Kill_Switch dispatch, Confirmation_Prompt approve/decline, ambiguity candidate rendering, and history newest-first rendering
    - _Requirements: 6.1, 8.1, 5.4, 7.5_

- [x] 16. Integration and end-to-end wiring
  - [x] 16.1 Wire the full request lifecycle together
    - Connect UI → backend `/chat` → Intent_Parser → client bridge → Desktop_Agent gauntlet → mocked OS handler → execution-result
    - _Requirements: 4.8, 5.1, 2.1_

  - [x] 16.2 Write end-to-end loopback integration test
    - Exercise the full gauntlet with a valid token and authorization through to a mocked OS handler
    - _Requirements: 1.2, 4.8, 11.1_

- [x] 17. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP.
- Each task references specific requirements for traceability.
- Checkpoints ensure incremental validation.
- Property tests (Hypothesis) validate the universal correctness properties P1–P24; each runs ≥100 iterations and is tagged `# Feature: friday-desktop-agent, Property {n}: {text}`.
- Unit, smoke, and vitest tests validate specific behaviors, timing bounds, and UI rendering.
- OS side effects are isolated behind handler seams and mocked in tests.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "3.1", "4.1", "5.1", "6.1", "7.1", "8.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4", "3.2", "3.3", "3.4", "4.2", "4.3", "5.2", "5.3", "6.2", "6.3", "6.4", "6.5", "7.2", "7.3", "8.2", "8.3", "8.4"] },
    { "id": 3, "tasks": ["9.1"] },
    { "id": 4, "tasks": ["9.2", "9.3", "9.4", "10.1", "11.1", "13.1"] },
    { "id": 5, "tasks": ["10.2", "10.3", "10.4", "11.2", "11.3", "11.4", "13.2", "13.3", "13.4", "14.1"] },
    { "id": 6, "tasks": ["15.1"] },
    { "id": 7, "tasks": ["15.2", "15.3", "16.1"] },
    { "id": 8, "tasks": ["16.2"] }
  ]
}
```
