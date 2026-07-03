/**
 * Property Test: Confidence Score Validity and Threshold Disclaimer (Property 12)
 *
 * **Validates: Requirements 5.1, 5.2**
 *
 * Generates responses with varying evidence and verifies:
 * - Confidence score is always in [0.0, 1.0]
 * - Disclaimer is present when score < threshold (default 0.7)
 * - Disclaimer is absent when score >= threshold
 */

import { describe, it, expect } from 'vitest';
import fc from 'fast-check';
import { ConfidenceScorerService } from '../../src/services/confidence-scorer';
import { CONFIDENCE_THRESHOLD } from '../../src/config/defaults';
import type { ScoringContext } from '../../src/interfaces/confidence-scorer';
import type { RetrievedDocument } from '../../src/interfaces/rag-pipeline';
import type { DataItem } from '../../src/interfaces/data-fetcher';

/** Generator for a simple response string */
const responseArb = fc.array(
  fc.string({ minLength: 5, maxLength: 40 }),
  { minLength: 1, maxLength: 5 },
).map((sentences) => sentences.join('. ') + '.');

/** Generator for a retrieved document */
const retrievedDocArb = fc.record({
  id: fc.uuid(),
  content: fc.string({ minLength: 10, maxLength: 100 }),
  similarityScore: fc.double({ min: 0.0, max: 1.0, noNaN: true }),
  source: fc.string({ minLength: 3, maxLength: 20 }),
  indexedAt: fc.date(),
});

/** Generator for a data item */
const dataItemArb = fc.record({
  content: fc.string({ minLength: 10, maxLength: 100 }),
  source: fc.string({ minLength: 3, maxLength: 20 }),
  retrievedAt: fc.date(),
  category: fc.constantFrom('news' as const, 'web_search' as const, 'weather' as const),
  verified: fc.boolean(),
});

describe('Property 12: Confidence Score Validity and Threshold Disclaimer', () => {
  /**
   * **Validates: Requirements 5.1, 5.2**
   *
   * Confidence score is always in [0.0, 1.0] for any response and context.
   */
  it('score is always in [0.0, 1.0]', async () => {
    await fc.assert(
      fc.asyncProperty(
        responseArb,
        fc.array(retrievedDocArb, { minLength: 0, maxLength: 5 }),
        fc.array(dataItemArb, { minLength: 0, maxLength: 5 }),
        async (response, docs, data) => {
          const scorer = new ConfidenceScorerService();
          const context: ScoringContext = {
            retrievedDocuments: docs as RetrievedDocument[],
            fetchedData: data as DataItem[],
            query: 'test query',
          };

          const result = await scorer.score(response, context);

          expect(result.overallScore).toBeGreaterThanOrEqual(0.0);
          expect(result.overallScore).toBeLessThanOrEqual(1.0);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 5.1, 5.2**
   *
   * Disclaimer is present when score < threshold.
   * We construct a response that has NO overlap with evidence to guarantee low confidence.
   */
  it('disclaimer present when score is below threshold', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.double({ min: 0.0, max: 1.0, noNaN: true }),
        async (threshold) => {
          const scorer = new ConfidenceScorerService(threshold);

          // Use a response with no overlap to any evidence → score should be 0
          const response = 'xyzzy plugh abcdef ghijkl mnopqr.';
          const context: ScoringContext = {
            retrievedDocuments: [
              {
                id: 'doc-1',
                content: 'completely different unrelated text here',
                similarityScore: 0.9,
                source: 'test-source',
                indexedAt: new Date(),
              },
            ],
            fetchedData: [],
            query: 'test query',
          };

          const result = await scorer.score(response, context);

          // Score should be 0 (no overlap)
          if (result.overallScore < threshold) {
            expect(result.needsDisclaimer).toBe(true);
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 5.1, 5.2**
   *
   * Disclaimer is absent when score >= threshold.
   * We construct a response identical to evidence to guarantee high confidence.
   */
  it('no disclaimer when score is at or above threshold', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.double({ min: 0.01, max: 1.0, noNaN: true }),
        fc.array(fc.string({ minLength: 3, maxLength: 15 }), { minLength: 3, maxLength: 8 }),
        async (threshold, words) => {
          const scorer = new ConfidenceScorerService(threshold);

          // Use the same text for response and evidence → high overlap → high score
          const sharedText = words.join(' ') + '.';
          const response = sharedText;
          const context: ScoringContext = {
            retrievedDocuments: [
              {
                id: 'doc-1',
                content: sharedText,
                similarityScore: 0.95,
                source: 'evidence-source',
                indexedAt: new Date(),
              },
            ],
            fetchedData: [],
            query: 'test query',
          };

          const result = await scorer.score(response, context);

          if (result.overallScore >= threshold) {
            expect(result.needsDisclaimer).toBe(false);
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 5.1, 5.2**
   *
   * needsDisclaimer is consistent with score vs threshold comparison.
   */
  it('needsDisclaimer is always consistent with score vs threshold', async () => {
    await fc.assert(
      fc.asyncProperty(
        responseArb,
        fc.array(retrievedDocArb, { minLength: 0, maxLength: 3 }),
        fc.array(dataItemArb, { minLength: 0, maxLength: 3 }),
        async (response, docs, data) => {
          const scorer = new ConfidenceScorerService(CONFIDENCE_THRESHOLD);
          const context: ScoringContext = {
            retrievedDocuments: docs as RetrievedDocument[],
            fetchedData: data as DataItem[],
            query: 'test query',
          };

          const result = await scorer.score(response, context);

          if (result.overallScore < CONFIDENCE_THRESHOLD) {
            expect(result.needsDisclaimer).toBe(true);
          } else {
            expect(result.needsDisclaimer).toBe(false);
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});
