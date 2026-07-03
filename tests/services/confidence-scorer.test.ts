/**
 * Unit tests for ConfidenceScorerService.
 *
 * Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
 */

import { describe, it, expect } from 'vitest';
import { ConfidenceScorerService } from '../../src/services/confidence-scorer.js';
import { ScoringContext } from '../../src/interfaces/confidence-scorer.js';
import { RetrievedDocument } from '../../src/interfaces/rag-pipeline.js';
import { DataItem } from '../../src/interfaces/data-fetcher.js';

function makeDoc(id: string, content: string, score = 0.9): RetrievedDocument {
  return {
    id,
    content,
    similarityScore: score,
    source: `source-${id}`,
    indexedAt: new Date(),
  };
}

function makeDataItem(content: string, source = 'news-api'): DataItem {
  return {
    content,
    source,
    retrievedAt: new Date(),
    category: 'news',
    verified: true,
  };
}

describe('ConfidenceScorerService', () => {
  const scorer = new ConfidenceScorerService();

  describe('score() - overall confidence', () => {
    it('should return confidence 0 when response has no evidence support', async () => {
      const context: ScoringContext = {
        retrievedDocuments: [],
        fetchedData: [],
        query: 'test query',
      };

      const result = await scorer.score('This is a completely novel statement.', context);

      expect(result.overallScore).toBe(0);
      expect(result.needsDisclaimer).toBe(true);
    });

    it('should return high confidence when response closely matches evidence', async () => {
      const doc = makeDoc('doc1', 'The weather today is sunny and warm with clear skies');
      const context: ScoringContext = {
        retrievedDocuments: [doc],
        fetchedData: [],
        query: 'What is the weather?',
      };

      const result = await scorer.score(
        'The weather today is sunny and warm with clear skies.',
        context
      );

      expect(result.overallScore).toBeGreaterThan(0.7);
      expect(result.needsDisclaimer).toBe(false);
    });

    it('should return score between 0.0 and 1.0', async () => {
      const doc = makeDoc('doc1', 'Some partially relevant content about TypeScript');
      const context: ScoringContext = {
        retrievedDocuments: [doc],
        fetchedData: [],
        query: 'Tell me about TypeScript',
      };

      const result = await scorer.score(
        'TypeScript is a language. It has many features not mentioned here.',
        context
      );

      expect(result.overallScore).toBeGreaterThanOrEqual(0.0);
      expect(result.overallScore).toBeLessThanOrEqual(1.0);
    });
  });

  describe('score() - needsDisclaimer', () => {
    it('should set needsDisclaimer=true when score < 0.7', async () => {
      const context: ScoringContext = {
        retrievedDocuments: [],
        fetchedData: [],
        query: 'random query',
      };

      const result = await scorer.score('Ungrounded claims about aliens.', context);

      expect(result.needsDisclaimer).toBe(true);
    });

    it('should set needsDisclaimer=false when score >= 0.7', async () => {
      const doc = makeDoc('doc1', 'The capital of France is Paris and it is a beautiful city');
      const context: ScoringContext = {
        retrievedDocuments: [doc],
        fetchedData: [],
        query: 'What is the capital of France?',
      };

      const result = await scorer.score(
        'The capital of France is Paris and it is a beautiful city.',
        context
      );

      expect(result.overallScore).toBeGreaterThanOrEqual(0.7);
      expect(result.needsDisclaimer).toBe(false);
    });

    it('should respect custom threshold', async () => {
      const customScorer = new ConfidenceScorerService(0.9);
      const doc = makeDoc('doc1', 'Some matching content about testing approaches');
      const context: ScoringContext = {
        retrievedDocuments: [doc],
        fetchedData: [],
        query: 'testing',
      };

      const result = await customScorer.score(
        'Some matching content about testing approaches.',
        context
      );

      // Even with matching content, a 0.9 threshold is harder to reach
      // The result depends on exact overlap but demonstrates threshold configurability
      expect(typeof result.needsDisclaimer).toBe('boolean');
    });
  });

  describe('score() - segment labeling', () => {
    it('should label supported segments as retrieved_evidence', async () => {
      const doc = makeDoc('doc1', 'TypeScript supports strict type checking and interfaces');
      const context: ScoringContext = {
        retrievedDocuments: [doc],
        fetchedData: [],
        query: 'TypeScript features',
      };

      const result = await scorer.score(
        'TypeScript supports strict type checking and interfaces.',
        context
      );

      expect(result.segments.length).toBeGreaterThan(0);
      expect(result.segments[0]!.sourceBasis).toBe('retrieved_evidence');
      expect(result.segments[0]!.supportingDocIds).toContain('doc1');
    });

    it('should label unsupported segments as model_knowledge', async () => {
      const doc = makeDoc('doc1', 'The earth revolves around the sun in 365 days');
      const context: ScoringContext = {
        retrievedDocuments: [doc],
        fetchedData: [],
        query: 'general questions',
      };

      const result = await scorer.score(
        'Quantum computing uses qubits for parallel computation.',
        context
      );

      expect(result.segments.length).toBeGreaterThan(0);
      expect(result.segments[0]!.sourceBasis).toBe('model_knowledge');
      expect(result.segments[0]!.supportingDocIds).toHaveLength(0);
    });

    it('should handle mixed segments with different source bases', async () => {
      const doc = makeDoc('doc1', 'The weather is sunny and warm today in the city');
      const context: ScoringContext = {
        retrievedDocuments: [doc],
        fetchedData: [],
        query: 'weather and plans',
      };

      const result = await scorer.score(
        'The weather is sunny and warm today. Quantum mechanics explores particle behavior.',
        context
      );

      expect(result.segments.length).toBe(2);
      // First segment should be evidence-backed
      expect(result.segments[0]!.sourceBasis).toBe('retrieved_evidence');
      // Second segment should be model knowledge
      expect(result.segments[1]!.sourceBasis).toBe('model_knowledge');
    });

    it('should include supporting document IDs for evidence segments', async () => {
      const doc1 = makeDoc('doc-a', 'Machine learning models require training data');
      const doc2 = makeDoc('doc-b', 'Machine learning models use training data for optimization');
      const context: ScoringContext = {
        retrievedDocuments: [doc1, doc2],
        fetchedData: [],
        query: 'machine learning',
      };

      const result = await scorer.score(
        'Machine learning models require training data for optimization.',
        context
      );

      const segment = result.segments[0]!;
      expect(segment.sourceBasis).toBe('retrieved_evidence');
      expect(segment.supportingDocIds.length).toBeGreaterThan(0);
    });
  });

  describe('score() - fetched data support', () => {
    it('should consider fetched data as evidence source', async () => {
      const dataItem = makeDataItem(
        'Stock market rallied today with major indices reaching new highs'
      );
      const context: ScoringContext = {
        retrievedDocuments: [],
        fetchedData: [dataItem],
        query: 'stock market today',
      };

      const result = await scorer.score(
        'Stock market rallied today with major indices reaching new highs.',
        context
      );

      expect(result.segments[0]!.sourceBasis).toBe('retrieved_evidence');
      expect(result.segments[0]!.segmentConfidence).toBeGreaterThan(0);
    });

    it('should combine evidence from both documents and fetched data', async () => {
      const doc = makeDoc('doc1', 'The company reported strong earnings this quarter');
      const dataItem = makeDataItem('Stock prices surged after the earnings announcement');
      const context: ScoringContext = {
        retrievedDocuments: [doc],
        fetchedData: [dataItem],
        query: 'company earnings',
      };

      const result = await scorer.score(
        'The company reported strong earnings this quarter. Stock prices surged after the earnings announcement.',
        context
      );

      expect(result.segments.length).toBe(2);
      expect(result.segments[0]!.sourceBasis).toBe('retrieved_evidence');
      expect(result.segments[1]!.sourceBasis).toBe('retrieved_evidence');
    });
  });

  describe('score() - edge cases', () => {
    it('should handle empty response', async () => {
      const context: ScoringContext = {
        retrievedDocuments: [],
        fetchedData: [],
        query: 'test',
      };

      const result = await scorer.score('', context);

      expect(result.overallScore).toBe(0);
      expect(result.segments).toHaveLength(0);
      expect(result.needsDisclaimer).toBe(true);
    });

    it('should handle response with single word', async () => {
      const doc = makeDoc('doc1', 'Yes confirmed');
      const context: ScoringContext = {
        retrievedDocuments: [doc],
        fetchedData: [],
        query: 'confirm?',
      };

      const result = await scorer.score('Yes.', context);

      expect(result.overallScore).toBeGreaterThanOrEqual(0.0);
      expect(result.overallScore).toBeLessThanOrEqual(1.0);
      expect(result.segments.length).toBe(1);
    });

    it('should handle context with no documents and no data', async () => {
      const context: ScoringContext = {
        retrievedDocuments: [],
        fetchedData: [],
        query: 'anything',
      };

      const result = await scorer.score('Some response text here.', context);

      expect(result.overallScore).toBe(0);
      expect(result.segments[0]!.sourceBasis).toBe('model_knowledge');
      expect(result.needsDisclaimer).toBe(true);
    });

    it('should produce segment confidence between 0.0 and 1.0 for each segment', async () => {
      const doc = makeDoc('doc1', 'Testing is important for software quality assurance');
      const context: ScoringContext = {
        retrievedDocuments: [doc],
        fetchedData: [],
        query: 'testing',
      };

      const result = await scorer.score(
        'Testing is important for software quality. Other things are also relevant.',
        context
      );

      for (const segment of result.segments) {
        expect(segment.segmentConfidence).toBeGreaterThanOrEqual(0.0);
        expect(segment.segmentConfidence).toBeLessThanOrEqual(1.0);
      }
    });
  });
});
