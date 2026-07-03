/**
 * Property Test: Model Rollback Decision Logic (Property 15)
 *
 * **Validates: Requirements 6.7**
 *
 * Generates evaluation scores (0.0-1.0) and verifies:
 * - Rollback triggered when evaluation score < 0.60
 * - New model retained when evaluation score >= 0.60
 */

import { describe, it, expect } from 'vitest';
import fc from 'fast-check';
import {
  FineTuningManager,
  TrainingExample,
} from '../../src/services/fine-tuning-manager';
import {
  MODEL_ROLLBACK_THRESHOLD,
  FINE_TUNING_MIN_EXAMPLES,
} from '../../src/config/defaults';

/**
 * Create a set of training examples sufficient for fine-tuning.
 */
function createTrainingData(count: number): TrainingExample[] {
  return Array.from({ length: count }, (_, i) => ({
    input: `input-${i}`,
    expectedOutput: `output-${i}`,
    category: 'general',
  }));
}

describe('Property 15: Model Rollback Decision Logic', () => {
  /**
   * **Validates: Requirements 6.7**
   *
   * Rollback is triggered when evaluation score < 0.60.
   */
  it('triggers rollback when evaluation score < 0.60', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.double({ min: 0.0, max: MODEL_ROLLBACK_THRESHOLD - 0.001, noNaN: true }),
        async (evalScore) => {
          const manager = new FineTuningManager({
            fineTuneFn: async () => ({
              weightsPath: '/models/test-weights',
              evalScore,
            }),
          });

          const trainingData = createTrainingData(FINE_TUNING_MIN_EXAMPLES);
          const result = await manager.triggerFineTuning(trainingData, 'base-model');

          expect(result.rolledBack).toBe(true);
          expect(result.success).toBe(false);
          expect(result.evaluationScore).toBe(evalScore);
          expect(result.modelVersion?.status).toBe('rolled_back');
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 6.7**
   *
   * New model is retained when evaluation score >= 0.60.
   */
  it('retains new model when evaluation score >= 0.60', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.double({ min: MODEL_ROLLBACK_THRESHOLD, max: 1.0, noNaN: true }),
        async (evalScore) => {
          const manager = new FineTuningManager({
            fineTuneFn: async () => ({
              weightsPath: '/models/test-weights',
              evalScore,
            }),
          });

          const trainingData = createTrainingData(FINE_TUNING_MIN_EXAMPLES);
          const result = await manager.triggerFineTuning(trainingData, 'base-model');

          expect(result.rolledBack).toBe(false);
          expect(result.success).toBe(true);
          expect(result.evaluationScore).toBe(evalScore);
          expect(result.modelVersion?.status).toBe('active');
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 6.7**
   *
   * The threshold boundary is exactly 0.60 — score of exactly 0.60 retains the model.
   */
  it('score of exactly 0.60 retains the model (boundary)', async () => {
    const manager = new FineTuningManager({
      fineTuneFn: async () => ({
        weightsPath: '/models/boundary-weights',
        evalScore: MODEL_ROLLBACK_THRESHOLD,
      }),
    });

    const trainingData = createTrainingData(FINE_TUNING_MIN_EXAMPLES);
    const result = await manager.triggerFineTuning(trainingData, 'base-model');

    expect(result.rolledBack).toBe(false);
    expect(result.success).toBe(true);
    expect(result.evaluationScore).toBe(MODEL_ROLLBACK_THRESHOLD);
  });

  /**
   * **Validates: Requirements 6.7**
   *
   * After rollback, no model becomes active (previous stays active if it existed).
   */
  it('after rollback, the rolled-back version is not active', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.double({ min: 0.0, max: MODEL_ROLLBACK_THRESHOLD - 0.001, noNaN: true }),
        async (evalScore) => {
          const manager = new FineTuningManager({
            fineTuneFn: async () => ({
              weightsPath: '/models/test-weights',
              evalScore,
            }),
          });

          const trainingData = createTrainingData(FINE_TUNING_MIN_EXAMPLES);
          await manager.triggerFineTuning(trainingData, 'base-model');

          // The active model should be null since the only version was rolled back
          const activeModel = manager.getActiveModel();
          expect(activeModel).toBeNull();
        },
      ),
      { numRuns: 100 },
    );
  });
});
