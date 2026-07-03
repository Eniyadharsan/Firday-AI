/**
 * Access Logger Service
 *
 * Logs all authentication attempts (success and failure) with timestamp,
 * source IP, method, and result. Enforces a minimum 90-day retention
 * policy and provides user-accessible query capabilities.
 *
 * Requirements: 9.4
 */

import { AccessLogEntry } from '../models/entities.js';
import { ACCESS_LOG_RETENTION_DAYS } from '../config/defaults.js';

/** Filter options for querying access log entries */
export interface AccessLogFilters {
  userId?: string;
  startDate?: Date;
  endDate?: Date;
  method?: 'api_key' | 'voice_biometric';
  success?: boolean;
}

/**
 * AccessLogger manages an append-only store of authentication attempts.
 * Entries younger than 90 days cannot be deleted (retention enforcement).
 */
export class AccessLogger {
  private entries: AccessLogEntry[] = [];

  /**
   * Append a new authentication attempt entry to the log store.
   * Entries are immutable once written.
   */
  logAttempt(entry: AccessLogEntry): void {
    this.entries.push({ ...entry });
  }

  /**
   * Query log entries with optional filters.
   * Provides user-accessible access to their authentication history.
   */
  getEntries(filters?: AccessLogFilters): AccessLogEntry[] {
    if (!filters) {
      return [...this.entries];
    }

    return this.entries.filter((entry) => {
      if (filters.userId !== undefined && entry.userId !== filters.userId) {
        return false;
      }
      if (filters.startDate !== undefined && entry.timestamp < filters.startDate) {
        return false;
      }
      if (filters.endDate !== undefined && entry.timestamp > filters.endDate) {
        return false;
      }
      if (filters.method !== undefined && entry.method !== filters.method) {
        return false;
      }
      if (filters.success !== undefined && entry.success !== filters.success) {
        return false;
      }
      return true;
    });
  }

  /**
   * Attempt to delete a log entry by ID.
   * Throws an error if the entry is younger than 90 days (retention enforcement).
   * Allows deletion only for entries that are >= 90 days old.
   */
  deleteEntry(entryId: string): void {
    const entryIndex = this.entries.findIndex((e) => e.id === entryId);

    if (entryIndex === -1) {
      throw new Error(`Access log entry not found: ${entryId}`);
    }

    const entry = this.entries[entryIndex]!;
    const ageInDays = this.getEntryAgeDays(entry);

    if (ageInDays < ACCESS_LOG_RETENTION_DAYS) {
      throw new Error(
        `Cannot delete access log entry "${entryId}": entry is ${Math.floor(ageInDays)} days old, ` +
        `minimum retention period is ${ACCESS_LOG_RETENTION_DAYS} days`
      );
    }

    this.entries.splice(entryIndex, 1);
  }

  /**
   * Returns the configured retention period in days.
   */
  getRetentionDays(): number {
    return ACCESS_LOG_RETENTION_DAYS;
  }

  /**
   * Remove all entries older than the retention period.
   * Returns the number of entries pruned.
   */
  pruneExpiredEntries(): number {
    const now = new Date();
    const retentionMs = ACCESS_LOG_RETENTION_DAYS * 24 * 60 * 60 * 1000;
    const cutoff = new Date(now.getTime() - retentionMs);

    const originalLength = this.entries.length;
    this.entries = this.entries.filter((entry) => entry.timestamp >= cutoff);

    return originalLength - this.entries.length;
  }

  /**
   * Get the total number of log entries currently stored.
   */
  getEntryCount(): number {
    return this.entries.length;
  }

  /**
   * Calculate the age of an entry in days from now.
   */
  private getEntryAgeDays(entry: AccessLogEntry): number {
    const now = new Date();
    const ageMs = now.getTime() - entry.timestamp.getTime();
    return ageMs / (24 * 60 * 60 * 1000);
  }
}
