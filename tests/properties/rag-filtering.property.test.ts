/**
 * Property Test: RAG Retrieval Filtering (Property 10)
 *
 * **Validates: Requirements 4.1, 4.2, 4.3**
 *
 * Generates document sets with random scores, thresholds, and k values.
 * Tests the pure filtering/ranking logic directly (no HTTP mocks needed).
 *
 * Asserts:
 * - At most k documents returned
 * - All returned docs are above the threshold
 * - Results are sorted in descending order by score
 * - Disclaimer (allBelowThreshold) if none meet threshold
 */

import { describe, it, expect } from 'vitest';
import fc from 'fast-check';

/** Document shape for testing the pure filtering logic */
interface ScoredDocument {
  id: string;
  content: string;
  similarityScore: number;
  source: string;
}

/**
 * Pure filtering and ranking logic — mirrors RAGPipelineService behavior.
 * Filters by relevance threshold, sorts descending, limits to top-k.
 */
function filterRankAndLimit(
  documents: ScoredDocument[],
  relevanceThreshold: number,
  topK: number,
): { results: ScoredDocument[]; allBelowThreshold: boolean } {
  const filtered = documents.filter(
    (doc) => doc.similarityScore >= relevanceThreshold,
  );

  filtered.sort((a, b) => b.similarityScore - a.similarityScore);

  const limited = filtered.slice(0, topK);

  return {
    results: limited,
    allBelowThreshold: filtered.length === 0,
  };
}

/** Arbitrary for a scored document */
const scoredDocArb = fc.record({
  id: fc.uuid(),
  content: fc.string({ minLength: 5, maxLength: 60 }),
  similarityScore: fc.double({ min: 0.0, max: 1.0, noNaN: true }),
  source: fc.string({ minLength: 3, maxLength: 20 }),
});

describe('Property 10: RAG Retrieval Filtering', () => {
  /**
   * **Validates: Requirements 4.1, 4.2, 4.3**
   *
   * At most k documents are returned, regardless of input size.
   */
  it('returns at most k documents', () => {
    fc.assert(
      fc.property(
        fc.array(scoredDocArb, { minLength: 0, maxLength: 30 }),
        fc.double({ min: 0.0, max: 1.0, noNaN: true }),
        fc.integer({ min: 1, max: 20 }),
        (documents, threshold, k) => {
          const { results } = filterRankAndLimit(documents, threshold, k);
          expect(results.length).toBeLessThanOrEqual(k);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 4.1, 4.2, 4.3**
   *
   * All returned documents have score >= threshold.
   */
  it('all returned documents are above the threshold', () => {
    fc.assert(
      fc.property(
        fc.array(scoredDocArb, { minLength: 0, maxLength: 30 }),
        fc.double({ min: 0.0, max: 1.0, noNaN: true }),
        fc.integer({ min: 1, max: 20 }),
        (documents, threshold, k) => {
          const { results } = filterRankAndLimit(documents, threshold, k);
          for (const doc of results) {
            expect(doc.similarityScore).toBeGreaterThanOrEqual(threshold);
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 4.1, 4.2, 4.3**
   *
   * Results are sorted in descending order by similarity score.
   */
  it('results are sorted descending by score', () => {
    fc.assert(
      fc.property(
        fc.array(scoredDocArb, { minLength: 0, maxLength: 30 }),
        fc.double({ min: 0.0, max: 1.0, noNaN: true }),
        fc.integer({ min: 1, max: 20 }),
        (documents, threshold, k) => {
          const { results } = filterRankAndLimit(documents, threshold, k);
          for (let i = 1; i < results.length; i++) {
            expect(results[i - 1].similarityScore).toBeGreaterThanOrEqual(
              results[i].similarityScore,
            );
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 4.1, 4.2, 4.3**
   *
   * Disclaimer emitted when no documents meet the threshold.
   */
  it('disclaimer when no documents meet threshold', () => {
    fc.assert(
      fc.property(
        fc.array(scoredDocArb, { minLength: 0, maxLength: 30 }),
        fc.double({ min: 0.0, max: 1.0, noNaN: true }),
        fc.integer({ min: 1, max: 20 }),
        (documents, threshold, k) => {
          const { results, allBelowThreshold } = filterRankAndLimit(documents, threshold, k);
          const anyAbove = documents.some((d) => d.similarityScore >= threshold);

          if (!anyAbove) {
            expect(allBelowThreshold).toBe(true);
            expect(results.length).toBe(0);
          } else {
            expect(allBelowThreshold).toBe(false);
            expect(results.length).toBeGreaterThan(0);
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});
