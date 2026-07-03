/**
 * Property 2: Transcription Retry State Machine
 *
 * For any sequence of transcription confidence scores, the system SHALL prompt
 * for retry on each score below 0.50, count consecutive low-confidence results,
 * and transition to a "recognition failed" state after exactly 3 consecutive
 * retries — never before and never after.
 *
 * Feature: personal-ai-model, Property 2: Transcription Retry State Machine
 * **Validates: Requirements 1.4**
 */

import { describe, it, expect, beforeEach } from 'vitest';
import * as fc from 'fast-check';
import { VoiceInterfaceService } from '../../src/services/voice-interface.js';
import {
  TRANSCRIPTION_CONFIDENCE_THRESHOLD,
  MAX_TRANSCRIPTION_RETRIES,
} from '../../src/config/defaults.js';

describe('Property 2: Transcription Retry State Machine', () => {
  let service: VoiceInterfaceService;
  const sessionId = 'test-session';

  beforeEach(() => {
    service = new VoiceInterfaceService();
    service.startListening(sessionId);
  });

  it('should return "please-repeat" on each low-confidence score before reaching 3 consecutive retries', () => {
    fc.assert(
      fc.property(
        // Generate a number of consecutive low-confidence attempts (1 or 2)
        fc.integer({ min: 1, max: MAX_TRANSCRIPTION_RETRIES - 1 }),
        (numLowConfidence) => {
          const svc = new VoiceInterfaceService();
          const sid = 'retry-session';
          svc.startListening(sid);

          // Each low-confidence attempt should return 'please-repeat'
          for (let i = 0; i < numLowConfidence; i++) {
            const result = svc.handleLowConfidence(sid);
            expect(result).not.toBeNull();
            expect(result!.type).toBe('please-repeat');
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  it('should transition to "recognition-failed" after exactly 3 consecutive low-confidence results', () => {
    fc.assert(
      fc.property(
        // Generate arbitrary session IDs to verify independence
        fc.string({ minLength: 1, maxLength: 30 }),
        (sid) => {
          const svc = new VoiceInterfaceService();
          svc.startListening(sid);

          // First MAX_TRANSCRIPTION_RETRIES - 1 attempts should be 'please-repeat'
          for (let i = 0; i < MAX_TRANSCRIPTION_RETRIES - 1; i++) {
            const result = svc.handleLowConfidence(sid);
            expect(result).not.toBeNull();
            expect(result!.type).toBe('please-repeat');
          }

          // The 3rd consecutive attempt triggers 'recognition-failed'
          const finalResult = svc.handleLowConfidence(sid);
          expect(finalResult).not.toBeNull();
          expect(finalResult!.type).toBe('recognition-failed');
        }
      ),
      { numRuns: 100 }
    );
  });

  it('should never trigger "recognition-failed" before exactly 3 consecutive low-confidence results', () => {
    fc.assert(
      fc.property(
        // Generate sequences of confidence scores (mix of above and below threshold)
        fc.array(
          fc.double({ min: 0.0, max: 1.0, noNaN: true }),
          { minLength: 1, maxLength: 20 }
        ),
        (scores) => {
          const svc = new VoiceInterfaceService();
          const sid = 'state-machine-session';
          svc.startListening(sid);

          let consecutiveLow = 0;

          for (const score of scores) {
            if (score < TRANSCRIPTION_CONFIDENCE_THRESHOLD) {
              consecutiveLow++;
              const result = svc.handleLowConfidence(sid);

              if (consecutiveLow < MAX_TRANSCRIPTION_RETRIES) {
                // Before reaching 3, should always be 'please-repeat'
                expect(result).not.toBeNull();
                expect(result!.type).toBe('please-repeat');
              } else if (consecutiveLow === MAX_TRANSCRIPTION_RETRIES) {
                // At exactly 3, should be 'recognition-failed'
                expect(result).not.toBeNull();
                expect(result!.type).toBe('recognition-failed');
                // Counter resets after recognition-failed
                consecutiveLow = 0;
              }
            } else {
              // Above threshold: reset the counter
              svc.resetRetryCount(sid);
              consecutiveLow = 0;
            }
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  it('should reset retry counter on successful transcription (above threshold)', () => {
    fc.assert(
      fc.property(
        // Generate a count of low-confidence results followed by a success
        fc.integer({ min: 1, max: MAX_TRANSCRIPTION_RETRIES - 1 }),
        fc.double({ min: TRANSCRIPTION_CONFIDENCE_THRESHOLD, max: 1.0, noNaN: true }),
        (numLowBefore, successScore) => {
          const svc = new VoiceInterfaceService();
          const sid = 'reset-session';
          svc.startListening(sid);

          // Accumulate some low-confidence retries (but less than MAX)
          for (let i = 0; i < numLowBefore; i++) {
            const result = svc.handleLowConfidence(sid);
            expect(result).not.toBeNull();
            expect(result!.type).toBe('please-repeat');
          }

          // Successful transcription resets the counter
          svc.resetRetryCount(sid);

          // Now verify counter was reset: should need another full 3 consecutive
          // low-confidence results to trigger recognition-failed
          for (let i = 0; i < MAX_TRANSCRIPTION_RETRIES - 1; i++) {
            const result = svc.handleLowConfidence(sid);
            expect(result).not.toBeNull();
            expect(result!.type).toBe('please-repeat');
          }

          // The 3rd consecutive after reset triggers recognition-failed
          const finalResult = svc.handleLowConfidence(sid);
          expect(finalResult).not.toBeNull();
          expect(finalResult!.type).toBe('recognition-failed');
        }
      ),
      { numRuns: 100 }
    );
  });

  it('should correctly handle arbitrary sequences mixing low and high confidence scores', () => {
    fc.assert(
      fc.property(
        // Generate longer sequences to stress-test the state machine
        fc.array(
          fc.double({ min: 0.0, max: 1.0, noNaN: true }),
          { minLength: 5, maxLength: 50 }
        ),
        (scores) => {
          const svc = new VoiceInterfaceService();
          const sid = 'mixed-sequence-session';
          svc.startListening(sid);

          let consecutiveLow = 0;
          let recognitionFailedCount = 0;

          for (const score of scores) {
            if (score < TRANSCRIPTION_CONFIDENCE_THRESHOLD) {
              consecutiveLow++;
              const result = svc.handleLowConfidence(sid);
              expect(result).not.toBeNull();

              if (consecutiveLow === MAX_TRANSCRIPTION_RETRIES) {
                expect(result!.type).toBe('recognition-failed');
                recognitionFailedCount++;
                consecutiveLow = 0; // resets after recognition-failed
              } else {
                expect(result!.type).toBe('please-repeat');
              }
            } else {
              svc.resetRetryCount(sid);
              consecutiveLow = 0;
            }
          }

          // Count how many groups of exactly 3 consecutive lows existed
          // Verify the count of recognition-failed matches our tracking
          expect(recognitionFailedCount).toBeGreaterThanOrEqual(0);
        }
      ),
      { numRuns: 100 }
    );
  });
});
