/**
 * Unit tests for AccessLogger service.
 *
 * Tests cover:
 * - Logging authentication attempts (success and failure) — Requirement 9.4
 * - Retention enforcement (entries < 90 days cannot be deleted) — Requirement 9.4
 * - Query filtering (by userId, date range, method, success) — Requirement 9.4
 * - Pruning expired entries — Requirement 9.4
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { AccessLogger } from '../../src/services/access-logger.js';
import type { AccessLogEntry } from '../../src/models/entities.js';
import { ACCESS_LOG_RETENTION_DAYS } from '../../src/config/defaults.js';

function makeEntry(overrides: Partial<AccessLogEntry> = {}): AccessLogEntry {
  return {
    id: 'entry-1',
    timestamp: new Date(),
    sourceIp: '192.168.1.1',
    method: 'api_key',
    success: true,
    userId: 'user-1',
    ...overrides,
  };
}

/** Create a date that is N days in the past from now */
function daysAgo(days: number): Date {
  return new Date(Date.now() - days * 24 * 60 * 60 * 1000);
}

describe('AccessLogger', () => {
  let logger: AccessLogger;

  beforeEach(() => {
    logger = new AccessLogger();
  });

  describe('logAttempt', () => {
    it('should log a successful authentication attempt', () => {
      const entry = makeEntry({ success: true });
      logger.logAttempt(entry);

      const entries = logger.getEntries();
      expect(entries).toHaveLength(1);
      expect(entries[0].success).toBe(true);
      expect(entries[0].sourceIp).toBe('192.168.1.1');
      expect(entries[0].method).toBe('api_key');
    });

    it('should log a failed authentication attempt', () => {
      const entry = makeEntry({
        id: 'entry-fail',
        success: false,
        failureReason: 'Invalid API key',
      });
      logger.logAttempt(entry);

      const entries = logger.getEntries();
      expect(entries).toHaveLength(1);
      expect(entries[0].success).toBe(false);
      expect(entries[0].failureReason).toBe('Invalid API key');
    });

    it('should append multiple entries in order', () => {
      logger.logAttempt(makeEntry({ id: 'e1', timestamp: new Date('2024-01-01') }));
      logger.logAttempt(makeEntry({ id: 'e2', timestamp: new Date('2024-01-02') }));
      logger.logAttempt(makeEntry({ id: 'e3', timestamp: new Date('2024-01-03') }));

      const entries = logger.getEntries();
      expect(entries).toHaveLength(3);
      expect(entries[0].id).toBe('e1');
      expect(entries[1].id).toBe('e2');
      expect(entries[2].id).toBe('e3');
    });

    it('should store all required fields: timestamp, sourceIp, method, result', () => {
      const entry = makeEntry({
        id: 'full-entry',
        timestamp: new Date('2024-06-15T10:30:00Z'),
        sourceIp: '10.0.0.5',
        method: 'voice_biometric',
        success: false,
        userId: 'user-42',
        failureReason: 'Voice mismatch',
      });
      logger.logAttempt(entry);

      const stored = logger.getEntries()[0];
      expect(stored.id).toBe('full-entry');
      expect(stored.timestamp).toEqual(new Date('2024-06-15T10:30:00Z'));
      expect(stored.sourceIp).toBe('10.0.0.5');
      expect(stored.method).toBe('voice_biometric');
      expect(stored.success).toBe(false);
      expect(stored.userId).toBe('user-42');
      expect(stored.failureReason).toBe('Voice mismatch');
    });

    it('should not allow mutation of logged entry via external reference', () => {
      const entry = makeEntry({ id: 'immutable' });
      logger.logAttempt(entry);

      // Mutate the original object
      entry.sourceIp = 'MUTATED';

      const stored = logger.getEntries()[0];
      expect(stored.sourceIp).toBe('192.168.1.1');
    });
  });

  describe('getEntries (query filtering)', () => {
    beforeEach(() => {
      logger.logAttempt(makeEntry({
        id: 'e1', userId: 'user-1', method: 'api_key', success: true,
        timestamp: new Date('2024-03-01'),
      }));
      logger.logAttempt(makeEntry({
        id: 'e2', userId: 'user-2', method: 'voice_biometric', success: false,
        timestamp: new Date('2024-03-15'),
      }));
      logger.logAttempt(makeEntry({
        id: 'e3', userId: 'user-1', method: 'api_key', success: false,
        timestamp: new Date('2024-04-01'),
      }));
      logger.logAttempt(makeEntry({
        id: 'e4', userId: 'user-1', method: 'voice_biometric', success: true,
        timestamp: new Date('2024-04-15'),
      }));
    });

    it('should return all entries when no filters are provided', () => {
      const entries = logger.getEntries();
      expect(entries).toHaveLength(4);
    });

    it('should filter by userId', () => {
      const entries = logger.getEntries({ userId: 'user-1' });
      expect(entries).toHaveLength(3);
      expect(entries.every((e) => e.userId === 'user-1')).toBe(true);
    });

    it('should filter by startDate', () => {
      const entries = logger.getEntries({ startDate: new Date('2024-03-10') });
      expect(entries).toHaveLength(3);
      expect(entries[0].id).toBe('e2');
    });

    it('should filter by endDate', () => {
      const entries = logger.getEntries({ endDate: new Date('2024-03-20') });
      expect(entries).toHaveLength(2);
      expect(entries[0].id).toBe('e1');
      expect(entries[1].id).toBe('e2');
    });

    it('should filter by date range (startDate and endDate)', () => {
      const entries = logger.getEntries({
        startDate: new Date('2024-03-10'),
        endDate: new Date('2024-04-05'),
      });
      expect(entries).toHaveLength(2);
      expect(entries[0].id).toBe('e2');
      expect(entries[1].id).toBe('e3');
    });

    it('should filter by method', () => {
      const entries = logger.getEntries({ method: 'voice_biometric' });
      expect(entries).toHaveLength(2);
      expect(entries.every((e) => e.method === 'voice_biometric')).toBe(true);
    });

    it('should filter by success status', () => {
      const entries = logger.getEntries({ success: false });
      expect(entries).toHaveLength(2);
      expect(entries.every((e) => e.success === false)).toBe(true);
    });

    it('should combine multiple filters', () => {
      const entries = logger.getEntries({
        userId: 'user-1',
        method: 'api_key',
        success: false,
      });
      expect(entries).toHaveLength(1);
      expect(entries[0].id).toBe('e3');
    });

    it('should return empty array when no entries match filters', () => {
      const entries = logger.getEntries({ userId: 'non-existent' });
      expect(entries).toHaveLength(0);
    });
  });

  describe('deleteEntry (retention enforcement)', () => {
    it('should reject deletion of entries younger than 90 days', () => {
      const recentEntry = makeEntry({
        id: 'recent',
        timestamp: daysAgo(30), // 30 days old
      });
      logger.logAttempt(recentEntry);

      expect(() => logger.deleteEntry('recent')).toThrow(
        /Cannot delete access log entry/
      );
      expect(logger.getEntryCount()).toBe(1);
    });

    it('should reject deletion of entries exactly at the boundary (89 days)', () => {
      const entry = makeEntry({
        id: 'boundary',
        timestamp: daysAgo(89),
      });
      logger.logAttempt(entry);

      expect(() => logger.deleteEntry('boundary')).toThrow(
        /Cannot delete access log entry/
      );
    });

    it('should allow deletion of entries older than 90 days', () => {
      const oldEntry = makeEntry({
        id: 'old-entry',
        timestamp: daysAgo(91), // 91 days old
      });
      logger.logAttempt(oldEntry);

      logger.deleteEntry('old-entry');
      expect(logger.getEntryCount()).toBe(0);
    });

    it('should allow deletion of entries exactly at 90 days', () => {
      const entry = makeEntry({
        id: 'exactly-90',
        timestamp: daysAgo(90),
      });
      logger.logAttempt(entry);

      logger.deleteEntry('exactly-90');
      expect(logger.getEntryCount()).toBe(0);
    });

    it('should throw when entry ID is not found', () => {
      expect(() => logger.deleteEntry('nonexistent')).toThrow(
        /Access log entry not found/
      );
    });

    it('should include retention days in error message', () => {
      const entry = makeEntry({ id: 'young', timestamp: daysAgo(10) });
      logger.logAttempt(entry);

      expect(() => logger.deleteEntry('young')).toThrow(/90 days/);
    });
  });

  describe('getRetentionDays', () => {
    it('should return 90 as the retention period', () => {
      expect(logger.getRetentionDays()).toBe(90);
      expect(logger.getRetentionDays()).toBe(ACCESS_LOG_RETENTION_DAYS);
    });
  });

  describe('pruneExpiredEntries', () => {
    it('should remove entries older than 90 days', () => {
      logger.logAttempt(makeEntry({ id: 'old', timestamp: daysAgo(100) }));
      logger.logAttempt(makeEntry({ id: 'recent', timestamp: daysAgo(10) }));

      const pruned = logger.pruneExpiredEntries();

      expect(pruned).toBe(1);
      expect(logger.getEntryCount()).toBe(1);
      expect(logger.getEntries()[0].id).toBe('recent');
    });

    it('should not remove entries within retention period', () => {
      logger.logAttempt(makeEntry({ id: 'e1', timestamp: daysAgo(30) }));
      logger.logAttempt(makeEntry({ id: 'e2', timestamp: daysAgo(60) }));
      logger.logAttempt(makeEntry({ id: 'e3', timestamp: daysAgo(89) }));

      const pruned = logger.pruneExpiredEntries();

      expect(pruned).toBe(0);
      expect(logger.getEntryCount()).toBe(3);
    });

    it('should return 0 when no entries exist', () => {
      const pruned = logger.pruneExpiredEntries();
      expect(pruned).toBe(0);
    });

    it('should remove all entries when all are expired', () => {
      logger.logAttempt(makeEntry({ id: 'e1', timestamp: daysAgo(91) }));
      logger.logAttempt(makeEntry({ id: 'e2', timestamp: daysAgo(120) }));
      logger.logAttempt(makeEntry({ id: 'e3', timestamp: daysAgo(200) }));

      const pruned = logger.pruneExpiredEntries();

      expect(pruned).toBe(3);
      expect(logger.getEntryCount()).toBe(0);
    });
  });

  describe('getEntryCount', () => {
    it('should return 0 for empty logger', () => {
      expect(logger.getEntryCount()).toBe(0);
    });

    it('should return correct count after logging entries', () => {
      logger.logAttempt(makeEntry({ id: 'e1' }));
      logger.logAttempt(makeEntry({ id: 'e2' }));
      expect(logger.getEntryCount()).toBe(2);
    });
  });
});
