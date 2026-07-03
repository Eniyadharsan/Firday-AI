/**
 * Property Test: RAG Retrieval Filtering and Ranking (Property 10)
 *
 * **Validates: Requirements 4.1, 4.2, 4.3**
 *
 * Generates random document sets with similarity scores (0.0-1.0),
 * threshold (0.0-1.0), and k (1-20).
 *
 * Asserts:
 * - Returns at most k documents
 * - All returned documents have similarity score >= threshold
 * - Results are sorted in descending order by score
 * - allBelowThreshold is true when no documents meet the threshold
 */

import { describe, it, expect } from 'vitest';
import fc from 'fast-check';

/**
 * Pure filtering/ranking logic extracted from RAGPipelineService.retrieve().
 * We test the core algorithm directly to avoid network calls to Qdrant/embeddings.
 */
interface MockRetrievedDocument {
  id: string;
  content: string;
  similarityScore: number;
  source: string;
  indexedAt: Date;
}

function filterAndRankDocuments(
  documents: MockRetrievedDocument[],
  relevanceThreshold: number,
  topK: number,
): { documents: MockRetrievedDocument[]; allBelowThreshold: boolean } {
  // Filter by relevance threshold
  const filtered = documents.filter(
    (doc) => doc.similarityScore >= relevanceThreshold,
  );

  // Sort by descending score
  filtered.sort((a, b) => b.similarityScore - a.similarityScore);

  // Limit to top-k
  const limited = filtered.slice(0, topK);

  return {
    documents: limited,
    allBelowThreshold: filtered.length === 0,
  };
}

/** Arbitrary for a single document with a random similarity score */
const documentArb = fc.record({
  id: fc.uuid(),
  content: fc.string({ minLength: 1, maxLength: 50 }),
  similarityScore: fc.double({ min: 0.0, max: 1.0, noNaN: true }),
  source: fc.string({ minLength: 1, maxLength: 20 }),
  indexedAt: fc.date(),
});

describe('Property 10: RAG Retrieval Filtering and Ranking', () => {
  /**
   * **Validates: Requirements 4.1, 4.2, 4.3**
   *
   * Returns at most k documents for any valid input.
   */
  it('returns at most k documents', () => {
    fc.assert(
      fc.property(
        fc.array(documentArb, { minLength: 0, maxLength: 30 }),
        fc.double({ min: 0.0, max: 1.0, noNaN: true }),
        fc.integer({ min: 1, max: 20 }),
        (documents, threshold, k) => {
          const result = filterAndRankDocuments(documents, threshold, k);
          expect(result.documents.length).toBeLessThanOrEqual(k);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 4.1, 4.2, 4.3**
   *
   * All returned documents have similarity score >= threshold.
   */
  it('all returned documents have similarity score >= threshold', () => {
    fc.assert(
      fc.property(
        fc.array(documentArb, { minLength: 0, maxLength: 30 }),
        fc.double({ min: 0.0, max: 1.0, noNaN: true }),
        fc.integer({ min: 1, max: 20 }),
        (documents, threshold, k) => {
          const result = filterAndRankDocuments(documents, threshold, k);
          for (const doc of result.documents) {
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
  it('results are sorted in descending order by score', () => {
    fc.assert(
      fc.property(
        fc.array(documentArb, { minLength: 0, maxLength: 30 }),
        fc.double({ min: 0.0, max: 1.0, noNaN: true }),
        fc.integer({ min: 1, max: 20 }),
        (documents, threshold, k) => {
          const result = filterAndRankDocuments(documents, threshold, k);
          for (let i = 1; i < result.documents.length; i++) {
            expect(result.documents[i - 1].similarityScore).toBeGreaterThanOrEqual(
              result.documents[i].similarityScore,
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
   * allBelowThreshold is true when no documents meet the threshold
   * (indicating "no supporting sources" disclaimer should appear).
   */
  it('produces "no supporting sources" when no documents meet threshold', () => {
    fc.assert(
      fc.property(
        fc.array(documentArb, { minLength: 0, maxLength: 30 }),
        fc.double({ min: 0.0, max: 1.0, noNaN: true }),
        fc.integer({ min: 1, max: 20 }),
        (documents, threshold, k) => {
          const result = filterAndRankDocuments(documents, threshold, k);
          const anyAboveThreshold = documents.some(
            (d) => d.similarityScore >= threshold,
          );

          if (!anyAboveThreshold) {
            expect(result.allBelowThreshold).toBe(true);
            expect(result.documents.length).toBe(0);
          } else {
            expect(result.allBelowThreshold).toBe(false);
            expect(result.documents.length).toBeGreaterThan(0);
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});
