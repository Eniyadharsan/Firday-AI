/**
 * Wake Invocation Handler Service
 *
 * Handles wake invocation events by authenticating the user, creating or
 * resuming a session, and managing session termination. Coordinates between
 * the API Gateway (auth), Session Manager (session lifecycle), and Voice
 * Interface (listening management).
 *
 * Requirements: 2.1, 2.4, 2.6
 */

import type { APIGateway, IncomingRequest, AuthResult } from '../interfaces/api-gateway.js';
import type { Session } from '../interfaces/session-manager.js';
import type { RedisSessionManager } from './session-manager.js';
import type { VoiceInterfaceService } from './voice-interface.js';

/**
 * Response returned after handling a wake invocation.
 */
export interface WakeResponse {
  /** The active session (new or resumed) */
  session: Session;
  /** Whether an existing session was continued */
  isExisting: boolean;
  /** Whether the invocation was acknowledged within the time constraint */
  acknowledged: boolean;
  /** Timestamp of the acknowledgment */
  timestamp: Date;
}

/**
 * Response returned after handling a session end request.
 */
export interface SessionEndResponse {
  /** Whether session termination was confirmed */
  confirmed: boolean;
  /** The ID of the terminated session */
  sessionId: string;
  /** Timestamp of termination */
  terminatedAt: Date;
}

/**
 * Error result returned when authentication fails during wake invocation.
 */
export interface WakeError {
  /** Error message describing what went wrong */
  error: string;
  /** The authentication result for diagnostic purposes */
  authResult: AuthResult;
}

/**
 * WakeHandler orchestrates the wake invocation flow:
 * 1. Authenticate the incoming request via the API Gateway
 * 2. Create or resume a session via the Session Manager
 * 3. Start listening via the Voice Interface
 * 4. Return acknowledgment within 3 seconds (Requirement 2.1)
 *
 * On session end:
 * 1. End the session via Session Manager
 * 2. Stop listening via Voice Interface
 * 3. Confirm termination within 2 seconds (Requirement 2.4)
 */
export class WakeHandler {
  private readonly apiGateway: APIGateway;
  private readonly sessionManager: RedisSessionManager;
  private readonly voiceInterface: VoiceInterfaceService;

  constructor(
    apiGateway: APIGateway,
    sessionManager: RedisSessionManager,
    voiceInterface: VoiceInterfaceService,
  ) {
    this.apiGateway = apiGateway;
    this.sessionManager = sessionManager;
    this.voiceInterface = voiceInterface;
  }

  /**
   * Handle a wake invocation event.
   *
   * Flow:
   * 1. Authenticate the incoming request
   * 2. If auth fails, return error
   * 3. Delegate to sessionManager.handleWakeInvocation() for create/resume
   * 4. Start listening via voice interface
   * 5. Return WakeResponse with session info and isExisting flag
   *
   * Requirement 2.1: Acknowledge within 3 seconds
   * Requirement 2.6: Continue existing session on duplicate invocation
   */
  async handleWakeInvocation(
    userId: string,
    request: IncomingRequest,
  ): Promise<WakeResponse | WakeError> {
    // Step 1: Authenticate the request
    const authResult = await this.apiGateway.authenticate(request);

    if (!authResult.authenticated) {
      return {
        error: authResult.error ?? 'Authentication failed. Access denied.',
        authResult,
      };
    }

    // Step 2: Create or resume session (handles duplicate invocation per Req 2.6)
    const { session, isExisting } =
      await this.sessionManager.handleWakeInvocation(userId);

    // Step 3: Start listening via voice interface
    this.voiceInterface.startListening(session.id);

    // Step 4: Return acknowledgment
    return {
      session,
      isExisting,
      acknowledged: true,
      timestamp: new Date(),
    };
  }

  /**
   * Handle a session end request.
   *
   * Flow:
   * 1. End the session via session manager
   * 2. Stop listening via voice interface
   * 3. Return confirmation with termination timestamp
   *
   * Requirement 2.4: Confirm termination within 2 seconds
   */
  async handleSessionEnd(
    sessionId: string,
    _userId: string,
  ): Promise<SessionEndResponse> {
    // Step 1: End session via session manager
    await this.sessionManager.endSession(sessionId);

    // Step 2: Stop listening via voice interface
    this.voiceInterface.stopListening(sessionId);

    // Step 3: Return confirmation
    return {
      confirmed: true,
      sessionId,
      terminatedAt: new Date(),
    };
  }
}
