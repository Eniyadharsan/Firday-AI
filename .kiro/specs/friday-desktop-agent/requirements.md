# Requirements Document

## Introduction

FRIDAY Desktop Agent extends the existing FRIDAY assistant so that it can act like a voice-driven personal assistant that executes actions on the user's Windows PC. Today FRIDAY is a Flask web application (`app.py`, deployed on Vercel) with a browser UI (`public/index.html`), voice input through the Web Speech API, and a multi-provider AI engine (`friday/modules/providers/`) with an IntentRouter and tool-calling system (`friday/modules/tool_calling/`). A browser or cloud-hosted web application cannot control the host operating system, so this feature introduces a new local native agent that runs on the user's Windows PC, receives voice-derived intents, and executes only explicitly allow-listed OS actions locally.

The Desktop Agent connects to the FRIDAY UI/backend over a local loopback channel (WebSocket or HTTP bound to localhost) and never exposes an unauthenticated command endpoint to the network. Security, explicit user consent, and least-privilege are first-class concerns throughout. The agent supports launching applications, opening files and folders, web searches, media control, dictation, and window management, plus an opt-in screen-awareness capability that sends captured screen content to a vision-capable provider (Gemini) to describe or act on on-screen context.

This feature deliberately excludes any capability that bypasses operating system security boundaries. Programmatic unlocking of the PC or bypassing the OS lock screen or login is an explicit non-goal. Locking the PC on command is permitted. Storing operating system credentials is out of scope.

## Glossary

- **Desktop_Agent**: The new local native process running on the user's Windows PC with the user's OS permissions, responsible for receiving intents and executing allow-listed OS actions locally.
- **FRIDAY_Backend**: The existing Flask application that hosts the AI engine, IntentRouter, and tool-calling system.
- **FRIDAY_UI**: The existing browser-based user interface that captures voice input and displays FRIDAY responses.
- **Local_Channel**: The loopback communication channel (WebSocket or HTTP bound to `127.0.0.1`) between the FRIDAY_UI/FRIDAY_Backend and the Desktop_Agent.
- **Command_Registry**: The allow-list of explicitly registered, executable actions. Only actions present in the Command_Registry may be executed by the Desktop_Agent.
- **Registered_Command**: A single entry in the Command_Registry describing an allowed action, its parameters, and its risk classification.
- **Intent_Parser**: The component that converts natural-language voice input into a structured command by using the existing AI engine and IntentRouter.
- **Structured_Command**: The machine-readable representation of a user intent, containing a target Registered_Command identifier and validated parameters.
- **Screen_Observer**: The opt-in component that captures screen content and sends it to a vision-capable provider for description or context extraction.
- **Vision_Provider**: The vision-capable AI provider (Gemini) that analyzes captured screen content.
- **Audit_Log**: The local, append-only record of executed commands, their parameters, outcomes, and timestamps.
- **Kill_Switch**: The control that immediately disables the Desktop_Agent, halting command execution and screen observation.
- **Active_Indicator**: The visible on-screen indication that the Desktop_Agent and/or Screen_Observer is currently active.
- **Risky_Action**: A Registered_Command classified as destructive, irreversible, or high-impact, requiring explicit confirmation before execution.
- **Confirmation_Prompt**: The user-facing prompt requesting explicit approval before executing a Risky_Action.
- **User_Authorization**: The explicit, recorded consent granted by the user that enables the Desktop_Agent to execute commands.

## Requirements

### Requirement 1: Local Desktop Agent Process

**User Story:** As a FRIDAY user, I want a local agent running on my Windows PC that connects to the FRIDAY UI, so that voice commands can be executed on my computer.

#### Acceptance Criteria

