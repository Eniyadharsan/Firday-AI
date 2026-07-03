import { describe, it, expect, beforeEach, vi } from 'vitest';
import { WakeHandler, WakeResponse, WakeError } from '../../src/services/wake-handler.js';
import type { APIGateway, AuthResult, IncomingRequest } from '../../src/interfaces/api-gateway.js';
import type { Session } from '../../src/interfaces/session-manager.js';

/**
 * Unit tests for WakeHandler service.
 *
 * Tests cover:
 * - Successful wake invocation with new session creation
 * - Successful wake invocation continuing an existing session
 * - Authentication failure handling
 * - Session end with confirmation
 * - Voice interface start/stop listening coordination
 *
 * Requirements: 2.1, 2.4, 2.6
 */

// --- Mock Factories ---

function createMockSession(overrides?: Partial<Session>): Session {
  return {
    id: 'session-001',
    userId: 'user-123',
    startedAt: new Date('2024-01-15T10:00:00Z'),
    lastActivityAt: new Date('2024-01-15T10:00:00Z'),
    exchanges: [],
    isActive: true,
    ...overrides,
  };
}

function createMockRequest(overrides?: Partial<IncomingRequest>): IncomingRequest {
  return {
    apiKey: 'valid-api-key',
    sourceIp: '192.168.1.1',
    timestamp: new Date(),
    ...overrides,
  };
}

function createMockApiGateway(authResult?: AuthResult): APIGateway {
  const defaultAuthResult: AuthResult = {
    authenticated: true,
    userId: 'user-123',
    method: 'api_key',
  };

  return {
    authenticate: vi.fn().mockResolvedValue(authResult ?? defaultAuthResult),
    recordFailedAttempt: vi.fn(),
    isBlocked: vi.fn().mockReturnValue(false),
  };
}

function createMockSessionManager(existingSession?: Session) {
  const session = existingSession ?? createMockSession();
  const isExisting = !!existingSession;

  return {
    handleWakeInvocation: vi.fn().mockResolvedValue({ session, isExisting }),
    createSession: vi.fn().mockResolvedValue(session),
    getSession: vi.fn().mockResolvedValue(session),
    addExchange: vi.fn().mockResolvedValue(undefined),
    endSession: vi.fn().mockResolvedValue(undefined),
    getActiveSessionForUser: vi.fn().mockResolvedValue(existingSession ?? null),
  };
}

function createMockVoiceInterface() {
  return {
    startListening: vi.fn(),
    stopListening: vi.fn(),
    transcribe: vi.fn(),
    synthesize: vi.fn(),
    handleSilenceDetected: vi.fn(),
    handleLowConfidence: vi.fn(),
    resetRetryCount: vi.fn(),
    getListeningState: vi.fn(),
  };
}

// --- Helper to check if result is a WakeError ---
function isWakeError(result: WakeResponse | WakeError): result is WakeError {
  return 'error' in result;
}

