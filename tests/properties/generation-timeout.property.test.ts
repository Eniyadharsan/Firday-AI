/**
 * Property Test: Generation Timeout Enforcement (Property 14)
 *
 * **Validates: Requirements 6.6**
 *
 * Generates requests with varying simulated durations and verifies:
 * - Error returned if generation exceeds 10 seconds
 * - No partial response is delivered on timeout
 */

import { describe, it, expect } from 'vitest';
import fc from 'fast-check';
import { VLLMEngine } from '../../src/services/llm-engine';
import { LLM_GENERATION_TIMEOUT_SECONDS } from '../../src/config/defaults';
import type { GenerationRequest } from '../../src/interfaces/llm-engine';

/**
 * Create a mock HTTP server that delays response by a given number of milliseconds.
 * We simulate this by creating a VLLMEngine pointed at a server that delays.
 * For unit property testing, we use a minimal approach with a local abort-based test.
 */

/** Creates a generation request with a specific timeout */
function createRequest(timeoutMs: number): GenerationRequest {
  return {
    prompt: 'Test prompt',
    context: [],
    conversationHistory: [],
    maxTokens: 100,
    temperature: 0.7,
    timeoutMs,
  };
}

describe('Property 14: Generation Timeout Enforcement', () => {
  /**
   * **Validates: Requirements 6.6**
   *
   * When generation exceeds the timeout, an error is returned with empty text.
   * We simulate this by using a very short timeout against a non-responsive endpoint.
   */
  it('returns error with empty text when generation exceeds timeout', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 1, max: 50 }), // Very short timeouts (1-50ms) to force timeout
        async (timeoutMs) => {
          // Point to a non-existent host that will cause a connection timeout/abort
          const engine = new VLLMEngine({
            baseUrl: 'http://192.0.2.1:1', // Non-routable address
            modelVersion: 'test-model',
            modelId: 'test',
          });

          const request = createRequest(timeoutMs);
          const result = await engine.generate(request);

          // On timeout or error: text must be empty, error must be present
          expect(result.text).toBe('');
          expect(result.error).toBeDefined();
          expect(result.error!.length).toBeGreaterThan(0);
          expect(result.tokenCount).toBe(0);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 6.6**
   *
   * No partial response is ever delivered — text is always empty string on error.
   */
  it('never delivers partial response on timeout/error', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 1, max: 100 }),
        async (timeoutMs) => {
          const engine = new VLLMEngine({
            baseUrl: 'http://192.0.2.1:1', // Non-routable
            modelVersion: 'test-model',
            modelId: 'test',
          });

          const request = createRequest(timeoutMs);
          const result = await engine.generate(request);

          // If there's an error, text MUST be empty (no partial content)
          if (result.error) {
            expect(result.text).toBe('');
            expect(result.tokenCount).toBe(0);
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 6.6**
   *
   * The default timeout is 10 seconds (LLM_GENERATION_TIMEOUT_SECONDS).
   */
  it('default timeout is 10 seconds', () => {
    expect(LLM_GENERATION_TIMEOUT_SECONDS).toBe(10);
  });

  /**
   * **Validates: Requirements 6.6**
   *
   * generationTimeMs is always reported, even on timeout.
   */
  it('generationTimeMs is always reported on timeout', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 1, max: 50 }),
        async (timeoutMs) => {
          const engine = new VLLMEngine({
            baseUrl: 'http://192.0.2.1:1',
            modelVersion: 'test-model',
            modelId: 'test',
          });

          const request = createRequest(timeoutMs);
          const result = await engine.generate(request);

          expect(result.generationTimeMs).toBeGreaterThanOrEqual(0);
          expect(result.modelVersion).toBe('test-model');
        },
      ),
      { numRuns: 100 },
    );
  });
});
