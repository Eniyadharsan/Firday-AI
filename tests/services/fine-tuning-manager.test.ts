/**
 * Unit tests for FineTuningManager.
 *
 * Tests cover:
 * - Minimum examples validation
 * - Rollback threshold logic
 * - Version management (active, archived, rolled_back)
 * - Manual rollback
 * - Error handling
 *
 * Requirements: 6.2, 6.3, 6.7
 */

import { describe, it, expect } from 'vitest';
import {
  FineTuningManager,
  TrainingExample,
} from '../../src/services/fine-tuning-manager';
import {
  MODEL_ROLLBACK_THRESHOLD,
  FINE_TUNING_MIN_EXAMPLES,
} from '../../src/config/defaults';

/** Create N training examples for testing */
function createExamples(n: number): TrainingExample[] {
  return Array.from({ length: n }, (_, i) => ({
    input: `input-${i}`,
    expectedOutput: `output-${i}`,
    category: 'general',
  }));
}

describe('FineTuningManager', () => {
  describe('Minimum examples validation', () => {
    it('rejects fine-tuning when fewer than 50 examples provided', async () => {
      const manager = new FineTuningManager();
      const data = createExamples(49);

      const result = await manager.triggerFineTuning(data, 'mistral-7b');

      expect(result.success).toBe(false);
      expect(result.modelVersion).toBeNull();
      expect(result.rolledBack).toBe(false);
      expect(result.error).toContain('Insufficient training data');
      expect(result.error).toContain('49');
      expect(result.error).toContain(`${FINE_TUNING_MIN_EXAMPLES}`);
    });

    it('rejects fine-tuning with 0 examples', async () => {
      const manager = new FineTuningManager();
      const result = await manager.triggerFineTuning([], 'mistral-7b');

      expect(result.success).toBe(false);
      expect(result.error).toContain('Insufficient training data');
    });

    it('accepts fine-tuning with exactly 50 examples', async () => {
      const manager = new FineTuningManager({
        fineTuneFn: async () => ({ weightsPath: '/models/test', evalScore: 0.75 }),
      });
      const data = createExamples(50);

      const result = await manager.triggerFineTuning(data, 'mistral-7b');

      expect(result.success).toBe(true);
      expect(result.modelVersion).not.toBeNull();
    });

    it('accepts fine-tuning with more than 50 examples', async () => {
      const manager = new FineTuningManager({
        fineTuneFn: async () => ({ weightsPath: '/models/test', evalScore: 0.80 }),
      });
      const data = createExamples(100);

      const result = await manager.triggerFineTuning(data, 'mistral-7b');

      expect(result.success).toBe(true);
      expect(result.modelVersion).not.toBeNull();
      expect(result.modelVersion!.trainingExamples).toBe(100);
    });
  });

  describe('Rollback threshold logic', () => {
    it('retains new model when evaluation score >= 0.60', async () => {
      const manager = new FineTuningManager({
        fineTuneFn: async () => ({ weightsPath: '/models/good', evalScore: 0.60 }),
      });
      const data = createExamples(60);

      const result = await manager.triggerFineTuning(data, 'mistral-7b');

      expect(result.success).toBe(true);
      expect(result.rolledBack).toBe(false);
      expect(result.evaluationScore).toBe(0.60);
      expect(result.modelVersion!.status).toBe('active');
    });

    it('triggers rollback when evaluation score < 0.60', async () => {
      const manager = new FineTuningManager({
        fineTuneFn: async () => ({ weightsPath: '/models/bad', evalScore: 0.59 }),
      });
      const data = createExamples(60);

      const result = await manager.triggerFineTuning(data, 'mistral-7b');

      expect(result.success).toBe(false);
      expect(result.rolledBack).toBe(true);
      expect(result.evaluationScore).toBe(0.59);
      expect(result.modelVersion!.status).toBe('rolled_back');
      expect(result.error).toContain('below rollback threshold');
    });

    it('triggers rollback at score 0.0', async () => {
      const manager = new FineTuningManager({
        fineTuneFn: async () => ({ weightsPath: '/models/terrible', evalScore: 0.0 }),
      });
      const data = createExamples(50);

      const result = await manager.triggerFineTuning(data, 'mistral-7b');

      expect(result.success).toBe(false);
      expect(result.rolledBack).toBe(true);
      expect(result.modelVersion!.status).toBe('rolled_back');
    });

    it('retains model at score 1.0', async () => {
      const manager = new FineTuningManager({
        fineTuneFn: async () => ({ weightsPath: '/models/perfect', evalScore: 1.0 }),
      });
      const data = createExamples(50);

      const result = await manager.triggerFineTuning(data, 'mistral-7b');

      expect(result.success).toBe(true);
      expect(result.rolledBack).toBe(false);
      expect(result.evaluationScore).toBe(1.0);
    });

    it('uses MODEL_ROLLBACK_THRESHOLD constant (0.60) as boundary', () => {
      expect(MODEL_ROLLBACK_THRESHOLD).toBe(0.60);
    });
  });

  describe('Version management', () => {
    it('returns null for active model when no fine-tuning has occurred', () => {
      const manager = new FineTuningManager();
      expect(manager.getActiveModel()).toBeNull();
    });

    it('returns empty history when no fine-tuning has occurred', () => {
      const manager = new FineTuningManager();
      expect(manager.getModelHistory()).toEqual([]);
    });

    it('sets first successful fine-tune as active version', async () => {
      const manager = new FineTuningManager({
        fineTuneFn: async () => ({ weightsPath: '/models/v1', evalScore: 0.75 }),
      });
      const data = createExamples(60);

      await manager.triggerFineTuning(data, 'mistral-7b');

      const active = manager.getActiveModel();
      expect(active).not.toBeNull();
      expect(active!.status).toBe('active');
      expect(active!.baseModel).toBe('mistral-7b');
      expect(active!.evaluationScore).toBe(0.75);
    });

    it('archives previous active version when new version succeeds', async () => {
      let callCount = 0;
      const manager = new FineTuningManager({
        fineTuneFn: async () => {
          callCount++;
          return { weightsPath: `/models/v${callCount}`, evalScore: 0.70 + callCount * 0.01 };
        },
      });
      const data = createExamples(60);

      await manager.triggerFineTuning(data, 'mistral-7b');
      await manager.triggerFineTuning(data, 'mistral-7b');

      const history = manager.getModelHistory();
      expect(history.length).toBe(2);
      expect(history[0].status).toBe('archived');
      expect(history[1].status).toBe('active');
    });

    it('keeps previous active when new version is rolled back', async () => {
      let callCount = 0;
      const manager = new FineTuningManager({
        fineTuneFn: async () => {
          callCount++;
          // First call: good score, second: bad score
          const score = callCount === 1 ? 0.80 : 0.50;
          return { weightsPath: `/models/v${callCount}`, evalScore: score };
        },
      });
      const data = createExamples(60);

      await manager.triggerFineTuning(data, 'mistral-7b');
      await manager.triggerFineTuning(data, 'mistral-7b');

      const history = manager.getModelHistory();
      expect(history.length).toBe(2);
      expect(history[0].status).toBe('active'); // previous stays active
      expect(history[1].status).toBe('rolled_back'); // new is rolled back

      const active = manager.getActiveModel();
      expect(active).not.toBeNull();
      expect(active!.evaluationScore).toBe(0.80);
    });

    it('stores correct metadata in model version', async () => {
      const manager = new FineTuningManager({
        fineTuneFn: async () => ({ weightsPath: '/models/lora-v1', evalScore: 0.85 }),
      });
      const data = createExamples(75);

      await manager.triggerFineTuning(data, 'mistral-7b-instruct-v0.2');

      const active = manager.getActiveModel();
      expect(active!.baseModel).toBe('mistral-7b-instruct-v0.2');
      expect(active!.trainingExamples).toBe(75);
      expect(active!.evaluationScore).toBe(0.85);
      expect(active!.loraWeightsPath).toBe('/models/lora-v1');
      expect(active!.createdAt).toBeInstanceOf(Date);
      expect(active!.id).toBeTruthy();
      expect(active!.version).toBe('v1');
    });

    it('returns model history as a copy (immutable)', async () => {
      const manager = new FineTuningManager({
        fineTuneFn: async () => ({ weightsPath: '/models/v1', evalScore: 0.75 }),
      });
      const data = createExamples(50);

      await manager.triggerFineTuning(data, 'mistral-7b');

      const history1 = manager.getModelHistory();
      const history2 = manager.getModelHistory();
      expect(history1).not.toBe(history2);
      expect(history1).toEqual(history2);
    });
  });

  describe('Manual rollback', () => {
    it('rolls back to a specific archived version', async () => {
      let callCount = 0;
      const manager = new FineTuningManager({
        fineTuneFn: async () => {
          callCount++;
          return { weightsPath: `/models/v${callCount}`, evalScore: 0.70 + callCount * 0.01 };
        },
      });
      const data = createExamples(60);

      await manager.triggerFineTuning(data, 'mistral-7b');
      await manager.triggerFineTuning(data, 'mistral-7b');

      const history = manager.getModelHistory();
      const archivedId = history[0].id;

      await manager.rollback(archivedId);

      const active = manager.getActiveModel();
      expect(active!.id).toBe(archivedId);
      expect(active!.status).toBe('active');

      // The previously active version should now be archived
      expect(history[1].status).toBe('archived');
    });

    it('throws error when rolling back to non-existent version', async () => {
      const manager = new FineTuningManager();
      await expect(manager.rollback('non-existent-id')).rejects.toThrow(
        "Model version 'non-existent-id' not found",
      );
    });

    it('throws error when rolling back to already active version', async () => {
      const manager = new FineTuningManager({
        fineTuneFn: async () => ({ weightsPath: '/models/v1', evalScore: 0.75 }),
      });
      const data = createExamples(50);

      await manager.triggerFineTuning(data, 'mistral-7b');
      const active = manager.getActiveModel();

      await expect(manager.rollback(active!.id)).rejects.toThrow(
        'is already active',
      );
    });
  });

  describe('Error handling', () => {
    it('handles fine-tuning function errors gracefully', async () => {
      const manager = new FineTuningManager({
        fineTuneFn: async () => {
          throw new Error('GPU out of memory');
        },
      });
      const data = createExamples(60);

      const result = await manager.triggerFineTuning(data, 'mistral-7b');

      expect(result.success).toBe(false);
      expect(result.modelVersion).toBeNull();
      expect(result.rolledBack).toBe(false);
      expect(result.error).toContain('Fine-tuning failed');
      expect(result.error).toContain('GPU out of memory');
    });

    it('does not create a version record on fine-tuning function failure', async () => {
      const manager = new FineTuningManager({
        fineTuneFn: async () => {
          throw new Error('Training failed');
        },
      });
      const data = createExamples(50);

      await manager.triggerFineTuning(data, 'mistral-7b');

      expect(manager.getModelHistory().length).toBe(0);
      expect(manager.getActiveModel()).toBeNull();
    });
  });
});