1. THE Desktop_Agent SHALL run as a local process on Windows using the operating system permissions of the invoking user.
2. WHEN the Desktop_Agent starts, THE Desktop_Agent SHALL bind the Local_Channel to the loopback interface `127.0.0.1` only.
3. THE Desktop_Agent SHALL reject any inbound connection that does not originate from the loopback interface.
4. WHEN the FRIDAY_UI connects to the Desktop_Agent, THE Desktop_Agent SHALL require a per-session authentication token containing at least 128 bits of entropy before accepting any command.
5. IF an inbound request on the Local_Channel does not present a valid session authentication token, THEN THE Desktop_Agent SHALL reject the request and record the rejection in the Audit_Log.
6. THE Desktop_Agent SHALL expire each per-session authentication token no later than 3600 seconds after issuance.
7. IF invalid session authentication tokens are presented more than 5 times within 60 seconds, THEN THE Desktop_Agent SHALL temporarily refuse new connection attempts for at least 60 seconds and record the lockout in the Audit_Log.
8. THE Desktop_Agent SHALL operate on Windows as the first supported operating system.

### Requirement 2: User Authorization and Least Privilege

**User Story:** As a FRIDAY user, I want to explicitly authorize the agent before it can act, so that no action runs on my PC without my consent.

#### Acceptance Criteria

1. WHEN the Desktop_Agent starts for the first time, THE Desktop_Agent SHALL require explicit User_Authorization before executing any command.
2. WHILE User_Authorization is absent, THE Desktop_Agent SHALL decline every command execution request and return an authorization-required status.
3. THE Desktop_Agent SHALL request only the operating system permissions required to execute the Registered_Commands.
4. WHEN User_Authorization is granted, THE Desktop_Agent SHALL record the authorization event, its scope, and its timestamp in the Audit_Log.
5. WHERE the user revokes User_Authorization, THE Desktop_Agent SHALL stop accepting command execution requests within 1 second of the revocation.

### Requirement 3: Command Registry Allow-List

**User Story:** As a FRIDAY user, I want only pre-approved actions to be executable, so that arbitrary or unexpected commands cannot run on my PC.

#### Acceptance Criteria

1. THE Command_Registry SHALL contain the complete set of actions that the Desktop_Agent is permitted to execute.
2. WHEN the Desktop_Agent receives a Structured_Command, THE Desktop_Agent SHALL execute the action only if the referenced Registered_Command exists in the Command_Registry.
3. IF a Structured_Command references an action that is absent from the Command_Registry, THEN THE Desktop_Agent SHALL decline execution and return an unsupported-command status.
4. THE Desktop_Agent SHALL treat arbitrary shell or operating system command strings that are not represented as a Registered_Command as unsupported and decline them.
5. WHEN a Registered_Command is added or modified, THE Command_Registry SHALL record a risk classification of either standard or Risky_Action for that command.
6. IF a Structured_Command supplies parameters that fail validation against the Registered_Command parameter schema, THEN THE Desktop_Agent SHALL decline execution and return a validation-error status.

### Requirement 4: Voice-Driven Command Execution

**User Story:** As a FRIDAY user, I want to speak commands like "open Chrome", so that FRIDAY performs common actions on my PC.

#### Acceptance Criteria

1. WHEN the user issues a voice command that maps to a Registered_Command for launching an application, THE Desktop_Agent SHALL launch the specified application.
2. WHEN the user issues a voice command that maps to a Registered_Command for opening a file or folder, THE Desktop_Agent SHALL open the specified file or folder using the default handler.
3. WHEN the user issues a voice command that maps to a Registered_Command for a web search, THE Desktop_Agent SHALL open the search results for the specified query in the default browser.
4. WHEN the user issues a voice command that maps to a Registered_Command for media control, THE Desktop_Agent SHALL perform the specified media action of play, pause, next, previous, or volume adjustment, WHERE any target volume level is constrained to the inclusive range 0 to 100.
5. WHEN the user issues a voice command that maps to a Registered_Command for dictation, THE Desktop_Agent SHALL type the transcribed text into the active input target.
6. WHEN the user issues a voice command that maps to a Registered_Command for window management, THE Desktop_Agent SHALL perform the specified window action of minimize, maximize, restore, focus, or close.
7. WHEN the user issues a voice command that maps to a Registered_Command for locking the PC, THE Desktop_Agent SHALL lock the operating system session.
8. WHEN a Registered_Command completes execution, THE Desktop_Agent SHALL return an execution-result status indicating success or failure to the FRIDAY_UI.

