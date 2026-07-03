/**
 * Main Application Bootstrap
 *
 * Instantiates all service classes with their dependencies,
 * wires them together via the OrchestratorService, and sets up
 * Express routes for the end-to-end flow.
 *
 * End-to-end flow:
 *   Wake → Auth → Session → Voice STT → Intent Classification →
 *   RAG/DataFetch → LLM → Confidence → Voice TTS
 *
 * Routes:
 *   POST /api/wake        — handle wake invocation (auth → session create/resume)
 *   POST /api/query       — handle user query (text input through orchestrator)
 *   POST /api/session/end — end session
 *   GET  /api/health      — health check for all services
 *   GET  /api/session/:id — get session info
 *
 * Graceful degradation:
 *   - RAG pipeline timeout/error: continue without RAG context, add disclaimer
 *   - Data Fetcher failure: inform user, continue without data
 *   - TTS failure: return text response without speech
 *   - Session persistence failure: deliver response, log error
 *
 * Error propagation strategy:
 *   1. Local Recovery First: each component handles retries internally before escalating
 *   2. Graceful Degradation: non-critical failure → continue with reduced capability
 *   3. Fail-Safe Defaults: label responses "unverified" + disclaimers when uncertain
 *   4. Session Preservation: errors in one exchange do not corrupt session state
 *
 * Requirements: 8.1, all requirements integrated
 */

import express, { Request, Response } from 'express';
import { OrchestratorService, OrchestratorDeps } from './services/orchestrator.js';
import { WakeHandler } from './services/wake-handler.js';
import { VoiceInterfaceService } from './services/voice-interface.js';
import { RedisSessionManager } from './services/session-manager.js';
import { RAGPipelineService } from './services/rag-pipeline.js';
import { DataFetcherService } from './services/data-fetcher.js';
import { VLLMEngine } from './services/llm-engine.js';
import { ConfidenceScorerService } from './services/confidence-scorer.js';
import { APIGatewayService } from './services/api-gateway.js';
import { HealthManager } from './services/health-manager.js';
import { errorHandler, notFoundHandler, asyncHandler } from './middleware/error-handler.js';
import { TRANSCRIPTION_CONFIDENCE_THRESHOLD } from './config/defaults.js';
import type { VoiceConfig } from './interfaces/voice-interface.js';
import type { UserQuery, AssistantResponse } from './interfaces/orchestrator.js';

/**
 * Dependencies that can be injected into the application for testing.
 * When not provided, real service instances are created from environment config.
 */
export interface AppDependencies {
  apiGateway: APIGatewayService;
  sessionManager: RedisSessionManager;
  voiceInterface: VoiceInterfaceService;
  ragPipeline: RAGPipelineService;
  dataFetcher: DataFetcherService;
  llmEngine: VLLMEngine;
  confidenceScorer: ConfidenceScorerService;
  orchestrator: OrchestratorService;
  wakeHandler: WakeHandler;
  healthManager: HealthManager;
}

/**
 * Collect audio chunks from a ReadableStream into a base64-encoded string.
 */
async function streamToBase64(stream: NodeJS.ReadableStream): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of stream) {
    if (Buffer.isBuffer(chunk)) {
      chunks.push(chunk);
    } else {
      chunks.push(Buffer.from(chunk as unknown as ArrayBuffer));
    }
  }
  return Buffer.concat(chunks).toString('base64');
}

/**
 * Create the Express application with all routes wired.
 *
 * Accepts optional dependencies for dependency injection (testing).
 * When no dependencies are provided, creates real service instances
 * from environment configuration.
 */