describe('WakeHandler', () => {
  let wakeHandler: WakeHandler;
  let mockApiGateway: ReturnType<typeof createMockApiGateway>;
  let mockSessionManager: ReturnType<typeof createMockSessionManager>;
  let mockVoiceInterface: ReturnType<typeof createMockVoiceInterface>;

  beforeEach(() => {
    mockApiGateway = createMockApiGateway();
    mockSessionManager = createMockSessionManager();
    mockVoiceInterface = createMockVoiceInterface();

    wakeHandler = new WakeHandler(
      mockApiGateway as unknown as APIGateway,
      mockSessionManager as any,
      mockVoiceInterface as any,
    );
  });

  describe('handleWakeInvocation', () => {
    it('should authenticate the incoming request', async () => {
      const request = createMockRequest();
      await wakeHandler.handleWakeInvocation('user-123', request);

      expect(mockApiGateway.authenticate).toHaveBeenCalledWith(request);
    });

    it('should return error when authentication fails', async () => {
      const failedAuth: AuthResult = {
        authenticated: false,
        userId: null,
        method: 'api_key',
        error: 'Authentication failed. Access denied.',
      };
      mockApiGateway = createMockApiGateway(failedAuth);
      wakeHandler = new WakeHandler(
        mockApiGateway as unknown as APIGateway,
        mockSessionManager as any,
        mockVoiceInterface as any,
      );

      const request = createMockRequest({ apiKey: 'invalid-key' });
      const result = await wakeHandler.handleWakeInvocation('user-123', request);

      expect(isWakeError(result)).toBe(true);
      if (isWakeError(result)) {
        expect(result.error).toBe('Authentication failed. Access denied.');
        expect(result.authResult.authenticated).toBe(false);
      }
    });

    it('should not create/resume session when auth fails', async () => {
      const failedAuth: AuthResult = {
        authenticated: false,
        userId: null,
        method: 'api_key',
        error: 'Invalid API key',
      };
      mockApiGateway = createMockApiGateway(failedAuth);
      wakeHandler = new WakeHandler(
        mockApiGateway as unknown as APIGateway,
        mockSessionManager as any,
        mockVoiceInterface as any,
      );

      const request = createMockRequest({ apiKey: 'bad-key' });
      await wakeHandler.handleWakeInvocation('user-123', request);

      expect(mockSessionManager.handleWakeInvocation).not.toHaveBeenCalled();
    });

    it('should not start listening when auth fails', async () => {
      const failedAuth: AuthResult = {
        authenticated: false,
        userId: null,
        method: 'api_key',
        error: 'Locked out',
      };
      mockApiGateway = createMockApiGateway(failedAuth);
      wakeHandler = new WakeHandler(
        mockApiGateway as unknown as APIGateway,
        mockSessionManager as any,
        mockVoiceInterface as any,
      );

      const request = createMockRequest();
      await wakeHandler.handleWakeInvocation('user-123', request);

      expect(mockVoiceInterface.startListening).not.toHaveBeenCalled();
    });

    it('should delegate to session manager for session creation/resumption', async () => {
      const request = createMockRequest();
      await wakeHandler.handleWakeInvocation('user-123', request);

      expect(mockSessionManager.handleWakeInvocation).toHaveBeenCalledWith('user-123');
    });

    it('should start listening on the session after successful auth', async () => {
      const request = createMockRequest();
      await wakeHandler.handleWakeInvocation('user-123', request);

      expect(mockVoiceInterface.startListening).toHaveBeenCalledWith('session-001');
    });

    it('should return WakeResponse with new session details', async () => {
      const request = createMockRequest();
      const result = await wakeHandler.handleWakeInvocation('user-123', request);

      expect(isWakeError(result)).toBe(false);
      if (!isWakeError(result)) {
        expect(result.session.id).toBe('session-001');
        expect(result.session.userId).toBe('user-123');
        expect(result.isExisting).toBe(false);
        expect(result.acknowledged).toBe(true);
        expect(result.timestamp).toBeInstanceOf(Date);
      }
    });

    it('should return isExisting=true when session already active (Req 2.6)', async () => {
      const existingSession = createMockSession({ id: 'existing-session-id' });
      mockSessionManager = createMockSessionManager(existingSession);
      wakeHandler = new WakeHandler(
        mockApiGateway as unknown as APIGateway,
        mockSessionManager as any,
        mockVoiceInterface as any,
      );

      const request = createMockRequest();
      const result = await wakeHandler.handleWakeInvocation('user-123', request);

      expect(isWakeError(result)).toBe(false);
      if (!isWakeError(result)) {
        expect(result.isExisting).toBe(true);
        expect(result.session.id).toBe('existing-session-id');
      }
    });

    it('should start listening on existing session (Req 2.6)', async () => {
      const existingSession = createMockSession({ id: 'active-session-xyz' });
      mockSessionManager = createMockSessionManager(existingSession);
      wakeHandler = new WakeHandler(
        mockApiGateway as unknown as APIGateway,
        mockSessionManager as any,
        mockVoiceInterface as any,
      );

      const request = createMockRequest();
      await wakeHandler.handleWakeInvocation('user-123', request);

      expect(mockVoiceInterface.startListening).toHaveBeenCalledWith('active-session-xyz');
    });

    it('should return acknowledged=true on successful invocation (Req 2.1)', async () => {
      const request = createMockRequest();
      const result = await wakeHandler.handleWakeInvocation('user-123', request);

      expect(isWakeError(result)).toBe(false);
      if (!isWakeError(result)) {
        expect(result.acknowledged).toBe(true);
      }
    });

    it('should include a timestamp in the response', async () => {
      const before = new Date();
      const request = createMockRequest();
      const result = await wakeHandler.handleWakeInvocation('user-123', request);
      const after = new Date();

      expect(isWakeError(result)).toBe(false);
      if (!isWakeError(result)) {
        expect(result.timestamp.getTime()).toBeGreaterThanOrEqual(before.getTime());
        expect(result.timestamp.getTime()).toBeLessThanOrEqual(after.getTime());
      }
    });

    it('should provide a default error message when authResult.error is undefined', async () => {
      const failedAuth: AuthResult = {
        authenticated: false,
        userId: null,
        method: 'api_key',
      };
      mockApiGateway = createMockApiGateway(failedAuth);
      wakeHandler = new WakeHandler(
        mockApiGateway as unknown as APIGateway,
        mockSessionManager as any,
        mockVoiceInterface as any,
      );

      const request = createMockRequest();
      const result = await wakeHandler.handleWakeInvocation('user-123', request);

      expect(isWakeError(result)).toBe(true);
      if (isWakeError(result)) {
        expect(result.error).toBe('Authentication failed. Access denied.');
      }
    });
  });

  describe('handleSessionEnd', () => {
    it('should end the session via session manager', async () => {
      await wakeHandler.handleSessionEnd('session-001', 'user-123');

      expect(mockSessionManager.endSession).toHaveBeenCalledWith('session-001');
    });

    it('should stop listening via voice interface', async () => {
      await wakeHandler.handleSessionEnd('session-001', 'user-123');

      expect(mockVoiceInterface.stopListening).toHaveBeenCalledWith('session-001');
    });

    it('should return confirmed=true on successful end (Req 2.4)', async () => {
      const result = await wakeHandler.handleSessionEnd('session-001', 'user-123');

      expect(result.confirmed).toBe(true);
    });

    it('should return the correct sessionId in response', async () => {
      const result = await wakeHandler.handleSessionEnd('session-abc', 'user-123');

      expect(result.sessionId).toBe('session-abc');
    });

    it('should return a terminatedAt timestamp', async () => {
      const before = new Date();
      const result = await wakeHandler.handleSessionEnd('session-001', 'user-123');
      const after = new Date();

      expect(result.terminatedAt).toBeInstanceOf(Date);
      expect(result.terminatedAt.getTime()).toBeGreaterThanOrEqual(before.getTime());
      expect(result.terminatedAt.getTime()).toBeLessThanOrEqual(after.getTime());
    });

    it('should propagate errors from session manager endSession', async () => {
      mockSessionManager.endSession.mockRejectedValue(
        new Error('Session not found: bad-id'),
      );

      await expect(
        wakeHandler.handleSessionEnd('bad-id', 'user-123'),
      ).rejects.toThrow('Session not found: bad-id');
    });

    it('should not stop listening if endSession throws', async () => {
      mockSessionManager.endSession.mockRejectedValue(
        new Error('Session not found'),
      );

      try {
        await wakeHandler.handleSessionEnd('bad-id', 'user-123');
      } catch {
        // expected
      }

      expect(mockVoiceInterface.stopListening).not.toHaveBeenCalled();
    });
  });
});