### Requirement 5: Intent Parsing

**User Story:** As a FRIDAY user, I want natural-language voice commands converted into precise structured actions, so that FRIDAY understands what I mean.

#### Acceptance Criteria

1. WHEN the Intent_Parser receives natural-language voice input, THE Intent_Parser SHALL produce a Structured_Command referencing a Registered_Command and its validated parameters using the existing AI engine and IntentRouter.
2. IF the Intent_Parser cannot map the voice input to any Registered_Command, THEN THE Intent_Parser SHALL return an unrecognized-command status and THE FRIDAY_UI SHALL inform the user that the command was not recognized.
3. IF the Intent_Parser maps the voice input to more than one candidate Registered_Command whose confidence values differ by 0.10 or less, THEN THE Intent_Parser SHALL return an ambiguous-command status listing the candidate commands.
4. WHEN the Intent_Parser returns an ambiguous-command status, THE FRIDAY_UI SHALL prompt the user to select one of the candidate commands before execution.
5. WHEN the Intent_Parser produces a Structured_Command, THE Intent_Parser SHALL include a confidence value in the inclusive range 0.0 to 1.0 for the mapping.

### Requirement 6: Confirmation for Risky Actions

**User Story:** As a FRIDAY user, I want to confirm destructive or risky actions before they run, so that I do not accidentally cause harm.

#### Acceptance Criteria

1. WHEN a Structured_Command references a Risky_Action, THE Desktop_Agent SHALL present a Confirmation_Prompt to the user before execution.
2. WHILE a Confirmation_Prompt is pending, THE Desktop_Agent SHALL withhold execution of the associated Risky_Action.
3. WHEN the user approves a Confirmation_Prompt, THE Desktop_Agent SHALL execute the associated Risky_Action and record the approval in the Audit_Log.
4. IF the user declines a Confirmation_Prompt, THEN THE Desktop_Agent SHALL cancel the associated Risky_Action and record the cancellation in the Audit_Log.
5. IF a Confirmation_Prompt receives no response within 30 seconds, THEN THE Desktop_Agent SHALL cancel the associated Risky_Action and record the timeout in the Audit_Log.

### Requirement 7: Audit Logging

**User Story:** As a FRIDAY user, I want a record of every action the agent takes, so that I can review what FRIDAY did on my PC.

#### Acceptance Criteria

1. WHEN the Desktop_Agent executes a Registered_Command, THE Audit_Log SHALL record the command identifier, parameters, outcome, and timestamp.
2. THE Audit_Log SHALL store entries in an append-only manner that preserves prior entries.
3. WHEN the Desktop_Agent declines a command, THE Audit_Log SHALL record the declined command, the reason, and the timestamp.
4. THE Audit_Log SHALL store its entries locally on the user's PC.
5. WHEN the user requests the command history, THE FRIDAY_UI SHALL display the Audit_Log entries in reverse chronological order.

### Requirement 8: Kill-Switch and Disable

**User Story:** As a FRIDAY user, I want an easy way to immediately stop the agent, so that I can regain control at any time.

#### Acceptance Criteria

1. THE FRIDAY_UI SHALL present a Kill_Switch control that disables the Desktop_Agent.
2. WHEN the user activates the Kill_Switch, THE Desktop_Agent SHALL stop accepting new command execution requests within 1 second.
3. WHEN the user activates the Kill_Switch, THE Desktop_Agent SHALL stop the Screen_Observer within 1 second.
4. WHEN the Kill_Switch is activated, THE Audit_Log SHALL record the kill-switch activation and its timestamp.
5. WHILE the Desktop_Agent is disabled by the Kill_Switch, THE Desktop_Agent SHALL decline every command execution request and return a disabled status.

