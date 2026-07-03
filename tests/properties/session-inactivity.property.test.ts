/**
 * Property 1: Session Inactivity Timeout
 *
 * For any active session and any silence duration, the system SHALL mark the
 * session as inactive and trigger a notification if and only if the silence
 * duration is greater than or equal to 60 seconds; otherwise the session
 * SHALL remain active.
 *
 * Feature: personal-ai-model, Property 1: Session Inactivity Timeout
 * **Validates: Requirements 1.3, 1.6**
 */

import { describe, it, expect, beforeEach } from 'vitest';
import * as fc from 'fast-check';
import { VoiceInterfaceService } from '../../src/services/voice-interface.js';
import { SESSION_SILENCE_TIMEOUT_SECONDS } from '../../src/config/defaults.js';

const SILENCE_TIMEOUT_MS = SESSION_SILENCE_TIMEOUT_SECONDS * 1000; // 60000ms

describe('Property 1: Session Inactivity Timeout', () => {
  let service: VoiceInterfaceService;

  beforeEach(() => {
    service = new VoiceInterfaceService();
  });

  it('should return session-end notification when silence duration >= 60 seconds', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 50 }),
        fc.integer({ min: SILENCE_TIMEOUT_MS, max: 120000 }),
        (sessionId, silenceDurationMs) => {
          service.startListening(sessionId);

          const result = service.handleSilenceDetected(sessionId, silenceDurationMs);

          expect(result).not.toBeNull();
          expect(result!.type).toBe('session-end');
          expect(result!.message).toBeTruthy();
        }
      ),
      { numRuns: 100 }
    );
  });

  it('should return null (session remains active) when silence duration < 60 seconds', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 50 }),
        fc.integer({ min: 0, max: SILENCE_TIMEOUT_MS - 1 }),
        (sessionId, silenceDurationMs) => {
          service.startListening(sessionId);

          const result = service.handleSilenceDetected(sessionId, silenceDurationMs);

          expect(result).toBeNull();

          // Verify session is still active
          const state = service.getListeningState(sessionId);
          expect(state).toBeDefined();
          expect(state!.isActive).toBe(true);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('should trigger session-end at exactly the 60-second boundary', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 50 }),
        (sessionId) => {
          service.startListening(sessionId);

          // Exactly at threshold should trigger session-end
          const resultAtBoundary = service.handleSilenceDetected(sessionId, SILENCE_TIMEOUT_MS);
          expect(resultAtBoundary).not.toBeNull();
          expect(resultAtBoundary!.type).toBe('session-end');

          // Re-create session to test just below threshold
          service.startListening(sessionId);
          const resultBelowBoundary = service.handleSilenceDetected(sessionId, SILENCE_TIMEOUT_MS - 1);
          expect(resultBelowBoundary).toBeNull();
        }
      ),
      { numRuns: 100 }
    );
  });

  it('should return null for inactive or non-existent sessions regardless of silence duration', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 50 }),
        fc.integer({ min: 0, max: 120000 }),
        (sessionId, silenceDurationMs) => {
          // Non-existent session should return null
          const resultNonExistent = service.handleSilenceDetected(sessionId, silenceDurationMs);
          expect(resultNonExistent).toBeNull();

          // Stopped session should also return null
          service.startListening(sessionId);
          service.stopListening(sessionId);
          const resultStopped = service.handleSilenceDetected(sessionId, silenceDurationMs);
          expect(resultStopped).toBeNull();
        }
      ),
      { numRuns: 100 }
    );
  });
});
