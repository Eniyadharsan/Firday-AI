/**
 * Property Test: Access Log Retention (Property 24)
 *
 * **Validates: Requirements 9.4**
 *
 * Generates log entries with various ages (0-200 days) and verifies:
 * - Entries younger than 90 days cannot be deleted (throws)
 * - Entries aged >= 90 days can be deleted successfully
 */

import { describe, it, expect } from 'vitest';
import fc from 'fast-check';
import { AccessLogger } from '../../src/services/access-logger';
import { ACCESS_LOG_RETENTION_DAYS } from '../../src/config/defaults';
import type { AccessLogEntry } from '../../src/models/entities';

/** Create a log entry with a specific age in days (relative to now) */
function createEntryWithAge(id: string, ageDays: number): AccessLogEntry {
  const now = new Date();
  const timestamp = new Date(now.getTime() - ageDays * 24 * 60 * 60 * 1000);
  return {
    id,
    timestamp,
    sourceIp: '192.168.1.1',
    method: 'api_key',
    success: true,
    userId: 'test-user',
  };
}

describe('Property 24: Access Log Retention', () => {
  /**
   * **Validates: Requirements 9.4**
   *
   * Entries younger than 90 days cannot be deleted — throws an error.
   */
  it('entries younger than 90 days cannot be deleted', () => {
    fc.assert(
      fc.property(
        fc.double({ min: 0, max: ACCESS_LOG_RETENTION_DAYS - 0.01, noNaN: true }),
        fc.uuid(),
        (ageDays, entryId) => {
          const logger = new AccessLogger();
          const entry = createEntryWithAge(entryId, ageDays);
          logger.logAttempt(entry);

          expect(() => logger.deleteEntry(entryId)).toThrow(/cannot delete|retention/i);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 9.4**
   *
   * Entries aged >= 90 days can be deleted successfully.
   */
  it('entries aged >= 90 days can be deleted', () => {
    fc.assert(
      fc.property(
        fc.double({ min: ACCESS_LOG_RETENTION_DAYS, max: 200, noNaN: true }),
        fc.uuid(),
        (ageDays, entryId) => {
          const logger = new AccessLogger();
          const entry = createEntryWithAge(entryId, ageDays);
          logger.logAttempt(entry);

          // Should not throw
          expect(() => logger.deleteEntry(entryId)).not.toThrow();

          // Entry should be removed
          const remaining = logger.getEntries();
          expect(remaining.find((e) => e.id === entryId)).toBeUndefined();
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 9.4**
   *
   * The retention period is exactly 90 days — boundary check.
   */
  it('retention boundary: exactly 90 days old can be deleted', () => {
    const logger = new AccessLogger();
    const entryId = 'boundary-entry';
    const entry = createEntryWithAge(entryId, ACCESS_LOG_RETENTION_DAYS);
    logger.logAttempt(entry);

    expect(() => logger.deleteEntry(entryId)).not.toThrow();
  });
});