### Requirement 9: Active-State Indication

**User Story:** As a FRIDAY user, I want a clear visible signal when the agent is active, so that I always know when FRIDAY can act or observe.

#### Acceptance Criteria

1. WHILE the Desktop_Agent is enabled, THE Active_Indicator SHALL be visible on screen.
2. WHILE the Screen_Observer is capturing, THE Active_Indicator SHALL show a distinct observing state.
3. WHEN the Desktop_Agent is disabled, THE Active_Indicator SHALL show a disabled state.
4. WHEN the Desktop_Agent transitions between enabled, observing, and disabled states, THE Active_Indicator SHALL update within 1 second of the transition.

### Requirement 10: Screen Awareness (Opt-In)

**User Story:** As a FRIDAY user, I want FRIDAY to optionally look at my screen, so that it can act on what I am currently doing.

#### Acceptance Criteria

1. WHILE screen awareness is disabled, THE Screen_Observer SHALL NOT capture screen content.
2. WHEN the user enables screen awareness, THE Screen_Observer SHALL require explicit opt-in consent before the first capture.
3. IF the user declines the opt-in consent, THEN THE Screen_Observer SHALL remain disabled and SHALL NOT capture screen content.
4. WHEN the Screen_Observer captures screen content, THE Screen_Observer SHALL send the captured content to the Vision_Provider for description or context extraction.
5. IF the Vision_Provider request fails or returns an error, THEN THE Screen_Observer SHALL discard the captured content, return a vision-unavailable status to the FRIDAY_UI, and record the failure in the Audit_Log.
6. WHILE the Screen_Observer is capturing, THE Active_Indicator SHALL show the observing state.
7. WHEN the user disables screen awareness, THE Screen_Observer SHALL stop capturing within 1 second.
8. WHEN the Screen_Observer sends captured content to the Vision_Provider, THE Audit_Log SHALL record the capture event and its timestamp.
9. THE Screen_Observer SHALL retain captured screen content only for the duration required to obtain the Vision_Provider response, after which THE Screen_Observer SHALL discard the captured content.

### Requirement 11: Network Exposure Protection

**User Story:** As a FRIDAY user, I want assurance that no one on the network can command my PC, so that the agent cannot be exploited remotely.

#### Acceptance Criteria

1. THE Desktop_Agent SHALL bind its command interface exclusively to the loopback interface `127.0.0.1`.
2. IF a command request originates from a non-loopback network address, THEN THE Desktop_Agent SHALL decline the request and record the attempt in the Audit_Log.
3. THE Desktop_Agent SHALL require a valid, unexpired session authentication token on every command request.
4. IF a command request presents an invalid or expired session authentication token, THEN THE Desktop_Agent SHALL decline the request and record the attempt in the Audit_Log.
5. WHEN a session authentication token reaches its expiry, THE Desktop_Agent SHALL invalidate the token and require re-authentication before accepting further commands.

### Requirement 12: Excluded Capabilities (Non-Goals)

**User Story:** As a FRIDAY user, I want dangerous capabilities explicitly excluded, so that FRIDAY cannot bypass my computer's security.

#### Acceptance Criteria

1. THE Desktop_Agent SHALL NOT provide any capability to unlock the PC, bypass the operating system lock screen, or bypass the operating system login.
2. IF a Structured_Command requests unlocking the PC or bypassing the lock screen or login, THEN THE Desktop_Agent SHALL decline the request and record the declined request in the Audit_Log.
3. THE Desktop_Agent SHALL NOT store operating system credentials.
4. THE Command_Registry SHALL exclude any Registered_Command whose purpose is to unlock the PC or bypass operating system authentication.
