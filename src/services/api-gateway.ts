/**
 * API Gateway / Authentication Layer implementation.
 *
 * Provides API key authentication with timing-safe comparison,
 * failed attempt tracking per source IP, and automatic lockout
 * after repeated failures.
 *
 * Requirements: 8.5, 8.6, 9.6, 9.4
 */

import { createHash, timingSafeEqual } from 'node:crypto';
import { APIGateway, AuthResult, IncomingRequest } from '../interfaces/api-gateway.js';
import { AccessLogEntry } from '../models/entities.js';
import {
  AUTH_LOCKOUT_ATTEMPTS,
  AUTH_LOCKOUT_WINDOW_MINUTES,
  AUTH_LOCKOUT_DURATION_MINUTES,
} from '../config/defaults.js';

/** Record of a single failed authentication attempt */
interface FailedAttempt {
  timestamp: Date;
}

/** Tracking state for a source IP */
interface SourceTracker {
  failedAttempts: FailedAttempt[];
  lockedUntil: Date | null;
}

/**
 * Hash an API key using SHA-256 for secure storage comparison.
 * Plaintext keys are never stored.
 */
export function hashApiKey(key: string): string {
  return createHash('sha256').update(key).digest('hex');
}

/**
 * APIGatewayService implements the APIGateway interface with:
 * - Timing-safe API key validation
 * - Per-IP failed attempt tracking with timestamps
 * - Lockout after AUTH_LOCKOUT_ATTEMPTS consecutive failures within AUTH_LOCKOUT_WINDOW_MINUTES
 * - Lockout duration of AUTH_LOCKOUT_DURATION_MINUTES
 * - Access log recording for all authentication attempts
 */
export class APIGatewayService implements APIGateway {
  /** In-memory store of failed attempts keyed by source IP */
  private readonly sourceTrackers: Map<string, SourceTracker> = new Map();

  /** In-memory access log (append-only) */
  private readonly accessLog: AccessLogEntry[] = [];

  /** Set of valid API key hashes (SHA-256) */
  private readonly validKeyHashes: Map<string, string> = new Map();

  /**
   * Register a valid API key for a user.
   * The key is stored as a SHA-256 hash — plaintext is never retained.
   */
  registerApiKey(userId: string, plaintextKey: string): void {
    const hash = hashApiKey(plaintextKey);
    this.validKeyHashes.set(hash, userId);
  }

  /**
   * Authenticate an incoming request.
   *
   * Flow:
   * 1. Check if source IP is currently locked out
   * 2. Validate API key using timing-safe comparison
   * 3. On success: reset failure counter, log success
   * 4. On failure: record attempt, check for lockout trigger, log failure
   */
  async authenticate(request: IncomingRequest): Promise<AuthResult> {
    const { sourceIp, apiKey, timestamp } = request;

    // Check lockout first
    if (this.isBlocked(sourceIp)) {
      const logEntry = this.createLogEntry(sourceIp, 'api_key', false, undefined, 'Source is locked out');
      this.accessLog.push(logEntry);

      return {
        authenticated: false,
        userId: null,
        method: 'api_key',
        error: 'Too many failed attempts. Try again later.',
      };
    }

    // Validate API key
    if (!apiKey) {
      this.recordFailedAttempt(sourceIp, timestamp);
      const logEntry = this.createLogEntry(sourceIp, 'api_key', false, undefined, 'No API key provided');
      this.accessLog.push(logEntry);

      return {
        authenticated: false,
        userId: null,
        method: 'api_key',
        error: 'Authentication failed. Access denied.',
      };
    }

    const userId = this.validateApiKey(apiKey);

    if (userId) {
      // Success: reset consecutive failure counter
      this.resetFailedAttempts(sourceIp);
      const logEntry = this.createLogEntry(sourceIp, 'api_key', true, userId);
      this.accessLog.push(logEntry);

      return {
        authenticated: true,
        userId,
        method: 'api_key',
      };
    }

    // Failed authentication
    this.recordFailedAttempt(sourceIp, timestamp);
    const logEntry = this.createLogEntry(sourceIp, 'api_key', false, undefined, 'Invalid API key');
    this.accessLog.push(logEntry);

    return {
      authenticated: false,
      userId: null,
      method: 'api_key',
      error: 'Authentication failed. Access denied.',
    };
  }

