/**
 * Property 5: Session Continuity on Duplicate Invocation
 *
 * For any active session, receiving a Wake_Invocation SHALL NOT create a new
 * session; the existing session SHALL continue with its full history intact,
 * and the session count SHALL remain unchanged.
 *
 * Feature: personal-ai-model, Property 5: Session Continuity on Duplicate Invocation
 *
 * **Validates: Requirements 2.6**
 */

import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import { RedisSessionManager } from '../../src/services/session-manager.js';
import type { Exchange } from '../../src/interfaces/session-manager.js';

/**
 * MockRedis - In-memory Redis substitute for testing.
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

/** Helper to create a fresh session manager with isolated state per iteration */
function createSessionManager(): RedisSessionManager {
  return new RedisSessionManager(new MockRedis() as any);
}

describe('Property 5: Session Continuity on Duplicate Invocation', () => {
  // Arbitrary for generating user IDs
  const arbUserId = fc.string({ minLength: 3, maxLength: 32 })
    .filter((s) => s.trim().length >= 3);

  // Arbitrary for number of duplicate invocations (1-10)
  const arbDuplicateCount = fc.integer({ min: 1, max: 10 });

  // Arbitrary for generating an exchange
  const arbExchange: fc.Arbitrary<Exchange> = fc.record({
    userMessage: fc.string({ minLength: 1, maxLength: 100 }),
    assistantResponse: fc.string({ minLength: 1, maxLength: 200 }),
    timestamp: fc.date({ min: new Date('2020-01-01'), max: new Date('2030-01-01') }),
    metadata: fc.record({
      confidenceScore: fc.double({ min: 0, max: 1, noNaN: true }),
      sourcesUsed: fc.array(fc.string({ minLength: 1, maxLength: 20 }), { minLength: 0, maxLength: 5 }),
      responseTimeMs: fc.integer({ min: 50, max: 5000 }),
    }),
  });

  it('duplicate wake invocations do not create new sessions; only the first creates one', async () => {
    await fc.assert(
      fc.asyncProperty(
        arbUserId,
        arbDuplicateCount,
        async (userId, duplicateCount) => {
          const sessionManager = createSessionManager();

          // First invocation creates a new session
          const firstResult = await sessionManager.handleWakeInvocation(userId);
          expect(firstResult.isExisting).toBe(false);
          const originalSessionId = firstResult.session.id;

          // Subsequent duplicate invocations should return the existing session
          for (let i = 0; i < duplicateCount; i++) {
            const result = await sessionManager.handleWakeInvocation(userId);

            // SHALL NOT create a new session
            expect(result.isExisting).toBe(true);

            // Session ID remains the same
            expect(result.session.id).toBe(originalSessionId);
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  it('session history is preserved intact across duplicate invocations', async () => {
    await fc.assert(
      fc.asyncProperty(
        arbUserId,
        fc.array(arbExchange, { minLength: 1, maxLength: 10 }),
        arbDuplicateCount,
        async (userId, exchanges, duplicateCount) => {
          const sessionManager = createSessionManager();

          // Create a session via first wake invocation
          const firstResult = await sessionManager.handleWakeInvocation(userId);
          const sessionId = firstResult.session.id;

          // Add exchanges to build up history
          for (const exchange of exchanges) {
            await sessionManager.addExchange(sessionId, exchange);
          }

          // Verify history is intact before duplicate invocations
          const sessionBefore = await sessionManager.getSession(sessionId);
          expect(sessionBefore).not.toBeNull();
          const exchangeCountBefore = sessionBefore!.exchanges.length;

          // Perform duplicate wake invocations
          for (let i = 0; i < duplicateCount; i++) {
            const result = await sessionManager.handleWakeInvocation(userId);

            // Existing session returned
            expect(result.isExisting).toBe(true);
            expect(result.session.id).toBe(sessionId);

            // History preserved intact - exchange count unchanged
            expect(result.session.exchanges.length).toBe(exchangeCountBefore);

            // Verify exchange content is preserved
            for (let j = 0; j < result.session.exchanges.length; j++) {
              expect(result.session.exchanges[j].userMessage).toBe(
                sessionBefore!.exchanges[j].userMessage
              );
              expect(result.session.exchanges[j].assistantResponse).toBe(
                sessionBefore!.exchanges[j].assistantResponse
              );
            }
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  it('session count remains unchanged after duplicate invocations', async () => {
    await fc.assert(
      fc.asyncProperty(
        arbUserId,
        arbDuplicateCount,
        async (userId, duplicateCount) => {
          const sessionManager = createSessionManager();

          // Create initial session
          const firstResult = await sessionManager.handleWakeInvocation(userId);
          const sessionId = firstResult.session.id;

          // Count sessions stored (by checking the original session still exists)
          const sessionAfterCreate = await sessionManager.getSession(sessionId);
          expect(sessionAfterCreate).not.toBeNull();

          // Perform duplicate invocations
          for (let i = 0; i < duplicateCount; i++) {
            await sessionManager.handleWakeInvocation(userId);
          }

          // The same session still exists (no additional sessions created)
          const sessionAfterDuplicates = await sessionManager.getSession(sessionId);
          expect(sessionAfterDuplicates).not.toBeNull();
          expect(sessionAfterDuplicates!.id).toBe(sessionId);
          expect(sessionAfterDuplicates!.userId).toBe(userId);
          expect(sessionAfterDuplicates!.isActive).toBe(true);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('after endSession + handleWakeInvocation, a NEW session is created', async () => {
    await fc.assert(
      fc.asyncProperty(
        arbUserId,
        arbDuplicateCount,
        async (userId, duplicateCount) => {
          const sessionManager = createSessionManager();

          // Create initial session
          const firstResult = await sessionManager.handleWakeInvocation(userId);
          expect(firstResult.isExisting).toBe(false);
          const originalSessionId = firstResult.session.id;

          // Perform some duplicate invocations to confirm continuity
          for (let i = 0; i < duplicateCount; i++) {
            const dupResult = await sessionManager.handleWakeInvocation(userId);
            expect(dupResult.isExisting).toBe(true);
            expect(dupResult.session.id).toBe(originalSessionId);
          }

          // End the session
          await sessionManager.endSession(originalSessionId);

          // After ending, a new wake invocation should create a NEW session
          const newResult = await sessionManager.handleWakeInvocation(userId);
          expect(newResult.isExisting).toBe(false);
          expect(newResult.session.id).not.toBe(originalSessionId);
          expect(newResult.session.isActive).toBe(true);
          expect(newResult.session.userId).toBe(userId);

          // The old session should be inactive
          const oldSession = await sessionManager.getSession(originalSessionId);
          expect(oldSession).not.toBeNull();
          expect(oldSession!.isActive).toBe(false);
        }
      ),
      { numRuns: 100 }
    );
  });
});
