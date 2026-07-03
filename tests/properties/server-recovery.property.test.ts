/**
 * Property Test: Server Recovery Retry Logic (Property 4)
 *
 * **Validates: Requirements 2.3**
 *
 * Generates sequences of recovery attempts (success/failure) and verifies:
 * - Retries up to 3 times
 * - Resumes (success) if any attempt succeeds
 * - Notifies user if all 3 attempts fail
 */

import { describe, it, expect } from 'vitest';
import fc from 'fast-check';
import { HealthManager } from '../../src/services/health-manager';
import { RECOVERY_MAX_RETRIES } from '../../src/config/defaults';

describe('Property 4: Server Recovery Retry Logic', () => {
  /**
   * **Validates: Requirements 2.3**
   *
   * If the first attempt succeeds, recovery succeeds with 1 attempt.
   */
  it('resumes immediately on first successful attempt', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.string({ minLength: 3, maxLength: 20 }),
        async (serviceName) => {
          const manager = new HealthManager();

          // Restart function always succeeds
          const restartFn = async () => true;

          const result = await manager.attemptRecovery(serviceName, restartFn);

          expect(result.success).toBe(true);
          expect(result.attempts).toBe(1);
          expect(result.recoveredAt).toBeInstanceOf(Date);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 2.3**
   *
   * Recovery succeeds if any attempt (1st, 2nd, or 3rd) succeeds.
   * The attempt count reflects which attempt succeeded.
   */
  it('resumes if any of the 3 attempts succeeds', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.string({ minLength: 3, maxLength: 20 }),
        fc.integer({ min: 1, max: RECOVERY_MAX_RETRIES }),
        async (serviceName, successAtAttempt) => {
          const manager = new HealthManager();

          let attemptCount = 0;
          const restartFn = async () => {
            attemptCount++;
            return attemptCount >= successAtAttempt;
          };

          const result = await manager.attemptRecovery(serviceName, restartFn);

          expect(result.success).toBe(true);
          expect(result.attempts).toBe(successAtAttempt);
          expect(result.recoveredAt).toBeInstanceOf(Date);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 2.3**
   *
   * If all 3 attempts fail, recovery fails and user is notified
   * of temporary unavailability.
   */
  it('notifies user when all recovery attempts fail', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.string({ minLength: 3, maxLength: 20 }),
        async (serviceName) => {
          const manager = new HealthManager();

          // Restart function always fails
          const restartFn = async () => false;

          const result = await manager.attemptRecovery(serviceName, restartFn);

          expect(result.success).toBe(false);
          expect(result.attempts).toBe(RECOVERY_MAX_RETRIES);
          expect(result.error).toBeDefined();
          expect(result.error).toContain('temporarily unavailable');

          // Notification should be emitted
          const notifications = manager.getNotifications();
          expect(notifications.length).toBeGreaterThanOrEqual(1);
          expect(notifications[notifications.length - 1]).toContain(serviceName);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 2.3**
   *
   * Recovery never exceeds 3 total attempts regardless of outcome sequence.
   */
  it('never exceeds 3 total attempts', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.string({ minLength: 3, maxLength: 20 }),
        fc.array(fc.boolean(), { minLength: 3, maxLength: 3 }),
        async (serviceName, outcomes) => {
          const manager = new HealthManager();

          let attemptCount = 0;
          const restartFn = async () => {
            const result = outcomes[attemptCount] ?? false;
            attemptCount++;
            return result;
          };

          const result = await manager.attemptRecovery(serviceName, restartFn);

          expect(result.attempts).toBeLessThanOrEqual(RECOVERY_MAX_RETRIES);
        },
      ),
      { numRuns: 100 },
    );
  });
});
