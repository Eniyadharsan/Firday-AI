/**
 * Property 26: Authentication Lockout Logic
 *
 * For any source IP, if 5 consecutive failed authentication attempts occur within
 * a 10-minute window, the system SHALL block all further attempts from that source
 * for at least 15 minutes; fewer than 5 consecutive failures within 10 minutes
 * SHALL NOT trigger lockout; a successful attempt SHALL reset the consecutive
 * failure count.
 *
 * Feature: personal-ai-model, Property 26: Authentication Lockout Logic
 * **Validates: Requirements 9.6**
 */

import { describe, it, expect, beforeEach } from 'vitest';
import * as fc from 'fast-check';
import { APIGatewayService } from '../../src/services/api-gateway.js';
import {
  AUTH_LOCKOUT_ATTEMPTS,
  AUTH_LOCKOUT_WINDOW_MINUTES,
  AUTH_LOCKOUT_DURATION_MINUTES,
} from '../../src/config/defaults.js';

describe('Property 26: Authentication Lockout Logic', () => {
  let gateway: APIGatewayService;

  beforeEach(() => {
    gateway = new APIGatewayService();
  });

  it('should trigger lockout after exactly 5 consecutive failures within 10-minute window', () => {
    fc.assert(
      fc.property(
        // Generate a base timestamp and offsets within the 10-minute window
        fc.date({ min: new Date('2020-01-01'), max: new Date('2030-01-01') }),
        fc.array(
          fc.integer({ min: 0, max: AUTH_LOCKOUT_WINDOW_MINUTES * 60 * 1000 - 1 }),
          { minLength: AUTH_LOCKOUT_ATTEMPTS, maxLength: AUTH_LOCKOUT_ATTEMPTS }
        ),
        fc.string({ minLength: 1, maxLength: 50 }),
        (baseTime, offsets, sourceIp) => {
          const service = new APIGatewayService();

          // Sort offsets to ensure timestamps are in chronological order
          const sortedOffsets = [...offsets].sort((a, b) => a - b);

          // Record exactly 5 failures within the window
          for (let i = 0; i < AUTH_LOCKOUT_ATTEMPTS; i++) {
            const timestamp = new Date(baseTime.getTime() + sortedOffsets[i]);
            service.recordFailedAttempt(sourceIp, timestamp);
          }

          // After 5 consecutive failures within the window, source should be blocked
          // We need to check isBlocked at a time that's within the lockout duration
          // Mock Date.now to be right after the last failure
          const lastFailureTime = new Date(
            baseTime.getTime() + sortedOffsets[AUTH_LOCKOUT_ATTEMPTS - 1]
          );
          const checkTime = new Date(lastFailureTime.getTime() + 1000); // 1 second after

          // Override Date to check blocking at the right time
          const originalNow = Date.now;
          Date.now = () => checkTime.getTime();
          const originalDate = globalThis.Date;
          globalThis.Date = class extends originalDate {
            constructor(...args: any[]) {
              if (args.length === 0) {
                super(checkTime.getTime());
              } else {
                // @ts-ignore
                super(...args);
              }
            }
            static now() { return checkTime.getTime(); }
          } as any;

          try {
            expect(service.isBlocked(sourceIp)).toBe(true);
          } finally {
            globalThis.Date = originalDate;
            Date.now = originalNow;
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  it('should NOT trigger lockout with fewer than 5 consecutive failures within 10 minutes', () => {
    fc.assert(
      fc.property(
        fc.date({ min: new Date('2020-01-01'), max: new Date('2030-01-01') }),
        fc.integer({ min: 1, max: AUTH_LOCKOUT_ATTEMPTS - 1 }),
        fc.string({ minLength: 1, maxLength: 50 }),
        (baseTime, numFailures, sourceIp) => {
          const service = new APIGatewayService();

          // Record fewer than 5 failures, all within the window
          for (let i = 0; i < numFailures; i++) {
            const timestamp = new Date(baseTime.getTime() + i * 60000); // 1 min apart
            service.recordFailedAttempt(sourceIp, timestamp);
          }

          // Check at a time shortly after last failure
          const checkTime = new Date(baseTime.getTime() + numFailures * 60000 + 1000);
          const originalDate = globalThis.Date;
          globalThis.Date = class extends originalDate {
            constructor(...args: any[]) {
              if (args.length === 0) {
                super(checkTime.getTime());
              } else {
                // @ts-ignore
                super(...args);
              }
            }
            static now() { return checkTime.getTime(); }
          } as any;

          try {
            expect(service.isBlocked(sourceIp)).toBe(false);
          } finally {
            globalThis.Date = originalDate;
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  it('should reset failure counter on successful authentication', () => {
    fc.assert(
      fc.asyncProperty(
        fc.date({ min: new Date('2020-01-01'), max: new Date('2030-01-01') }),
        fc.integer({ min: 1, max: AUTH_LOCKOUT_ATTEMPTS - 1 }),
        fc.string({ minLength: 1, maxLength: 50 }),
        fc.string({ minLength: 8, maxLength: 32 }),
        async (baseTime, failuresBeforeSuccess, sourceIp, apiKey) => {
          const service = new APIGatewayService();

          // Register a valid API key
          service.registerApiKey('test-user', apiKey);

          // Record some failures (fewer than lockout threshold)
          for (let i = 0; i < failuresBeforeSuccess; i++) {
            const timestamp = new Date(baseTime.getTime() + i * 60000);
            service.recordFailedAttempt(sourceIp, timestamp);
          }

          // Perform a successful authentication to reset the counter
          const successTime = new Date(
            baseTime.getTime() + failuresBeforeSuccess * 60000 + 1000
          );
          await service.authenticate({
            sourceIp,
            apiKey,
            timestamp: successTime,
          });

          // Now record more failures (up to threshold minus 1) - should NOT lockout
          // because counter was reset by the success
          for (let i = 0; i < AUTH_LOCKOUT_ATTEMPTS - 1; i++) {
            const timestamp = new Date(successTime.getTime() + (i + 1) * 60000);
            service.recordFailedAttempt(sourceIp, timestamp);
          }

          // Check at a time shortly after last failure
          const checkTime = new Date(
            successTime.getTime() + AUTH_LOCKOUT_ATTEMPTS * 60000
          );
          const originalDate = globalThis.Date;
          globalThis.Date = class extends originalDate {
            constructor(...args: any[]) {
              if (args.length === 0) {
                super(checkTime.getTime());
              } else {
                // @ts-ignore
                super(...args);
              }
            }
            static now() { return checkTime.getTime(); }
          } as any;

          try {
            expect(service.isBlocked(sourceIp)).toBe(false);
          } finally {
            globalThis.Date = originalDate;
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  it('should maintain lockout for at least 15 minutes after triggering', () => {
    fc.assert(
      fc.property(
        fc.date({ min: new Date('2020-01-01'), max: new Date('2030-01-01') }),
        fc.integer({ min: 0, max: AUTH_LOCKOUT_DURATION_MINUTES * 60 * 1000 - 1000 }),
        fc.string({ minLength: 1, maxLength: 50 }),
        (baseTime, elapsedAfterLockout, sourceIp) => {
          const service = new APIGatewayService();

          // Trigger lockout: 5 consecutive failures within 10-minute window
          for (let i = 0; i < AUTH_LOCKOUT_ATTEMPTS; i++) {
            const timestamp = new Date(baseTime.getTime() + i * 1000); // 1 second apart
            service.recordFailedAttempt(sourceIp, timestamp);
          }

          // The lockout was triggered at the last failure time
          const lockoutTriggerTime = new Date(
            baseTime.getTime() + (AUTH_LOCKOUT_ATTEMPTS - 1) * 1000
          );

          // Check at various times BEFORE 15 minutes have elapsed
          // elapsedAfterLockout is guaranteed < 15 minutes (in ms)
          const checkTime = new Date(lockoutTriggerTime.getTime() + elapsedAfterLockout);

          const originalDate = globalThis.Date;
          globalThis.Date = class extends originalDate {
            constructor(...args: any[]) {
              if (args.length === 0) {
                super(checkTime.getTime());
              } else {
                // @ts-ignore
                super(...args);
              }
            }
            static now() { return checkTime.getTime(); }
          } as any;

          try {
            expect(service.isBlocked(sourceIp)).toBe(true);
          } finally {
            globalThis.Date = originalDate;
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  it('should NOT trigger lockout when failures are spread outside 10-minute window', () => {
    fc.assert(
      fc.property(
        fc.date({ min: new Date('2020-01-01'), max: new Date('2030-01-01') }),
        fc.string({ minLength: 1, maxLength: 50 }),
        (baseTime, sourceIp) => {
          const service = new APIGatewayService();

          // Record 5 failures but spread over MORE than 10 minutes
          // The first failure is at baseTime, each subsequent one is
          // more than 2.5 minutes apart so that no 5 fit within 10 minutes
          const spreadMs = (AUTH_LOCKOUT_WINDOW_MINUTES * 60 * 1000) / (AUTH_LOCKOUT_ATTEMPTS - 1) + 1000;

          for (let i = 0; i < AUTH_LOCKOUT_ATTEMPTS; i++) {
            const timestamp = new Date(baseTime.getTime() + i * spreadMs);
            service.recordFailedAttempt(sourceIp, timestamp);
          }

          // Check after the last failure
          const lastFailureTime = new Date(
            baseTime.getTime() + (AUTH_LOCKOUT_ATTEMPTS - 1) * spreadMs
          );
          const checkTime = new Date(lastFailureTime.getTime() + 1000);

          const originalDate = globalThis.Date;
          globalThis.Date = class extends originalDate {
            constructor(...args: any[]) {
              if (args.length === 0) {
                super(checkTime.getTime());
              } else {
                // @ts-ignore
                super(...args);
              }
            }
            static now() { return checkTime.getTime(); }
          } as any;

          try {
            expect(service.isBlocked(sourceIp)).toBe(false);
          } finally {
            globalThis.Date = originalDate;
          }
        }
      ),
      { numRuns: 100 }
    );
  });
});
