/**
 * Property Test: Session History Retention Invariant (Property 17)
 *
 * **Validates: Requirements 7.2**
 *
 * Generates sessions with N exchanges (varying N from 1 to 100+)
 * and verifies four properties:
 * 1. Session retains min(N, 50) exchanges for any N
 * 2. For N > 50, the 50 most RECENT exchanges are retained (oldest evicted)
 * 3. For N <= 50, ALL exchanges are retained
 * 4. Exchange order is always preserved (no reordering)
 */

import { describe, it, expect, beforeEach } from 'vitest';
import fc from 'fast-check';
import { RedisSessionManager } from '../../src/services/session-manager';
import type { Exchange } from '../../src/interfaces/session-manager';
import { SESSION_MAX_EXCHANGES } from '../../src/config/defaults';

/**
 * MockRedis - In-memory Redis substitute for testing without a real Redis server.
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
}

/**
 * Create a valid Exchange with a unique index marker for ordering verification.
 */
function createExchange(index: number): Exchange {
  return {
    userMessage: `user-message-${index}`,
    assistantResponse: `assistant-response-${index}`,
    timestamp: new Date(1700000000000 + index * 1000),
    metadata: {
      confidenceScore: 0.85,
      sourcesUsed: ['source-1'],
      responseTimeMs: 200,
    },
  };
}

describe('Property 17: Session History Retention Invariant', () => {
  /**
   * **Validates: Requirements 7.2**
   *
   * Property 1: For any N exchanges added (N from 1 to 100),
   * the session retains exactly min(N, SESSION_MAX_EXCHANGES) exchanges.
   */
  it('retains min(N, 50) exchanges for any N between 1 and 100', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 1, max: 100 }),
        async (n: number) => {
          const redis = new MockRedis();
          const manager = new RedisSessionManager(redis as any);
          const session = await manager.createSession('test-user');

          for (let i = 0; i < n; i++) {
            await manager.addExchange(session.id, createExchange(i));
          }

          const retrieved = await manager.getSession(session.id);
          const expectedCount = Math.min(n, SESSION_MAX_EXCHANGES);

          expect(retrieved).not.toBeNull();
          expect(retrieved!.exchanges.length).toBe(expectedCount);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 7.2**
   *
   * Property 2: For N > 50, the 50 most RECENT exchanges are retained
   * (oldest are evicted).
   */
  it('retains exactly the 50 most recent exchanges when N > 50', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: SESSION_MAX_EXCHANGES + 1, max: 150 }),
        async (n: number) => {
          const redis = new MockRedis();
          const manager = new RedisSessionManager(redis as any);
          const session = await manager.createSession('test-user');

          for (let i = 0; i < n; i++) {
            await manager.addExchange(session.id, createExchange(i));
          }

          const retrieved = await manager.getSession(session.id);
          expect(retrieved).not.toBeNull();
          expect(retrieved!.exchanges.length).toBe(SESSION_MAX_EXCHANGES);

          // The retained exchanges should be the last 50 (oldest evicted)
          const startIndex = n - SESSION_MAX_EXCHANGES;
          for (let i = 0; i < SESSION_MAX_EXCHANGES; i++) {
            expect(retrieved!.exchanges[i].userMessage).toBe(
              `user-message-${startIndex + i}`,
            );
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 7.2**
   *
   * Property 3: For N <= 50, ALL exchanges are retained (none evicted).
   */
  it('retains all exchanges when N <= 50', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 1, max: SESSION_MAX_EXCHANGES }),
        async (n: number) => {
          const redis = new MockRedis();
          const manager = new RedisSessionManager(redis as any);
          const session = await manager.createSession('test-user');

          for (let i = 0; i < n; i++) {
            await manager.addExchange(session.id, createExchange(i));
          }

          const retrieved = await manager.getSession(session.id);
          expect(retrieved).not.toBeNull();
          expect(retrieved!.exchanges.length).toBe(n);

          // Every exchange we added should be present
          for (let i = 0; i < n; i++) {
            expect(retrieved!.exchanges[i].userMessage).toBe(`user-message-${i}`);
            expect(retrieved!.exchanges[i].assistantResponse).toBe(
              `assistant-response-${i}`,
            );
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 7.2**
   *
   * Property 4: Exchange order is always preserved (no reordering)
   * regardless of how many exchanges are added.
   */
  it('preserves exchange order (no reordering) for any N', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 1, max: 100 }),
        async (n: number) => {
          const redis = new MockRedis();
          const manager = new RedisSessionManager(redis as any);
          const session = await manager.createSession('test-user');

          for (let i = 0; i < n; i++) {
            await manager.addExchange(session.id, createExchange(i));
          }

          const retrieved = await manager.getSession(session.id);
          expect(retrieved).not.toBeNull();

          const exchanges = retrieved!.exchanges;
          // Verify monotonically increasing order using timestamps
          for (let i = 1; i < exchanges.length; i++) {
            const prevTimestamp = exchanges[i - 1].timestamp.getTime();
            const currTimestamp = exchanges[i].timestamp.getTime();
            expect(currTimestamp).toBeGreaterThan(prevTimestamp);
          }

          // Also verify message indices are strictly increasing
          for (let i = 1; i < exchanges.length; i++) {
            const prevIndex = parseInt(
              exchanges[i - 1].userMessage.replace('user-message-', ''),
              10,
            );
            const currIndex = parseInt(
              exchanges[i].userMessage.replace('user-message-', ''),
              10,
            );
            expect(currIndex).toBeGreaterThan(prevIndex);
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});