  /**
   * Record a failed authentication attempt from a source.
   * Accepts an optional timestamp (defaults to now) for testability.
   */
  recordFailedAttempt(source: string, timestamp?: Date): void {
    const now = timestamp ?? new Date();
    let tracker = this.sourceTrackers.get(source);

    if (!tracker) {
      tracker = { failedAttempts: [], lockedUntil: null };
      this.sourceTrackers.set(source, tracker);
    }

    tracker.failedAttempts.push({ timestamp: now });

    // Prune attempts outside the lockout window
    const windowStart = new Date(now.getTime() - AUTH_LOCKOUT_WINDOW_MINUTES * 60 * 1000);
    tracker.failedAttempts = tracker.failedAttempts.filter(
      (attempt) => attempt.timestamp >= windowStart
    );

    // Check if lockout threshold is reached
    if (tracker.failedAttempts.length >= AUTH_LOCKOUT_ATTEMPTS) {
      tracker.lockedUntil = new Date(now.getTime() + AUTH_LOCKOUT_DURATION_MINUTES * 60 * 1000);
    }
  }

  /**
   * Check if a source IP is currently blocked due to lockout.
   */
  isBlocked(source: string): boolean {
    const tracker = this.sourceTrackers.get(source);
    if (!tracker || !tracker.lockedUntil) {
      return false;
    }

    const now = new Date();
    if (now >= tracker.lockedUntil) {
      // Lockout period has expired — reset
      tracker.lockedUntil = null;
      tracker.failedAttempts = [];
      return false;
    }

    return true;
  }

  /**
   * Get the access log entries (read-only copy).
   */
  getAccessLog(): ReadonlyArray<AccessLogEntry> {
    return [...this.accessLog];
  }

  /**
   * Get the lockout expiry time for a source, if any.
   */
  getLockoutExpiry(source: string): Date | null {
    const tracker = this.sourceTrackers.get(source);
    return tracker?.lockedUntil ?? null;
  }

  /**
   * Get the number of tracked failed attempts for a source within the window.
   */
  getFailedAttemptCount(source: string): number {
    const tracker = this.sourceTrackers.get(source);
    if (!tracker) return 0;

    const now = new Date();
    const windowStart = new Date(now.getTime() - AUTH_LOCKOUT_WINDOW_MINUTES * 60 * 1000);
    return tracker.failedAttempts.filter((a) => a.timestamp >= windowStart).length;
  }

  // --- Private helpers ---

  /**
   * Validate an API key using timing-safe comparison.
   * Returns the userId if valid, null otherwise.
   */
  private validateApiKey(apiKey: string): string | null {
    const incomingHash = hashApiKey(apiKey);
    const incomingBuffer = Buffer.from(incomingHash, 'hex');

    for (const [storedHash, userId] of this.validKeyHashes.entries()) {
      const storedBuffer = Buffer.from(storedHash, 'hex');

      if (incomingBuffer.length === storedBuffer.length && timingSafeEqual(incomingBuffer, storedBuffer)) {
        return userId;
      }
    }

    return null;
  }

  /**
   * Reset the failed attempt counter for a source (called on successful auth).
   */
  private resetFailedAttempts(source: string): void {
    const tracker = this.sourceTrackers.get(source);
    if (tracker) {
      tracker.failedAttempts = [];
      // Do not clear lockedUntil here — if they were blocked, the block already
      // prevents reaching this point (checked in authenticate()).
    }
  }

  /**
   * Create an access log entry.
   */
  private createLogEntry(
    sourceIp: string,
    method: 'api_key' | 'voice_biometric',
    success: boolean,
    userId?: string,
    failureReason?: string
  ): AccessLogEntry {
    return {
      id: crypto.randomUUID(),
      timestamp: new Date(),
      sourceIp,
      method,
      success,
      userId,
      failureReason,
    };
  }
}
