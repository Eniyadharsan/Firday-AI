/**
 * Session Manager Service
 *
 * Maintains conversation history, handles session lifecycle, and persists
 * session state in Redis. Implements the SessionManager interface with
 * a 50-exchange rolling window and inactivity tracking.
 *
 * Requirements: 2.1, 2.4, 7.2
 */

import { randomUUID } from 'node:crypto';
import Redis from 'ioredis';
import { SESSION_MAX_EXCHANGES } from '../config/defaults.js';
import type {
  SessionManager,
  Session,
  Exchange,
} from '../interfaces/session-manager.js';

/** Redis key prefix for session storage */
const SESSION_KEY_PREFIX = 'session:';

/** Redis key prefix for tracking active session per user */
const ACTIVE_SESSION_KEY_PREFIX = 'active-session:';

/** TTL for session keys in seconds (24 hours for cleanup) */
const SESSION_TTL_SECONDS = 24 * 60 * 60;

/**
 * Serializable session representation for Redis storage.
 * Dates are stored as ISO strings since JSON.stringify loses Date types.
 */
interface SerializedSession {
  id: string;
  userId: string;
  startedAt: string;
  lastActivityAt: string;
  exchanges: SerializedExchange[];
  isActive: boolean;
}

interface SerializedExchange {
  userMessage: string;
  assistantResponse: string;
  timestamp: string;
  metadata: {
    confidenceScore: number;
    sourcesUsed: string[];
    responseTimeMs: number;
  };
}

export class RedisSessionManager implements SessionManager {
  private readonly redis: Redis;

  constructor(redis?: Redis) {
    this.redis =
      redis ?? new Redis(process.env['REDIS_URL'] ?? 'redis://localhost:6379');
  }

  /**
   * Create a new session with a unique ID and store it in Redis.
   * Requirement 2.1: Begin a new Session within 3 seconds and provide acknowledgment.
   */
  async createSession(userId: string): Promise<Session> {
    const now = new Date();
    const session: Session = {
      id: randomUUID(),
      userId,
      startedAt: now,
      lastActivityAt: now,
      exchanges: [],
      isActive: true,
    };

    await this.saveSession(session);
    // Track this as the active session for the user
    await this.redis.set(
      `${ACTIVE_SESSION_KEY_PREFIX}${userId}`,
      session.id,
      'EX',
      SESSION_TTL_SECONDS,
    );
    return session;
  }

  /**
   * Retrieve a session by ID from Redis.
   * Returns null if the session does not exist.
   */
  async getSession(sessionId: string): Promise<Session | null> {
    const key = this.buildKey(sessionId);
    const data = await this.redis.get(key);

    if (!data) {
      return null;
    }

    return this.deserialize(data);
  }

  /**
   * Append an exchange to the session and enforce the 50-exchange rolling window.
   * Updates lastActivityAt for inactivity detection.
   * Requirement 7.2: Maintain at least the most recent 50 exchanges.
   */
  async addExchange(sessionId: string, exchange: Exchange): Promise<void> {
    const session = await this.getSession(sessionId);

    if (!session) {
      throw new Error(`Session not found: ${sessionId}`);
    }

    if (!session.isActive) {
      throw new Error(`Session is not active: ${sessionId}`);
    }

    // Append the new exchange
    session.exchanges.push(exchange);

    // Enforce rolling window: keep only the most recent SESSION_MAX_EXCHANGES
    if (session.exchanges.length > SESSION_MAX_EXCHANGES) {
      session.exchanges = session.exchanges.slice(-SESSION_MAX_EXCHANGES);
    }

    // Update lastActivityAt for inactivity detection
    session.lastActivityAt = new Date();

    await this.saveSession(session);
  }

  /**
   * End a session by marking it inactive.
   * Requirement 2.4: Confirm session termination within 2 seconds.
   */
  async endSession(sessionId: string): Promise<void> {
    const session = await this.getSession(sessionId);

    if (!session) {
      throw new Error(`Session not found: ${sessionId}`);
    }

    session.isActive = false;
    session.lastActivityAt = new Date();

    await this.saveSession(session);
    // Remove the active-session tracking key for this user
    await this.redis.del(`${ACTIVE_SESSION_KEY_PREFIX}${session.userId}`);
  }

  /**
   * Get the active session for a given user, if one exists.
   * Requirement 2.6: Support session continuity on duplicate wake invocations.
   */
  async getActiveSessionForUser(userId: string): Promise<Session | null> {
    const activeSessionId = await this.redis.get(
      `${ACTIVE_SESSION_KEY_PREFIX}${userId}`,
    );

    if (!activeSessionId) {
      return null;
    }

    const session = await this.getSession(activeSessionId);

    // Validate the session is still active (it may have been ended without
    // cleaning up the active-session key in an edge case)
    if (!session || !session.isActive) {
      // Clean up stale reference
      await this.redis.del(`${ACTIVE_SESSION_KEY_PREFIX}${userId}`);
      return null;
    }

    return session;
  }

  /**
   * Handle a wake invocation for a user.
   * If an active session exists, continue it without creating a new one.
   * If no active session exists, create a new one.
   * Requirement 2.6: Continue existing session on duplicate wake invocation.
   */
  async handleWakeInvocation(
    userId: string,
  ): Promise<{ session: Session; isExisting: boolean }> {
    const existingSession = await this.getActiveSessionForUser(userId);

    if (existingSession) {
      return { session: existingSession, isExisting: true };
    }

    const newSession = await this.createSession(userId);
    return { session: newSession, isExisting: false };
  }

  /**
   * Save a session to Redis with TTL for automatic cleanup.
   */
  private async saveSession(session: Session): Promise<void> {
    const key = this.buildKey(session.id);
    const serialized = this.serialize(session);
    await this.redis.set(key, serialized, 'EX', SESSION_TTL_SECONDS);
  }

  /**
   * Build the Redis key for a session.
   */
  private buildKey(sessionId: string): string {
    return `${SESSION_KEY_PREFIX}${sessionId}`;
  }

  /**
   * Serialize a Session to JSON for Redis storage.
   */
  private serialize(session: Session): string {
    const serialized: SerializedSession = {
      id: session.id,
      userId: session.userId,
      startedAt: session.startedAt.toISOString(),
      lastActivityAt: session.lastActivityAt.toISOString(),
      exchanges: session.exchanges.map((ex) => ({
        userMessage: ex.userMessage,
        assistantResponse: ex.assistantResponse,
        timestamp: ex.timestamp.toISOString(),
        metadata: {
          confidenceScore: ex.metadata.confidenceScore,
          sourcesUsed: ex.metadata.sourcesUsed,
          responseTimeMs: ex.metadata.responseTimeMs,
        },
      })),
      isActive: session.isActive,
    };
    return JSON.stringify(serialized);
  }

  /**
   * Deserialize a JSON string from Redis back into a Session object.
   */
  private deserialize(data: string): Session {
    const parsed: SerializedSession = JSON.parse(data);
    return {
      id: parsed.id,
      userId: parsed.userId,
      startedAt: new Date(parsed.startedAt),
      lastActivityAt: new Date(parsed.lastActivityAt),
      exchanges: parsed.exchanges.map((ex) => ({
        userMessage: ex.userMessage,
        assistantResponse: ex.assistantResponse,
        timestamp: new Date(ex.timestamp),
        metadata: {
          confidenceScore: ex.metadata.confidenceScore,
          sourcesUsed: ex.metadata.sourcesUsed,
          responseTimeMs: ex.metadata.responseTimeMs,
        },
      })),
      isActive: parsed.isActive,
    };
  }
}
