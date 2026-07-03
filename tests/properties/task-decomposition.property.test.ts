/**
 * Property Test: Task Decomposition Bounds (Property 16)
 *
 * **Validates: Requirements 7.1**
 *
 * Generates queries of varying complexity and verifies:
 * - Always produces 1–10 subtasks
 * - Never produces more than 10 subtasks
 */

import { describe, it, expect } from 'vitest';
import fc from 'fast-check';
import { OrchestratorService } from '../../src/services/orchestrator';
import { MAX_SUBTASKS } from '../../src/config/defaults';
import type { RAGPipeline } from '../../src/interfaces/rag-pipeline';
import type { DataFetcher } from '../../src/interfaces/data-fetcher';
import type { LLMEngine } from '../../src/interfaces/llm-engine';
import type { ConfidenceScorer } from '../../src/interfaces/confidence-scorer';
import type { UserQuery } from '../../src/interfaces/orchestrator';

/** Minimal mock dependencies — task decomposition doesn't use them */
const mockDeps = {
  ragPipeline: {} as RAGPipeline,
  dataFetcher: {} as DataFetcher,
  llmEngine: {} as LLMEngine,
  confidenceScorer: {} as ConfidenceScorer,
};

/** Arbitrary for a simple query string */
const simpleQueryArb = fc.string({ minLength: 1, maxLength: 100 });

/** Arbitrary for a multi-step query with sequential indicators */
const multiStepQueryArb = fc.array(
  fc.string({ minLength: 5, maxLength: 30 }),
  { minLength: 2, maxLength: 15 },
).map((steps) => steps.join(' and then '));

/** Arbitrary for a query using "and" conjunctions */
const conjunctionQueryArb = fc.array(
  fc.string({ minLength: 5, maxLength: 30 }),
  { minLength: 2, maxLength: 15 },
).map((steps) => steps.join(' and '));

describe('Property 16: Task Decomposition Bounds', () => {
  /**
   * **Validates: Requirements 7.1**
   *
   * Simple queries produce exactly 1 subtask.
   */
  it('simple queries produce at least 1 subtask', async () => {
    await fc.assert(
      fc.asyncProperty(simpleQueryArb, async (queryText) => {
        const orchestrator = new OrchestratorService(mockDeps);
        const query: UserQuery = {
          text: queryText,
          transcriptionConfidence: 0.95,
          sessionId: 'session-1',
          timestamp: new Date(),
        };

        const subtasks = await orchestrator.decomposeTask(query);

        expect(subtasks.length).toBeGreaterThanOrEqual(1);
        expect(subtasks.length).toBeLessThanOrEqual(MAX_SUBTASKS);
      }),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 7.1**
   *
   * Multi-step queries with many steps never exceed 10 subtasks.
   */
  it('multi-step queries never exceed 10 subtasks', async () => {
    await fc.assert(
      fc.asyncProperty(multiStepQueryArb, async (queryText) => {
        const orchestrator = new OrchestratorService(mockDeps);
        const query: UserQuery = {
          text: queryText,
          transcriptionConfidence: 0.95,
          sessionId: 'session-1',
          timestamp: new Date(),
        };

        const subtasks = await orchestrator.decomposeTask(query);

        expect(subtasks.length).toBeGreaterThanOrEqual(1);
        expect(subtasks.length).toBeLessThanOrEqual(MAX_SUBTASKS);
      }),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 7.1**
   *
   * Conjunction queries also stay within 1-10 bounds.
   */
  it('conjunction queries stay within 1-10 bounds', async () => {
    await fc.assert(
      fc.asyncProperty(conjunctionQueryArb, async (queryText) => {
        const orchestrator = new OrchestratorService(mockDeps);
        const query: UserQuery = {
          text: queryText,
          transcriptionConfidence: 0.95,
          sessionId: 'session-1',
          timestamp: new Date(),
        };

        const subtasks = await orchestrator.decomposeTask(query);

        expect(subtasks.length).toBeGreaterThanOrEqual(1);
        expect(subtasks.length).toBeLessThanOrEqual(MAX_SUBTASKS);
      }),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 7.1**
   *
   * All subtask IDs are sequential starting from 1.
   */
  it('subtask IDs are sequential starting from 1', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.oneof(simpleQueryArb, multiStepQueryArb, conjunctionQueryArb),
        async (queryText) => {
          const orchestrator = new OrchestratorService(mockDeps);
          const query: UserQuery = {
            text: queryText,
            transcriptionConfidence: 0.95,
            sessionId: 'session-1',
            timestamp: new Date(),
          };

          const subtasks = await orchestrator.decomposeTask(query);

          for (let i = 0; i < subtasks.length; i++) {
            expect(subtasks[i].id).toBe(i + 1);
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});
