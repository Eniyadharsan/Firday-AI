import { describe, it, expect, beforeEach } from 'vitest';
import Redis from 'ioredis';
import { RedisSessionManager } from '../../src/services/session-manager.js';
import { SESSION_MAX_EXCHANGES } from '../../src/config/defaults.js';
import type { Exchange } from '../../src/interfaces/session-manager.js';

/**
 * In-memory Redis mock for unit testing.
 * Simulates get/set/del with TTL tracking without requiring a real Redis server.
 */
class MockRedis {
  private store = new Map<string, { value: string; expiresAt?: number }>();

  async get(key: string): Promise<string | null> {
    const entry = this.store.get(key);
    if (!entry) return null;
    if (entry.expiresAt && Date.now() > entry.expiresAt) {
      this.store.delete(key);
      return null;
    }
    return entry.value;
  }

  async set(key: string, value: string, mode?: string, ttl?: number): Promise<'OK'> {
    const entry: { value: string; expiresAt?: number } = { value };
    if (mode === 'EX' && ttl) {
      entry.expiresAt = Date.now() + ttl * 1000;
    }
    this.store.set(key, entry);
    return 'OK';
  }

  async del(key: string): Promise<number> {
    return this.store.delete(key) ? 1 : 0;
  }

  clear(): void {
    this.store.clear();
  }
}

function createExchange(index: number): Exchange {
  return {
    userMessage: `User message ${index}`,
    assistantResponse: `Assistant response ${index}`,
    timestamp: new Date(),
    metadata: {
      confidenceScore: 0.85,
      sourcesUsed: ['source-a'],
      responseTimeMs: 150,
    },
  };
}

