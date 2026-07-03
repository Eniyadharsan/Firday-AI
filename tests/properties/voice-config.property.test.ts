/**
 * Property 3: Voice Configuration Boundary Validation
 *
 * For any VoiceConfig with random speed, pitch, and voiceId values,
 * the synthesize() method SHALL accept the config if and only if:
 *   speed ∈ [0.5, 2.0] AND pitch ∈ [0.5, 2.0] AND voiceId ∈ available voices.
 * Out-of-range values SHALL be rejected with an error.
 *
 * Feature: personal-ai-model, Property 3: Voice Configuration Boundary Validation
 * **Validates: Requirements 1.5**
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import * as fc from 'fast-check';
import { VoiceInterfaceService } from '../../src/services/voice-interface.js';
import {
  VOICE_SPEED_MIN,
  VOICE_SPEED_MAX,
  VOICE_PITCH_MIN,
  VOICE_PITCH_MAX,
} from '../../src/config/defaults.js';

const AVAILABLE_VOICES = ['default', 'female-1'];

/**
 * Creates a fresh mock Response with a readable body for each fetch call.
 */
function createMockFetch() {
  return vi.fn().mockImplementation(() => {
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new Uint8Array([0x00, 0x01, 0x02]));
        controller.close();
      },
    });
    return Promise.resolve(new Response(stream, {
      status: 200,
      headers: { 'Content-Type': 'audio/wav' },
    }));
  });
}

describe('Property 3: Voice Configuration Boundary Validation', () => {
  let service: VoiceInterfaceService;

  beforeEach(() => {
    service = new VoiceInterfaceService(undefined, undefined, AVAILABLE_VOICES);
    vi.stubGlobal('fetch', createMockFetch());
  });

  it('should accept config when speed, pitch, and voiceId are all within valid ranges', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.double({ min: VOICE_SPEED_MIN, max: VOICE_SPEED_MAX, noNaN: true }),
        fc.double({ min: VOICE_PITCH_MIN, max: VOICE_PITCH_MAX, noNaN: true }),
        fc.constantFrom(...AVAILABLE_VOICES),
        async (speed, pitch, voiceId) => {
          // Valid config should not throw
          const result = await service.synthesize('Hello', { speed, pitch, voiceId });
          expect(result).toBeDefined();
        }
      ),
      { numRuns: 100 }
    );
  });

  it('should reject config when speed is below minimum', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.double({ min: -100, max: VOICE_SPEED_MIN - 0.0001, noNaN: true, noDefaultInfinity: true }),
        fc.double({ min: VOICE_PITCH_MIN, max: VOICE_PITCH_MAX, noNaN: true }),
        fc.constantFrom(...AVAILABLE_VOICES),
        async (speed, pitch, voiceId) => {
          await expect(
            service.synthesize('Hello', { speed, pitch, voiceId })
          ).rejects.toThrow(/voice speed/i);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('should reject config when speed is above maximum', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.double({ min: VOICE_SPEED_MAX + 0.0001, max: 100, noNaN: true, noDefaultInfinity: true }),
        fc.double({ min: VOICE_PITCH_MIN, max: VOICE_PITCH_MAX, noNaN: true }),
        fc.constantFrom(...AVAILABLE_VOICES),
        async (speed, pitch, voiceId) => {
          await expect(
            service.synthesize('Hello', { speed, pitch, voiceId })
          ).rejects.toThrow(/voice speed/i);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('should reject config when pitch is below minimum', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.double({ min: VOICE_SPEED_MIN, max: VOICE_SPEED_MAX, noNaN: true }),
        fc.double({ min: -100, max: VOICE_PITCH_MIN - 0.0001, noNaN: true, noDefaultInfinity: true }),
        fc.constantFrom(...AVAILABLE_VOICES),
        async (speed, pitch, voiceId) => {
          await expect(
            service.synthesize('Hello', { speed, pitch, voiceId })
          ).rejects.toThrow(/voice pitch/i);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('should reject config when pitch is above maximum', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.double({ min: VOICE_SPEED_MIN, max: VOICE_SPEED_MAX, noNaN: true }),
        fc.double({ min: VOICE_PITCH_MAX + 0.0001, max: 100, noNaN: true, noDefaultInfinity: true }),
        fc.constantFrom(...AVAILABLE_VOICES),
        async (speed, pitch, voiceId) => {
          await expect(
            service.synthesize('Hello', { speed, pitch, voiceId })
          ).rejects.toThrow(/voice pitch/i);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('should reject config when voiceId is not in available voices', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.double({ min: VOICE_SPEED_MIN, max: VOICE_SPEED_MAX, noNaN: true }),
        fc.double({ min: VOICE_PITCH_MIN, max: VOICE_PITCH_MAX, noNaN: true }),
        fc.string({ minLength: 1, maxLength: 50 }).filter(
          (s) => !AVAILABLE_VOICES.includes(s)
        ),
        async (speed, pitch, voiceId) => {
          await expect(
            service.synthesize('Hello', { speed, pitch, voiceId })
          ).rejects.toThrow(/voice id/i);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('should accept iff speed ∈ [0.5, 2.0] AND pitch ∈ [0.5, 2.0] AND voiceId ∈ available voices', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.double({ min: -10, max: 10, noNaN: true, noDefaultInfinity: true }),
        fc.double({ min: -10, max: 10, noNaN: true, noDefaultInfinity: true }),
        fc.oneof(
          fc.constantFrom(...AVAILABLE_VOICES),
          fc.string({ minLength: 1, maxLength: 20 })
        ),
        async (speed, pitch, voiceId) => {
          const isValidSpeed = speed >= VOICE_SPEED_MIN && speed <= VOICE_SPEED_MAX;
          const isValidPitch = pitch >= VOICE_PITCH_MIN && pitch <= VOICE_PITCH_MAX;
          const isValidVoice = AVAILABLE_VOICES.includes(voiceId);
          const shouldAccept = isValidSpeed && isValidPitch && isValidVoice;

          if (shouldAccept) {
            const result = await service.synthesize('Hello', { speed, pitch, voiceId });
            expect(result).toBeDefined();
          } else {
            await expect(
              service.synthesize('Hello', { speed, pitch, voiceId })
            ).rejects.toThrow();
          }
        }
      ),
      { numRuns: 100 }
    );
  });
});
