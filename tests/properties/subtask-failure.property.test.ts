/**
 * Property Test: Subtask Failure Preservation (Property 19)
 *
 * **Validates: Requirements 7.6**
 *
 * Generates multi-step executions with failures at position N and verifies:
 * - Results 1..N-1 are preserved (status: completed)
 * - Subtask N is correctly identified as failed
 */

import { describe, it, expect } from 'vitest';
import fc from 'fast-check';
import { TaskExecutor } from '../../src/services/task-executor';
import type { SubTask, TaskResult } from '../../src/interfaces/orchestrator';
import type { Session } from '../../src/interfaces/session-manager';

/** Create a mock session for testing */
function createMockSession(): Session {
  return {
    id: 'test-session-1',
    userId: 'test-user',
    startedAt: new Date(),
    lastActivityAt: new Date(),
    exchanges: [],
    isActive: true,
  };
}

/** Create N subtasks with sequential dependencies */
function createSubTasks(count: number): SubTask[] {
  return Array.from({ length: count }, (_, i) => ({
    id: i + 1,
    description: `subtask ${i + 1} action`,
    type: 'lookup' as const,
    dependencies: i > 0 ? [i] : [],
  }));
}

describe('Property 19: Subtask Failure Preservation', () => {
  /**
   * **Validates: Requirements 7.6**
   *
   * When subtask N fails, all subtasks 1..N-1 have their results preserved
   * (status: completed) and subtask N is marked as failed.
   */
  it('preserves prior results when a subtask fails', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 2, max: 8 }),
        fc.integer({ min: 1, max: 8 }),
        async (totalTasks, failAtRaw) => {
          // Ensure failAt is within range
          const failAt = ((failAtRaw - 1) % totalTasks) + 1;
          const session = createMockSession();

          // Create a handler that fails at position `failAt`
          let executionCount = 0;
          const handler = async (_session: Session, task: SubTask): Promise<TaskResult> => {
            executionCount++;
            if (task.id === failAt) {
              return {
                subtaskId: task.id,
                status: 'failed',
                error: `Subtask ${task.id} failed intentionally`,
              };
            }
            return {
              subtaskId: task.id,
              status: 'completed',
              result: `Result for subtask ${task.id}`,
            };
          };

          const executor = new TaskExecutor(handler);
          const subtasks = createSubTasks(totalTasks);
          const results = await executor.executeSubTasks(session, subtasks);

          // All results before failAt should be completed
          for (let i = 0; i < failAt - 1; i++) {
            expect(results[i].status).toBe('completed');
            expect(results[i].subtaskId).toBe(i + 1);
            expect(results[i].result).toBeDefined();
          }

          // The failed subtask should be identified
          const failedResult = results.find((r) => r.subtaskId === failAt);
          expect(failedResult).toBeDefined();
          expect(failedResult!.status).toBe('failed');
          expect(failedResult!.error).toBeDefined();

          // No subtasks after failAt should have been executed
          for (const result of results) {
            expect(result.subtaskId).toBeLessThanOrEqual(failAt);
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 7.6**
   *
   * When all subtasks succeed, all results are preserved with completed status.
   */
  it('preserves all results when no failures occur', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 1, max: 10 }),
        async (totalTasks) => {
          const session = createMockSession();

          // Handler that always succeeds
          const handler = async (_session: Session, task: SubTask): Promise<TaskResult> => ({
            subtaskId: task.id,
            status: 'completed',
            result: `Result for subtask ${task.id}`,
          });

          const executor = new TaskExecutor(handler);
          const subtasks = createSubTasks(totalTasks);
          const results = await executor.executeSubTasks(session, subtasks);

          // All subtasks should be completed
          expect(results.length).toBe(totalTasks);
          for (let i = 0; i < totalTasks; i++) {
            expect(results[i].status).toBe('completed');
            expect(results[i].subtaskId).toBe(i + 1);
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 7.6**
   *
   * Failure at position 1 means no prior results exist — only the failure is returned.
   */
  it('handles failure at first subtask with no prior results', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 1, max: 10 }),
        async (totalTasks) => {
          const session = createMockSession();

          // Handler that fails on the first subtask
          const handler = async (_session: Session, task: SubTask): Promise<TaskResult> => {
            if (task.id === 1) {
              return {
                subtaskId: task.id,
                status: 'failed',
                error: 'First subtask failed',
              };
            }
            return {
              subtaskId: task.id,
              status: 'completed',
              result: `Result for subtask ${task.id}`,
            };
          };

          const executor = new TaskExecutor(handler);
          const subtasks = createSubTasks(totalTasks);
          const results = await executor.executeSubTasks(session, subtasks);

          // Only the first (failed) result
          expect(results.length).toBe(1);
          expect(results[0].subtaskId).toBe(1);
          expect(results[0].status).toBe('failed');
        },
      ),
      { numRuns: 100 },
    );
  });
});
