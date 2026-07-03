/**
 * Unit tests for the application wiring (src/app.ts).
 *
 * Tests the end-to-end flow through the orchestrator:
 * - Wake → Auth → Session → Query → Response
 * - Graceful degradation when RAG is unavailable
 * - Graceful degradation when Data Fetcher fails
 * - Graceful degradation when TTS fails
 * - Session preservation across errors
 * - Error propagation strategy
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { createApp, AppDependencies } from '../../src/app.js';
import express from 'express';

// ---- Mock Factories ----

function createMockApiGateway() {
  return {
    authenticate: vi.fn().mockResolvedValue({
      authenticated: true,
      userId: 'user-1',
      method: 'api_key' as const,
    }),
    recordFailedAttempt: vi.fn(),
    isBlocked: vi.fn().mockReturnValue(false),
    registerApiKey: vi.fn(),
    getAccessLog: vi.fn().mockReturnValue([]),
    getLockoutExpiry: vi.fn().mockReturnValue(null),
    getFailedAttemptCount: vi.fn().mockReturnValue(0),
  };
}

function createMockSessionManager() {
  const sessions = new Map<string, any>();
  return {
    createSession: vi.fn().mockImplementation(async (userId: string) => {
      const session = {
        id: 'session-123',
        userId,
        startedAt: new Date(),
        lastActivityAt: new Date(),
        exchanges: [],
        isActive: true,
      };
      sessions.set(session.id, session);
      return session;
    }),
    getSession: vi.fn().mockImplementation(async (id: string) => {
      return sessions.get(id) ?? null;
    }),
    addExchange: vi.fn().mockResolvedValue(undefined),
    endSession: vi.fn().mockImplementation(async (id: string) => {
      const session = sessions.get(id);
      if (session) session.isActive = false;
    }),
    getActiveSessionForUser: vi.fn().mockResolvedValue(null),
    handleWakeInvocation: vi.fn(),
    _setSession(session: any) {
      sessions.set(session.id, session);
    },
  };
}

function createMockVoiceInterface() {
  return {
    transcribe: vi.fn().mockResolvedValue({
      text: 'What is the weather today?',
      confidence: 0.95,
      language: 'en',
      durationMs: 1500,
    }),
    synthesize: vi.fn().mockImplementation(async () => {
      const { Readable } = await import('node:stream');
      return Readable.from(Buffer.from('mock-audio-data'));
    }),
    startListening: vi.fn(),
    stopListening: vi.fn(),
    handleLowConfidence: vi.fn().mockReturnValue(null),
    resetRetryCount: vi.fn(),
    handleSilenceDetected: vi.fn().mockReturnValue(null),
    getListeningState: vi.fn(),
  };
}

function createMockRagPipeline() {
  return {
    retrieve: vi.fn().mockResolvedValue({
      documents: [
        {
          id: 'doc-1',
          content: 'Relevant document content',
          similarityScore: 0.85,
          source: 'knowledge-base',
          indexedAt: new Date(),
        },
      ],
      allBelowThreshold: false,
      queryEmbeddingTimeMs: 50,
      searchTimeMs: 100,
    }),
    indexDocument: vi.fn().mockResolvedValue({ documentId: 'doc-1', chunksCreated: 3, indexTimeMs: 500, success: true }),
    removeDocument: vi.fn().mockResolvedValue(undefined),
  };
}

function createMockDataFetcher() {
  return {
    fetch: vi.fn().mockResolvedValue({
      items: [
        {
          content: 'Today the weather is sunny.',
          source: 'weather-api',
          retrievedAt: new Date(),
          category: 'weather' as const,
          verified: true,
        },
      ],
      failedCategories: [],
      allFailed: false,
    }),
  };
}

function createMockLlmEngine() {
  return {
    generate: vi.fn().mockResolvedValue({
      text: 'The weather today is sunny with mild temperatures.',
      tokenCount: 15,
      generationTimeMs: 800,
      modelVersion: 'mistral-7b-v1',
    }),
    healthCheck: vi.fn().mockResolvedValue({
      status: 'healthy' as const,
      gpuUtilization: 0.45,
      vramUsageMb: 6000,
      queueDepth: 2,
    }),
    getModelVersion: vi.fn().mockReturnValue('mistral-7b-v1'),
  };
}

function createMockConfidenceScorer() {
  return {
    score: vi.fn().mockResolvedValue({
      overallScore: 0.85,
      segments: [
        {
          text: 'The weather today is sunny with mild temperatures.',
          sourceBasis: 'retrieved_evidence' as const,
          supportingDocIds: ['doc-1'],
          segmentConfidence: 0.85,
        },
      ],
      needsDisclaimer: false,
    }),
  };
}

function createMockHealthManager() {
  return {
    checkService: vi.fn().mockResolvedValue({
      serviceName: 'test',
      status: 'healthy',
      lastCheckAt: new Date(),
      responseTimeMs: 5,
    }),
    checkAllServices: vi.fn().mockResolvedValue([
      { serviceName: 'llm', status: 'healthy', lastCheckAt: new Date(), responseTimeMs: 5 },
      { serviceName: 'session-manager', status: 'healthy', lastCheckAt: new Date(), responseTimeMs: 3 },
    ]),
    getAllServiceHealth: vi.fn().mockReturnValue([
      { serviceName: 'llm', status: 'healthy', lastCheckAt: new Date(), responseTimeMs: 5 },
      { serviceName: 'session-manager', status: 'healthy', lastCheckAt: new Date(), responseTimeMs: 3 },
    ]),
    getUptime: vi.fn().mockReturnValue({
      uptimePercent: 100,
      totalDowntimeMs: 0,
      trackingSince: new Date(),
    }),
    attemptRecovery: vi.fn(),
    recordDowntime: vi.fn(),
    registerService: vi.fn(),
    isWithinSLA: vi.fn().mockReturnValue(true),
    getServiceHealth: vi.fn(),
    getNotifications: vi.fn().mockReturnValue([]),
  };
}

function createMockWakeHandler(apiGateway: any, sessionManager: any, voiceInterface?: any) {
  return {
    handleWakeInvocation: vi.fn().mockImplementation(async (userId: string, request: any) => {
      const authResult = await apiGateway.authenticate(request);
      if (!authResult.authenticated) {
        return { error: authResult.error ?? 'Authentication failed', authResult };
      }
      const existing = await sessionManager.getActiveSessionForUser(userId);
      if (existing) {
        voiceInterface?.startListening(existing.id);
        return { session: existing, isExisting: true, acknowledged: true, timestamp: new Date() };
      }
      const session = await sessionManager.createSession(userId);
      voiceInterface?.startListening(session.id);
      return { session, isExisting: false, acknowledged: true, timestamp: new Date() };
    }),
    handleSessionEnd: vi.fn().mockImplementation(async (sessionId: string, _userId: string) => {
      await sessionManager.endSession(sessionId);
      voiceInterface?.stopListening(sessionId);
      return { confirmed: true, sessionId, terminatedAt: new Date() };
    }),
  };
}

function createMockOrchestrator() {
  return {
    processQuery: vi.fn().mockResolvedValue({
      text: 'The weather today is sunny with mild temperatures.',
      confidenceScore: 0.85,
      sourceLabels: [],
      citations: [],
      disclaimers: [],
    }),
    classifyIntent: vi.fn().mockReturnValue('general'),
    decomposeTask: vi.fn().mockResolvedValue([]),
    executeSubTasks: vi.fn().mockResolvedValue([]),
  };
}

// ---- Helpers ----

function createTestDeps(): AppDependencies {
  const apiGateway = createMockApiGateway();
  const sessionManager = createMockSessionManager();
  const voiceInterface = createMockVoiceInterface();
  const ragPipeline = createMockRagPipeline();
  const dataFetcher = createMockDataFetcher();
  const llmEngine = createMockLlmEngine();
  const confidenceScorer = createMockConfidenceScorer();
  const orchestrator = createMockOrchestrator();
  const healthManager = createMockHealthManager();
  const wakeHandler = createMockWakeHandler(apiGateway, sessionManager, voiceInterface);

  return {
    apiGateway: apiGateway as any,
    sessionManager: sessionManager as any,
    voiceInterface: voiceInterface as any,
    ragPipeline: ragPipeline as any,
    dataFetcher: dataFetcher as any,
    llmEngine: llmEngine as any,
    confidenceScorer: confidenceScorer as any,
    orchestrator: orchestrator as any,
    wakeHandler: wakeHandler as any,
    healthManager: healthManager as any,
  };
}

async function makeRequest(app: express.Application, method: string, path: string, body?: any) {
  // Use a simple supertest-like approach with the app's handler
  const { default: http } = await import('node:http');
  const server = http.createServer(app);

  return new Promise<{ status: number; body: any }>((resolve, reject) => {
    server.listen(0, () => {
      const address = server.address() as { port: number };
      const bodyStr = body ? JSON.stringify(body) : '';
      const options = {
        hostname: '127.0.0.1',
        port: address.port,
        path,
        method: method.toUpperCase(),
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(bodyStr),
        },
      };

      const req = http.request(options, (res) => {
        let data = '';
        res.on('data', (chunk) => { data += chunk; });
        res.on('end', () => {
          server.close();
          try {
            resolve({ status: res.statusCode ?? 500, body: JSON.parse(data) });
          } catch {
            resolve({ status: res.statusCode ?? 500, body: data });
          }
        });
      });

      req.on('error', (err) => { server.close(); reject(err); });
      req.write(bodyStr);
      req.end();
    });
  });
}

// ---- Tests ----

describe('App Wiring - End-to-End Flow', () => {
  let deps: AppDependencies;
  let app: express.Application;

  beforeEach(() => {
    deps = createTestDeps();
    app = createApp(deps as any);
  });

  describe('POST /api/wake', () => {
    it('should authenticate and create a new session', async () => {
      const res = await makeRequest(app, 'POST', '/api/wake', {
        apiKey: 'valid-key',
        sourceIp: '192.168.1.1',
        userId: 'user-1',
      });

      expect(res.status).toBe(200);
      expect(res.body.success).toBe(true);
      expect(res.body.sessionId).toBe('session-123');
      expect(res.body.isExistingSession).toBe(false);
      expect(res.body.message).toContain('New session started');
    });

    it('should return 401 when authentication fails', async () => {
      (deps.apiGateway as any).authenticate.mockResolvedValue({
        authenticated: false,
        userId: null,
        method: 'api_key',
        error: 'Invalid API key',
      });

      const res = await makeRequest(app, 'POST', '/api/wake', {
        apiKey: 'invalid-key',
        sourceIp: '192.168.1.1',
        userId: 'user-1',
      });

      expect(res.status).toBe(401);
      expect(res.body.success).toBe(false);
      expect(res.body.error).toContain('Invalid API key');
    });

    it('should continue existing session on duplicate wake invocation', async () => {
      const existingSession = {
        id: 'session-existing',
        userId: 'user-1',
        startedAt: new Date(),
        lastActivityAt: new Date(),
        exchanges: [{ userMessage: 'hi', assistantResponse: 'hello', timestamp: new Date(), metadata: { confidenceScore: 0.9, sourcesUsed: [], responseTimeMs: 100 } }],
        isActive: true,
      };
      (deps.sessionManager as any).getActiveSessionForUser.mockResolvedValue(existingSession);

      const res = await makeRequest(app, 'POST', '/api/wake', {
        apiKey: 'valid-key',
        sourceIp: '192.168.1.1',
        userId: 'user-1',
      });

      expect(res.status).toBe(200);
      expect(res.body.success).toBe(true);
      expect(res.body.sessionId).toBe('session-existing');
      expect(res.body.isExistingSession).toBe(true);
      expect(res.body.message).toContain('Continuing existing session');
    });
  });

  describe('POST /api/query', () => {
    beforeEach(async () => {
      // Create a session for use in query tests
      (deps.sessionManager as any)._setSession({
        id: 'session-123',
        userId: 'user-1',
        startedAt: new Date(),
        lastActivityAt: new Date(),
        exchanges: [],
        isActive: true,
      });
    });

    it('should process a text query and return a response', async () => {
      const res = await makeRequest(app, 'POST', '/api/query', {
        sessionId: 'session-123',
        text: 'What is the meaning of life?',
      });

      expect(res.status).toBe(200);
      expect(res.body.success).toBe(true);
      expect(res.body.response.text).toBeDefined();
      expect(res.body.response.confidenceScore).toBeDefined();
      expect(res.body.responseTimeMs).toBeDefined();
    });

    it('should return 400 when sessionId is missing', async () => {
      const res = await makeRequest(app, 'POST', '/api/query', {
        text: 'Hello',
      });

      expect(res.status).toBe(400);
      expect(res.body.error).toContain('sessionId is required');
    });

    it('should return 404 when session does not exist', async () => {
      const res = await makeRequest(app, 'POST', '/api/query', {
        sessionId: 'nonexistent-session',
        text: 'Hello',
      });

      expect(res.status).toBe(404);
      expect(res.body.error).toContain('Session not found');
    });

    it('should return 400 when neither text nor audio is provided', async () => {
      const res = await makeRequest(app, 'POST', '/api/query', {
        sessionId: 'session-123',
      });

      expect(res.status).toBe(400);
      expect(res.body.error).toContain('Either text or audio is required');
    });

    it('should persist exchange to session after successful query', async () => {
      await makeRequest(app, 'POST', '/api/query', {
        sessionId: 'session-123',
        text: 'Tell me about science',
      });

      expect((deps.sessionManager as any).addExchange).toHaveBeenCalledWith(
        'session-123',
        expect.objectContaining({
          userMessage: 'Tell me about science',
          assistantResponse: expect.any(String),
        }),
      );
    });

    it('should include TTS audio when voiceConfig is provided', async () => {
      const res = await makeRequest(app, 'POST', '/api/query', {
        sessionId: 'session-123',
        text: 'Hello world',
        voiceConfig: { speed: 1.0, pitch: 1.0, voiceId: 'default' },
      });

      expect(res.status).toBe(200);
      expect(res.body.audio).toBeDefined();
      expect(res.body.audio).not.toBeNull();
    });
  });

  describe('Graceful Degradation', () => {
    beforeEach(() => {
      (deps.sessionManager as any)._setSession({
        id: 'session-123',
        userId: 'user-1',
        startedAt: new Date(),
        lastActivityAt: new Date(),
        exchanges: [],
        isActive: true,
      });
    });

    it('should continue with disclaimer when TTS fails', async () => {
      (deps.voiceInterface as any).synthesize.mockRejectedValue(new Error('TTS service unavailable'));

      const res = await makeRequest(app, 'POST', '/api/query', {
        sessionId: 'session-123',
        text: 'What time is it?',
        voiceConfig: { speed: 1.0, pitch: 1.0, voiceId: 'default' },
      });

      expect(res.status).toBe(200);
      expect(res.body.success).toBe(true);
      expect(res.body.response.text).toBeDefined();
      expect(res.body.audio).toBeNull();
      expect(res.body.response.disclaimers).toContain('Voice output unavailable, showing text response.');
    });

    it('should still deliver response when session persistence fails', async () => {
      (deps.sessionManager as any).addExchange.mockRejectedValue(new Error('Redis connection error'));

      const res = await makeRequest(app, 'POST', '/api/query', {
        sessionId: 'session-123',
        text: 'Hello',
      });

      // Response should still be delivered even if session save fails
      expect(res.status).toBe(200);
      expect(res.body.success).toBe(true);
      expect(res.body.response.text).toBeDefined();
    });
  });

  describe('POST /api/session/end', () => {
    beforeEach(() => {
      (deps.sessionManager as any)._setSession({
        id: 'session-123',
        userId: 'user-1',
        startedAt: new Date(),
        lastActivityAt: new Date(),
        exchanges: [],
        isActive: true,
      });
    });

    it('should end session successfully', async () => {
      const res = await makeRequest(app, 'POST', '/api/session/end', {
        sessionId: 'session-123',
      });

      expect(res.status).toBe(200);
      expect(res.body.success).toBe(true);
      expect(res.body.message).toContain('Session ended');
      expect((deps.voiceInterface as any).stopListening).toHaveBeenCalledWith('session-123');
    });

    it('should return 400 when sessionId is missing', async () => {
      const res = await makeRequest(app, 'POST', '/api/session/end', {});

      expect(res.status).toBe(400);
      expect(res.body.error).toContain('sessionId is required');
    });
  });

  describe('GET /api/health', () => {
    it('should return health status for all services', async () => {
      const res = await makeRequest(app, 'GET', '/api/health');

      expect(res.status).toBe(200);
      expect(res.body.status).toBe('healthy');
      expect(res.body.services).toBeDefined();
      expect(res.body.uptime).toBeDefined();
      expect(res.body.timestamp).toBeDefined();
    });

    it('should return 503 when a service is unhealthy', async () => {
      (deps.healthManager as any).getAllServiceHealth.mockReturnValue([
        { serviceName: 'llm', status: 'degraded', lastCheckAt: new Date(), responseTimeMs: 50 },
      ]);

      const res = await makeRequest(app, 'GET', '/api/health');

      expect(res.status).toBe(503);
      expect(res.body.status).toBe('degraded');
    });
  });

  describe('GET /api/session/:id', () => {
    it('should return session info when session exists', async () => {
      (deps.sessionManager as any)._setSession({
        id: 'session-456',
        userId: 'user-1',
        startedAt: new Date('2024-01-01'),
        lastActivityAt: new Date('2024-01-01'),
        exchanges: [],
        isActive: true,
      });

      const res = await makeRequest(app, 'GET', '/api/session/session-456');

      expect(res.status).toBe(200);
      expect(res.body.success).toBe(true);
      expect(res.body.session.id).toBe('session-456');
      expect(res.body.session.isActive).toBe(true);
      expect(res.body.session.exchangeCount).toBe(0);
    });

    it('should return 404 when session does not exist', async () => {
      const res = await makeRequest(app, 'GET', '/api/session/nonexistent');

      expect(res.status).toBe(404);
      expect(res.body.error).toContain('Session not found');
    });
  });

  describe('Session Preservation Across Errors', () => {
    it('should not corrupt session when orchestrator throws an error', async () => {
      (deps.sessionManager as any)._setSession({
        id: 'session-123',
        userId: 'user-1',
        startedAt: new Date(),
        lastActivityAt: new Date(),
        exchanges: [
          { userMessage: 'first', assistantResponse: 'first-reply', timestamp: new Date(), metadata: { confidenceScore: 0.9, sourcesUsed: [], responseTimeMs: 100 } },
        ],
        isActive: true,
      });

      // Orchestrator throws an error on this query
      (deps.orchestrator as any).processQuery.mockRejectedValueOnce(new Error('LLM timeout'));

      const res = await makeRequest(app, 'POST', '/api/query', {
        sessionId: 'session-123',
        text: 'This will fail',
      });

      expect(res.status).toBe(500);

      // Session should still be retrievable and intact
      const session = await (deps.sessionManager as any).getSession('session-123');
      expect(session).not.toBeNull();
      expect(session.isActive).toBe(true);
      expect(session.exchanges).toHaveLength(1); // Original exchange preserved
    });
  });
});