export function createApp(deps?: AppDependencies): express.Application {
  // --- Service Instantiation ---
  const apiGateway = deps?.apiGateway ?? new APIGatewayService();
  const sessionManager = deps?.sessionManager ?? new RedisSessionManager();
  const voiceInterface = deps?.voiceInterface ?? new VoiceInterfaceService();
  const ragPipeline = deps?.ragPipeline ?? new RAGPipelineService();
  const dataFetcher = deps?.dataFetcher ?? new DataFetcherService();
  const llmEngine = deps?.llmEngine ?? new VLLMEngine();
  const confidenceScorer = deps?.confidenceScorer ?? new ConfidenceScorerService();
  const healthManager = deps?.healthManager ?? new HealthManager();

  const orchestratorDeps: OrchestratorDeps = {
    ragPipeline,
    dataFetcher,
    llmEngine,
    confidenceScorer,
  };
  const orchestrator = deps?.orchestrator ?? new OrchestratorService(orchestratorDeps);

  const wakeHandler = deps?.wakeHandler ?? new WakeHandler(apiGateway, sessionManager, voiceInterface);

  // --- Express App Setup ---
  const app = express();
  app.use(express.json({ limit: '10mb' }));

  // --- Routes ---

  /**
   * POST /api/wake — Wake invocation endpoint.
   *
   * Flow: Auth → Session Create/Resume → Acknowledge
   *
   * Request body:
   *   { apiKey: string, sourceIp: string, userId: string }
   *
   * Response (200):
   *   { success: true, sessionId, isExistingSession, message, timestamp }
   *
   * Response (401):
   *   { success: false, error }
   */
  app.post('/api/wake', asyncHandler(async (req: Request, res: Response) => {
    const { apiKey, sourceIp, userId } = req.body;

    const incomingRequest = {
      apiKey: apiKey ?? '',
      sourceIp: sourceIp ?? req.ip ?? '0.0.0.0',
      timestamp: new Date(),
    };

    const result = await wakeHandler.handleWakeInvocation(userId ?? '', incomingRequest);

    // Check if result is a WakeError (has 'error' field)
    if ('error' in result) {
      res.status(401).json({
        success: false,
        error: result.error,
      });
      return;
    }

    // Successful wake invocation
    const message = result.isExisting
      ? 'Continuing existing session.'
      : 'New session started.';

    res.status(200).json({
      success: true,
      sessionId: result.session.id,
      isExistingSession: result.isExisting,
      message,
      timestamp: result.timestamp.toISOString(),
    });
  }));

  /**
   * POST /api/query — Process a user query (text or voice).
   *
   * Flow: Validate → Retrieve Session → (STT if audio) → Orchestrator →
   *       (TTS if voiceConfig) → Persist Exchange → Response
   *
   * Request body:
   *   { sessionId: string, text?: string, audio?: string (base64), voiceConfig?: VoiceConfig }
   *
   * Graceful degradation:
   *   - TTS failure: return text response with audio=null, add disclaimer
   *   - Session persistence failure: deliver response, log error
   *   - Orchestrator handles RAG/Data failures internally with disclaimers
   */
  app.post('/api/query', asyncHandler(async (req: Request, res: Response) => {
    const { sessionId, text, audio, voiceConfig } = req.body;
    const startTime = Date.now();

    // Validation
    if (!sessionId) {
      res.status(400).json({ success: false, error: 'sessionId is required' });
      return;
    }

    if (!text && !audio) {
      res.status(400).json({ success: false, error: 'Either text or audio is required' });
      return;
    }

    // Retrieve session — preserve session on any error
    const session = await sessionManager.getSession(sessionId);
    if (!session) {
      res.status(404).json({ success: false, error: 'Session not found' });
      return;
    }

    // Determine query text (STT if audio provided, otherwise use text)
    let queryText = text ?? '';
    if (audio && !text) {
      // Convert base64 audio to buffer and run STT
      const { Readable } = await import('node:stream');
      const audioBuffer = Buffer.from(audio, 'base64');
      const audioStream = Readable.from(audioBuffer);

      const transcription = await voiceInterface.transcribe(audioStream);

      // Handle low-confidence transcription
      if (transcription.confidence < TRANSCRIPTION_CONFIDENCE_THRESHOLD) {
        const notification = voiceInterface.handleLowConfidence(sessionId);
        if (notification) {
          res.status(200).json({
            success: true,
            response: {
              text: notification.message,
              confidenceScore: 0,
              sourceLabels: [],
              citations: [],
              disclaimers: ['Low transcription confidence'],
            },
            audio: null,
            responseTimeMs: Date.now() - startTime,
          });
          return;
        }
      } else {
        voiceInterface.resetRetryCount(sessionId);
      }

      queryText = transcription.text;
    }

    // Build UserQuery
    const userQuery: UserQuery = {
      text: queryText,
      transcriptionConfidence: 1.0,
      sessionId,
      timestamp: new Date(),
    };

    // Process through orchestrator (handles RAG/Data/LLM degradation internally)
    // If orchestrator itself throws, we catch it to preserve session state
    let response: AssistantResponse;
    try {
      response = await orchestrator.processQuery(session, userQuery);
    } catch (error: unknown) {
      // Session preservation: do NOT corrupt session state on orchestrator errors
      const message = error instanceof Error ? error.message : 'Unknown error';
      console.error(`[App] Orchestrator error: ${message}`);
      res.status(500).json({
        success: false,
        error: "I'm having trouble generating a response, please try again.",
        sessionId,
      });
      return;
    }

    // Attempt TTS if voiceConfig provided — graceful degradation on failure
    let audioOutput: string | null = null;
    const disclaimers = [...(response.disclaimers ?? [])];

    if (voiceConfig) {
      try {
        const ttsStream = await voiceInterface.synthesize(response.text, voiceConfig as VoiceConfig);
        audioOutput = await streamToBase64(ttsStream);
      } catch (error: unknown) {
        // TTS failure: continue with text response, add disclaimer
        const message = error instanceof Error ? error.message : 'Unknown error';
        console.error(`[App] TTS failure: ${message}`);
        disclaimers.push('Voice output unavailable, showing text response.');
        audioOutput = null;
      }
    }

    // Persist exchange to session — graceful degradation on failure
    try {
      await sessionManager.addExchange(sessionId, {
        userMessage: queryText,
        assistantResponse: response.text,
        timestamp: new Date(),
        metadata: {
          confidenceScore: response.confidenceScore,
          sourcesUsed: response.citations.map(c => c.source),
          responseTimeMs: Date.now() - startTime,
        },
      });
    } catch (error: unknown) {
      // Session persistence failure: deliver response anyway, log error
      const message = error instanceof Error ? error.message : 'Unknown error';
      console.error(`[App] Session persistence failure: ${message}`);
    }

    const responseTimeMs = Date.now() - startTime;

    res.status(200).json({
      success: true,
      response: {
        text: response.text,
        confidenceScore: response.confidenceScore,
        sourceLabels: response.sourceLabels,
        citations: response.citations,
        disclaimers,
      },
      audio: audioOutput,
      responseTimeMs,
    });
  }));

  /**
   * POST /api/session/end — End a session.
   *
   * Flow: Validate → End Session → Stop Listening → Confirm
   *
   * Request body:
   *   { sessionId: string }
   */
  app.post('/api/session/end', asyncHandler(async (req: Request, res: Response) => {
    const { sessionId } = req.body;

    if (!sessionId) {
      res.status(400).json({ success: false, error: 'sessionId is required' });
      return;
    }

    // End session and stop listening
    await sessionManager.endSession(sessionId);
    voiceInterface.stopListening(sessionId);

    res.status(200).json({
      success: true,
      message: 'Session ended.',
      sessionId,
      terminatedAt: new Date().toISOString(),
    });
  }));

  /**
   * GET /api/health — Health check for all services.
   *
   * Returns overall system status and individual service reports.
   * Returns 200 if all healthy, 503 if any service is degraded/unavailable.
   */
  app.get('/api/health', asyncHandler(async (_req: Request, res: Response) => {
    const services = healthManager.getAllServiceHealth();
    const uptime = healthManager.getUptime();

    // Determine overall status
    const hasUnavailable = services.some(s => s.status === 'unavailable');
    const hasDegraded = services.some(s => s.status === 'degraded');
    const overallStatus = hasUnavailable ? 'unavailable' : hasDegraded ? 'degraded' : 'healthy';
    const statusCode = overallStatus === 'healthy' ? 200 : 503;

    res.status(statusCode).json({
      status: overallStatus,
      services: services.map(s => ({
        name: s.serviceName,
        status: s.status,
        lastCheckAt: s.lastCheckAt.toISOString(),
        responseTimeMs: s.responseTimeMs,
      })),
      uptime: {
        percent: uptime.uptimePercent,
        trackingSince: uptime.trackingSince.toISOString(),
      },
      timestamp: new Date().toISOString(),
    });
  }));

  /**
   * GET /api/session/:id — Get session information.
   *
   * Returns session metadata and exchange count.
   */
  app.get('/api/session/:id', asyncHandler(async (req: Request, res: Response) => {
    const sessionId = req.params['id'];

    if (!sessionId) {
      res.status(400).json({ success: false, error: 'Session ID is required' });
      return;
    }

    const session = await sessionManager.getSession(sessionId);
    if (!session) {
      res.status(404).json({ success: false, error: 'Session not found' });
      return;
    }

    res.status(200).json({
      success: true,
      session: {
        id: session.id,
        userId: session.userId,
        startedAt: session.startedAt.toISOString(),
        lastActivityAt: session.lastActivityAt.toISOString(),
        isActive: session.isActive,
        exchangeCount: session.exchanges.length,
      },
    });
  }));

  // --- Error Handling ---
  app.use(notFoundHandler);
  app.use(errorHandler);

  return app;
}