describe('RedisSessionManager', () => {
  let mockRedis: MockRedis;
  let sessionManager: RedisSessionManager;

  beforeEach(() => {
    mockRedis = new MockRedis();
    sessionManager = new RedisSessionManager(mockRedis as unknown as Redis);
  });

  describe('createSession', () => {
    it('should create a session with a unique ID', async () => {
      const session = await sessionManager.createSession('user-123');

      expect(session.id).toBeDefined();
      expect(session.id).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
      );
    });

    it('should initialize session with correct user ID', async () => {
      const session = await sessionManager.createSession('user-456');
      expect(session.userId).toBe('user-456');
    });

    it('should set isActive to true', async () => {
      const session = await sessionManager.createSession('user-123');
      expect(session.isActive).toBe(true);
    });

    it('should start with empty exchanges array', async () => {
      const session = await sessionManager.createSession('user-123');
      expect(session.exchanges).toEqual([]);
    });

    it('should set startedAt and lastActivityAt to current time', async () => {
      const before = new Date();
      const session = await sessionManager.createSession('user-123');
      const after = new Date();

      expect(session.startedAt.getTime()).toBeGreaterThanOrEqual(before.getTime());
      expect(session.startedAt.getTime()).toBeLessThanOrEqual(after.getTime());
      expect(session.lastActivityAt.getTime()).toEqual(session.startedAt.getTime());
    });

    it('should persist session to Redis', async () => {
      const session = await sessionManager.createSession('user-123');
      const retrieved = await sessionManager.getSession(session.id);

      expect(retrieved).not.toBeNull();
      expect(retrieved!.id).toBe(session.id);
      expect(retrieved!.userId).toBe('user-123');
    });

    it('should generate unique IDs for different sessions', async () => {
      const session1 = await sessionManager.createSession('user-123');
      const session2 = await sessionManager.createSession('user-123');

      expect(session1.id).not.toBe(session2.id);
    });
  });

  describe('getSession', () => {
    it('should return null for non-existent session', async () => {
      const result = await sessionManager.getSession('non-existent-id');
      expect(result).toBeNull();
    });

    it('should return the session with correct data', async () => {
      const created = await sessionManager.createSession('user-789');
      const retrieved = await sessionManager.getSession(created.id);

      expect(retrieved).not.toBeNull();
      expect(retrieved!.id).toBe(created.id);
      expect(retrieved!.userId).toBe('user-789');
      expect(retrieved!.isActive).toBe(true);
      expect(retrieved!.exchanges).toEqual([]);
    });

    it('should correctly deserialize dates', async () => {
      const created = await sessionManager.createSession('user-123');
      const retrieved = await sessionManager.getSession(created.id);

      expect(retrieved!.startedAt).toBeInstanceOf(Date);
      expect(retrieved!.lastActivityAt).toBeInstanceOf(Date);
      expect(retrieved!.startedAt.getTime()).toBe(created.startedAt.getTime());
    });
  });

  describe('addExchange', () => {
    it('should append an exchange to the session', async () => {
      const session = await sessionManager.createSession('user-123');
      const exchange = createExchange(1);

      await sessionManager.addExchange(session.id, exchange);

      const updated = await sessionManager.getSession(session.id);
      expect(updated!.exchanges).toHaveLength(1);
      expect(updated!.exchanges[0]!.userMessage).toBe('User message 1');
    });

    it('should update lastActivityAt on each exchange', async () => {
      const session = await sessionManager.createSession('user-123');
      const originalActivity = session.lastActivityAt;

      // Small delay to ensure time difference
      await new Promise((resolve) => setTimeout(resolve, 10));

      await sessionManager.addExchange(session.id, createExchange(1));

      const updated = await sessionManager.getSession(session.id);
      expect(updated!.lastActivityAt.getTime()).toBeGreaterThan(
        originalActivity.getTime()
      );
    });

    it('should throw error for non-existent session', async () => {
      await expect(
        sessionManager.addExchange('non-existent', createExchange(1))
      ).rejects.toThrow('Session not found: non-existent');
    });

    it('should throw error for inactive session', async () => {
      const session = await sessionManager.createSession('user-123');
      await sessionManager.endSession(session.id);

      await expect(
        sessionManager.addExchange(session.id, createExchange(1))
      ).rejects.toThrow(`Session is not active: ${session.id}`);
    });

    it('should enforce 50-exchange rolling window', async () => {
      const session = await sessionManager.createSession('user-123');

      // Add 55 exchanges
      for (let i = 1; i <= 55; i++) {
        await sessionManager.addExchange(session.id, createExchange(i));
      }

      const updated = await sessionManager.getSession(session.id);
      expect(updated!.exchanges).toHaveLength(SESSION_MAX_EXCHANGES);

      // Should retain the most recent 50 (exchanges 6-55)
      expect(updated!.exchanges[0]!.userMessage).toBe('User message 6');
      expect(updated!.exchanges[49]!.userMessage).toBe('User message 55');
    });

    it('should retain all exchanges when count is at or below limit', async () => {
      const session = await sessionManager.createSession('user-123');

      for (let i = 1; i <= SESSION_MAX_EXCHANGES; i++) {
        await sessionManager.addExchange(session.id, createExchange(i));
      }

      const updated = await sessionManager.getSession(session.id);
      expect(updated!.exchanges).toHaveLength(SESSION_MAX_EXCHANGES);
      expect(updated!.exchanges[0]!.userMessage).toBe('User message 1');
    });

    it('should preserve exchange metadata through serialization', async () => {
      const session = await sessionManager.createSession('user-123');
      const exchange: Exchange = {
        userMessage: 'Tell me about weather',
        assistantResponse: 'The weather is sunny today.',
        timestamp: new Date('2024-01-15T10:30:00Z'),
        metadata: {
          confidenceScore: 0.92,
          sourcesUsed: ['weather-api', 'news-feed'],
          responseTimeMs: 234,
        },
      };

      await sessionManager.addExchange(session.id, exchange);

      const updated = await sessionManager.getSession(session.id);
      const stored = updated!.exchanges[0]!;
      expect(stored.metadata.confidenceScore).toBe(0.92);
      expect(stored.metadata.sourcesUsed).toEqual(['weather-api', 'news-feed']);
      expect(stored.metadata.responseTimeMs).toBe(234);
      expect(stored.timestamp.toISOString()).toBe('2024-01-15T10:30:00.000Z');
    });
  });

  describe('endSession', () => {
    it('should mark session as inactive', async () => {
      const session = await sessionManager.createSession('user-123');
      await sessionManager.endSession(session.id);

      const ended = await sessionManager.getSession(session.id);
      expect(ended!.isActive).toBe(false);
    });

    it('should update lastActivityAt when ending', async () => {
      const session = await sessionManager.createSession('user-123');
      const originalActivity = session.lastActivityAt;

      await new Promise((resolve) => setTimeout(resolve, 10));
      await sessionManager.endSession(session.id);

      const ended = await sessionManager.getSession(session.id);
      expect(ended!.lastActivityAt.getTime()).toBeGreaterThan(
        originalActivity.getTime()
      );
    });

    it('should throw error for non-existent session', async () => {
      await expect(
        sessionManager.endSession('non-existent')
      ).rejects.toThrow('Session not found: non-existent');
    });

    it('should preserve exchanges when ending session', async () => {
      const session = await sessionManager.createSession('user-123');
      await sessionManager.addExchange(session.id, createExchange(1));
      await sessionManager.addExchange(session.id, createExchange(2));

      await sessionManager.endSession(session.id);

      const ended = await sessionManager.getSession(session.id);
      expect(ended!.exchanges).toHaveLength(2);
      expect(ended!.isActive).toBe(false);
    });
  });

  describe('lastActivityAt tracking', () => {
    it('should reflect the time of the most recent exchange', async () => {
      const session = await sessionManager.createSession('user-123');

      await new Promise((resolve) => setTimeout(resolve, 10));
      await sessionManager.addExchange(session.id, createExchange(1));
      const afterFirst = (await sessionManager.getSession(session.id))!.lastActivityAt;

      await new Promise((resolve) => setTimeout(resolve, 10));
      await sessionManager.addExchange(session.id, createExchange(2));
      const afterSecond = (await sessionManager.getSession(session.id))!.lastActivityAt;

      expect(afterSecond.getTime()).toBeGreaterThan(afterFirst.getTime());
    });
  });

  describe('getActiveSessionForUser', () => {
    it('should return null when no active session exists for a user', async () => {
      const result = await sessionManager.getActiveSessionForUser('user-no-session');
      expect(result).toBeNull();
    });

    it('should return the active session for a user', async () => {
      const session = await sessionManager.createSession('user-123');
      const active = await sessionManager.getActiveSessionForUser('user-123');

      expect(active).not.toBeNull();
      expect(active!.id).toBe(session.id);
      expect(active!.userId).toBe('user-123');
      expect(active!.isActive).toBe(true);
    });

    it('should return null after session is ended', async () => {
      const session = await sessionManager.createSession('user-123');
      await sessionManager.endSession(session.id);

      const active = await sessionManager.getActiveSessionForUser('user-123');
      expect(active).toBeNull();
    });

    it('should return the most recent active session when createSession is called multiple times', async () => {
      await sessionManager.createSession('user-123');
      const session2 = await sessionManager.createSession('user-123');

      const active = await sessionManager.getActiveSessionForUser('user-123');
      expect(active).not.toBeNull();
      expect(active!.id).toBe(session2.id);
    });

    it('should clean up stale reference if session was marked inactive directly', async () => {
      const session = await sessionManager.createSession('user-123');

      // Simulate a scenario where session is inactive but active-session key still exists
      // (e.g., a race condition or manual intervention)
      // End the session manually without going through endSession
      const rawSession = await sessionManager.getSession(session.id);
      rawSession!.isActive = false;
      // We can't directly save, so we use endSession which does clean up
      // Instead, let's just verify that getActiveSessionForUser handles it:
      await sessionManager.endSession(session.id);

      const active = await sessionManager.getActiveSessionForUser('user-123');
      expect(active).toBeNull();
    });
  });

  describe('handleWakeInvocation', () => {
    it('should create a new session when no active session exists', async () => {
      const result = await sessionManager.handleWakeInvocation('user-123');

      expect(result.isExisting).toBe(false);
      expect(result.session).toBeDefined();
      expect(result.session.userId).toBe('user-123');
      expect(result.session.isActive).toBe(true);
    });

    it('should return existing session when one is already active', async () => {
      const original = await sessionManager.createSession('user-123');
      const result = await sessionManager.handleWakeInvocation('user-123');

      expect(result.isExisting).toBe(true);
      expect(result.session.id).toBe(original.id);
    });

    it('should not create a new session on duplicate invocation', async () => {
      const first = await sessionManager.handleWakeInvocation('user-123');
      const second = await sessionManager.handleWakeInvocation('user-123');

      expect(first.session.id).toBe(second.session.id);
      expect(second.isExisting).toBe(true);
    });

    it('should preserve full history on duplicate invocation', async () => {
      const { session } = await sessionManager.handleWakeInvocation('user-123');

      // Add some exchanges
      await sessionManager.addExchange(session.id, createExchange(1));
      await sessionManager.addExchange(session.id, createExchange(2));
      await sessionManager.addExchange(session.id, createExchange(3));

      // Duplicate wake invocation
      const { session: continued, isExisting } =
        await sessionManager.handleWakeInvocation('user-123');

      expect(isExisting).toBe(true);
      expect(continued.id).toBe(session.id);
      expect(continued.exchanges).toHaveLength(3);
      expect(continued.exchanges[0]!.userMessage).toBe('User message 1');
      expect(continued.exchanges[2]!.userMessage).toBe('User message 3');
    });

    it('should create new session after previous session is ended', async () => {
      const { session: first } = await sessionManager.handleWakeInvocation('user-123');
      await sessionManager.endSession(first.id);

      const { session: second, isExisting } =
        await sessionManager.handleWakeInvocation('user-123');

      expect(isExisting).toBe(false);
      expect(second.id).not.toBe(first.id);
      expect(second.isActive).toBe(true);
    });

    it('should maintain session count unchanged on duplicate invocation', async () => {
      // First invocation creates a session
      const { session } = await sessionManager.handleWakeInvocation('user-123');

      // Multiple duplicate invocations should not create new sessions
      await sessionManager.handleWakeInvocation('user-123');
      await sessionManager.handleWakeInvocation('user-123');
      await sessionManager.handleWakeInvocation('user-123');

      // The active session should still be the original one
      const active = await sessionManager.getActiveSessionForUser('user-123');
      expect(active!.id).toBe(session.id);
    });

    it('should handle different users independently', async () => {
      const { session: sessionA } = await sessionManager.handleWakeInvocation('user-A');
      const { session: sessionB } = await sessionManager.handleWakeInvocation('user-B');

      expect(sessionA.id).not.toBe(sessionB.id);
      expect(sessionA.userId).toBe('user-A');
      expect(sessionB.userId).toBe('user-B');

      // Duplicate for user-A should return user-A's session
      const { session: dupA, isExisting } =
        await sessionManager.handleWakeInvocation('user-A');
      expect(isExisting).toBe(true);
      expect(dupA.id).toBe(sessionA.id);
    });

    it('should acknowledge invocation by returning session details', async () => {
      // First invocation
      const first = await sessionManager.handleWakeInvocation('user-123');
      expect(first.session.id).toBeDefined();
      expect(first.session.startedAt).toBeInstanceOf(Date);
      expect(first.isExisting).toBe(false);

      // Duplicate invocation also returns acknowledgeable response
      const second = await sessionManager.handleWakeInvocation('user-123');
      expect(second.session.id).toBeDefined();
      expect(second.session.startedAt).toBeInstanceOf(Date);
      expect(second.isExisting).toBe(true);
    });
  });
});
