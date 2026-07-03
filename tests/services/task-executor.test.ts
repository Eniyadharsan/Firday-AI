/**
 * Unit tests for TaskExecutor — multi-step task decomposition and execution.
 *
 * Covers:
 * - Decomposition bounds (always 1–10 subtasks)
 * - Failure preservation (prior results retained on failure)
 * - Unsupported task detection with alternatives
 * - Task category classification
 * - Dependency-based skipping
 *
 * Requirements: 7.1, 7.4, 7.5, 7.6
 */

import { describe, it, expect, vi } from 'vitest';
import {
  TaskExecutor,
  classifySubTaskType,
  detectUnsupportedAction,
  SUPPORTED_TASK_CATEGORIES,
  defaultSubTaskHandler,
} from '../../src/services/task-executor.js';
import type { SubTask, TaskResult, UserQuery } from '../../src/interfaces/orchestrator.js';
import type { Session } from '../../src/interfaces/session-manager.js';
import { MAX_SUBTASKS } from '../../src/config/defaults.js';

// --- Helpers ---

function createUserQuery(text: string): UserQuery {
  return {
    text,
    transcriptionConfidence: 0.95,
    sessionId: 'session-test',
    timestamp: new Date(),
  };
}

function createMockSession(): Session {
  return {
    id: 'session-test',
    userId: 'user-1',
    startedAt: new Date(),
    lastActivityAt: new Date(),
    exchanges: [],
    isActive: true,
  };
}

describe('TaskExecutor', () => {
  describe('decomposeTask — bounds enforcement', () => {
    const executor = new TaskExecutor();

    it('returns at least 1 subtask for a simple query', async () => {
      const query = createUserQuery('Find the capital of France');
      const tasks = await executor.decomposeTask(query);

      expect(tasks.length).toBeGreaterThanOrEqual(1);
      expect(tasks.length).toBeLessThanOrEqual(MAX_SUBTASKS);
    });

    it('returns at least 1 subtask for an empty query', async () => {
      const query = createUserQuery('');
      const tasks = await executor.decomposeTask(query);

      expect(tasks.length).toBe(1);
    });

    it('returns multiple subtasks for a multi-step request', async () => {
      const query = createUserQuery('Search for TypeScript tutorials and then summarize the best one');
      const tasks = await executor.decomposeTask(query);

      expect(tasks.length).toBeGreaterThanOrEqual(2);
      expect(tasks.length).toBeLessThanOrEqual(MAX_SUBTASKS);
    });

    it('never exceeds MAX_SUBTASKS (10) even for very complex queries', async () => {
      // Build a query with more than 10 parts
      const parts = Array.from({ length: 15 }, (_, i) => `step ${i + 1} find item ${i}`);
      const complexQuery = parts.join(' and then ');
      const query = createUserQuery(complexQuery);
      const tasks = await executor.decomposeTask(query);

      expect(tasks.length).toBeLessThanOrEqual(MAX_SUBTASKS);
      expect(tasks.length).toBeGreaterThanOrEqual(1);
    });

    it('assigns sequential IDs starting from 1', async () => {
      const query = createUserQuery('Look up weather and then calculate the average temperature');
      const tasks = await executor.decomposeTask(query);

      tasks.forEach((task, index) => {
        expect(task.id).toBe(index + 1);
      });
    });

    it('assigns dependencies so each step depends on the previous', async () => {
      const query = createUserQuery('Find data and then summarize it and then write a report');
      const tasks = await executor.decomposeTask(query);

      expect(tasks[0]!.dependencies).toEqual([]);
      for (let i = 1; i < tasks.length; i++) {
        expect(tasks[i]!.dependencies).toContain(i); // depends on previous task ID
      }
    });

    it('MAX_SUBTASKS constant is 10', () => {
      expect(MAX_SUBTASKS).toBe(10);
    });
  });

  describe('decomposeTask — task category classification', () => {
    const executor = new TaskExecutor();

    it('classifies lookup tasks', async () => {
      const query = createUserQuery('Find the population of Japan');
      const tasks = await executor.decomposeTask(query);
      expect(tasks[0]!.type).toBe('lookup');
    });

    it('classifies summarization tasks', async () => {
      const query = createUserQuery('Summarize this article');
      const tasks = await executor.decomposeTask(query);
      expect(tasks[0]!.type).toBe('summarization');
    });

    it('classifies reminder tasks', async () => {
      const query = createUserQuery('Remind me to buy groceries at 5pm');
      const tasks = await executor.decomposeTask(query);
      expect(tasks[0]!.type).toBe('reminder');
    });

    it('classifies calculation tasks', async () => {
      const query = createUserQuery('Calculate 15% of 240');
      const tasks = await executor.decomposeTask(query);
      expect(tasks[0]!.type).toBe('calculation');
    });

    it('classifies creative tasks', async () => {
      const query = createUserQuery('Write a poem about the sunset');
      const tasks = await executor.decomposeTask(query);
      expect(tasks[0]!.type).toBe('creative');
    });

    it('defaults to lookup for unrecognized categories', async () => {
      const query = createUserQuery('Do something vague please');
      const tasks = await executor.decomposeTask(query);
      expect(tasks[0]!.type).toBe('lookup');
    });
  });

  describe('executeSubTasks — successful execution', () => {
    const executor = new TaskExecutor();
    const session = createMockSession();

    it('executes all subtasks when all succeed', async () => {
      const tasks: SubTask[] = [
        { id: 1, description: 'Look up info', type: 'lookup', dependencies: [] },
        { id: 2, description: 'Summarize results', type: 'summarization', dependencies: [1] },
        { id: 3, description: 'Write a report', type: 'creative', dependencies: [2] },
      ];

      const results = await executor.executeSubTasks(session, tasks);

      expect(results).toHaveLength(3);
      expect(results.every(r => r.status === 'completed')).toBe(true);
    });

    it('returns a result for each supported task type', async () => {
      const tasks: SubTask[] = SUPPORTED_TASK_CATEGORIES.map((type, index) => ({
        id: index + 1,
        description: `Task of type ${type}`,
        type,
        dependencies: index > 0 ? [index] : [],
      }));

      const results = await executor.executeSubTasks(session, tasks);

      expect(results).toHaveLength(SUPPORTED_TASK_CATEGORIES.length);
      results.forEach(r => {
        expect(r.status).toBe('completed');
        expect(r.result).toBeDefined();
      });
    });
  });

  describe('executeSubTasks — failure preservation (Requirement 7.6)', () => {
    const session = createMockSession();

    it('preserves completed results when a subtask fails', async () => {
      const failingHandler = vi.fn()
        .mockResolvedValueOnce({ subtaskId: 1, status: 'completed', result: 'Step 1 done' })
        .mockResolvedValueOnce({ subtaskId: 2, status: 'completed', result: 'Step 2 done' })
        .mockResolvedValueOnce({ subtaskId: 3, status: 'failed', error: 'Network error' });

      const executor = new TaskExecutor(failingHandler);

      const tasks: SubTask[] = [
        { id: 1, description: 'Step 1', type: 'lookup', dependencies: [] },
        { id: 2, description: 'Step 2', type: 'summarization', dependencies: [1] },
        { id: 3, description: 'Step 3', type: 'calculation', dependencies: [2] },
        { id: 4, description: 'Step 4', type: 'creative', dependencies: [3] },
      ];

      const results = await executor.executeSubTasks(session, tasks);

      // Steps 1 & 2 completed, step 3 failed, step 4 not reached
      expect(results).toHaveLength(3);
      expect(results[0]!.status).toBe('completed');
      expect(results[0]!.result).toBe('Step 1 done');
      expect(results[1]!.status).toBe('completed');
      expect(results[1]!.result).toBe('Step 2 done');
      expect(results[2]!.status).toBe('failed');
      expect(results[2]!.error).toBe('Network error');
    });

    it('identifies the failed subtask by ID', async () => {
      const failingHandler = vi.fn()
        .mockResolvedValueOnce({ subtaskId: 1, status: 'completed', result: 'Done' })
        .mockResolvedValueOnce({ subtaskId: 2, status: 'failed', error: 'Timeout' });

      const executor = new TaskExecutor(failingHandler);

      const tasks: SubTask[] = [
        { id: 1, description: 'Step 1', type: 'lookup', dependencies: [] },
        { id: 2, description: 'Step 2', type: 'calculation', dependencies: [1] },
      ];

      const results = await executor.executeSubTasks(session, tasks);
      const failedResult = results.find(r => r.status === 'failed');

      expect(failedResult).toBeDefined();
      expect(failedResult!.subtaskId).toBe(2);
    });

    it('stops execution after first failure (does not run subsequent tasks)', async () => {
      const handler = vi.fn()
        .mockResolvedValueOnce({ subtaskId: 1, status: 'failed', error: 'First failure' });

      const executor = new TaskExecutor(handler);

      const tasks: SubTask[] = [
        { id: 1, description: 'Step 1', type: 'lookup', dependencies: [] },
        { id: 2, description: 'Step 2', type: 'creative', dependencies: [1] },
        { id: 3, description: 'Step 3', type: 'calculation', dependencies: [2] },
      ];

      const results = await executor.executeSubTasks(session, tasks);

      expect(results).toHaveLength(1);
      expect(results[0]!.status).toBe('failed');
      expect(handler).toHaveBeenCalledTimes(1);
    });

    it('preserves all prior results on exception thrown by handler', async () => {
      const handler = vi.fn()
        .mockResolvedValueOnce({ subtaskId: 1, status: 'completed', result: 'OK' })
        .mockRejectedValueOnce(new Error('Unexpected crash'));

      const executor = new TaskExecutor(handler);

      const tasks: SubTask[] = [
        { id: 1, description: 'Step 1', type: 'lookup', dependencies: [] },
        { id: 2, description: 'Step 2', type: 'calculation', dependencies: [1] },
      ];

      const results = await executor.executeSubTasks(session, tasks);

      expect(results).toHaveLength(2);
      expect(results[0]!.status).toBe('completed');
      expect(results[0]!.result).toBe('OK');
      expect(results[1]!.status).toBe('failed');
      expect(results[1]!.error).toContain('Unexpected crash');
      expect(results[1]!.error).toContain('retry');
    });

    it('offers retry/skip option in failure error message', async () => {
      const handler = vi.fn()
        .mockRejectedValueOnce(new Error('Something went wrong'));

      const executor = new TaskExecutor(handler);

      const tasks: SubTask[] = [
        { id: 1, description: 'Step 1', type: 'lookup', dependencies: [] },
      ];

      const results = await executor.executeSubTasks(session, tasks);

      expect(results[0]!.error).toContain('retry');
      expect(results[0]!.error).toContain('skip');
    });
  });

  describe('executeSubTasks — unsupported capabilities (Requirement 7.5)', () => {
    const executor = new TaskExecutor();
    const session = createMockSession();

    it('detects unsupported "send email" action and returns alternatives', async () => {
      const tasks: SubTask[] = [
        { id: 1, description: 'Send an email to John', type: 'lookup', dependencies: [] },
      ];

      const results = await executor.executeSubTasks(session, tasks);

      expect(results[0]!.status).toBe('failed');
      expect(results[0]!.error).toContain('not available');
      expect(results[0]!.error).toContain('sending emails');
      expect(results[0]!.error).toContain('draft');
    });

    it('detects unsupported "make a call" action and returns alternatives', async () => {
      const tasks: SubTask[] = [
        { id: 1, description: 'Make a phone call to support', type: 'lookup', dependencies: [] },
      ];

      const results = await executor.executeSubTasks(session, tasks);

      expect(results[0]!.status).toBe('failed');
      expect(results[0]!.error).toContain('not available');
      expect(results[0]!.error).toContain('phone calls');
      expect(results[0]!.error).toContain('look up the phone number');
    });

    it('detects unsupported "buy/purchase" action and returns alternatives', async () => {
      const tasks: SubTask[] = [
        { id: 1, description: 'Buy a ticket to the concert', type: 'lookup', dependencies: [] },
      ];

      const results = await executor.executeSubTasks(session, tasks);

      expect(results[0]!.status).toBe('failed');
      expect(results[0]!.error).toContain('not available');
      expect(results[0]!.error).toContain('purchases');
    });

    it('detects unsupported "book/reserve" action and returns alternatives', async () => {
      const tasks: SubTask[] = [
        { id: 1, description: 'Book a flight to Paris', type: 'lookup', dependencies: [] },
      ];

      const results = await executor.executeSubTasks(session, tasks);

      expect(results[0]!.status).toBe('failed');
      expect(results[0]!.error).toContain('not available');
      expect(results[0]!.error).toContain('bookings');
    });

    it('preserves completed results when unsupported action is in later step', async () => {
      const tasks: SubTask[] = [
        { id: 1, description: 'Find info about hotels', type: 'lookup', dependencies: [] },
        { id: 2, description: 'Book a hotel room', type: 'lookup', dependencies: [1] },
      ];

      const results = await executor.executeSubTasks(session, tasks);

      expect(results).toHaveLength(2);
      expect(results[0]!.status).toBe('completed');
      expect(results[0]!.result).toBeDefined();
      expect(results[1]!.status).toBe('failed');
      expect(results[1]!.error).toContain('not available');
    });

    it('offers retry/skip on unsupported capability failure', async () => {
      const tasks: SubTask[] = [
        { id: 1, description: 'Send a message to Alice', type: 'lookup', dependencies: [] },
      ];

      const results = await executor.executeSubTasks(session, tasks);

      expect(results[0]!.error).toContain('retry');
      expect(results[0]!.error).toContain('skip');
    });
  });

  describe('executeSubTasks — dependency handling', () => {
    const session = createMockSession();

    it('skips a task if its dependency failed', async () => {
      const handler = vi.fn()
        .mockResolvedValueOnce({ subtaskId: 1, status: 'failed', error: 'Oops' });

      const executor = new TaskExecutor(handler);

      // Tasks without dependency chain break: task 2 depends on task 1
      // but since execution stops on failure, task 2 won't be reached anyway
      const tasks: SubTask[] = [
        { id: 1, description: 'Step 1', type: 'lookup', dependencies: [] },
        { id: 2, description: 'Step 2', type: 'lookup', dependencies: [1] },
      ];

      const results = await executor.executeSubTasks(session, tasks);

      expect(results).toHaveLength(1);
      expect(results[0]!.status).toBe('failed');
    });

    it('skips a task whose dependency was skipped', async () => {
      // Use an executor where task 2 has dependency on task 1 (which fails)
      // And task 3 also depends on task 1 — but since we break on failure,
      // we test with independent dependencies
      const executor = new TaskExecutor();

      // Task 2 depends on task 99 which doesn't exist
      const tasks: SubTask[] = [
        { id: 1, description: 'Find info', type: 'lookup', dependencies: [] },
        { id: 2, description: 'Summarize', type: 'summarization', dependencies: [99] },
      ];

      const results = await executor.executeSubTasks(session, tasks);

      expect(results[0]!.status).toBe('completed');
      expect(results[1]!.status).toBe('skipped');
      expect(results[1]!.error).toContain('dependency');
    });
  });

  describe('classifySubTaskType', () => {
    it('classifies lookup keywords', () => {
      expect(classifySubTaskType('find the nearest restaurant')).toBe('lookup');
      expect(classifySubTaskType('search for TypeScript tutorials')).toBe('lookup');
      expect(classifySubTaskType('what is the meaning of life')).toBe('lookup');
      expect(classifySubTaskType('who is the president')).toBe('lookup');
    });

    it('classifies summarization keywords', () => {
      expect(classifySubTaskType('summarize this document')).toBe('summarization');
      expect(classifySubTaskType('give me an overview')).toBe('summarization');
      expect(classifySubTaskType('provide a brief recap')).toBe('summarization');
    });

    it('classifies reminder keywords', () => {
      expect(classifySubTaskType('remind me at 3pm')).toBe('reminder');
      expect(classifySubTaskType('schedule a meeting')).toBe('reminder');
      expect(classifySubTaskType('set a reminder for tomorrow')).toBe('reminder');
    });

    it('classifies calculation keywords', () => {
      expect(classifySubTaskType('calculate the total cost')).toBe('calculation');
      expect(classifySubTaskType('compute the average')).toBe('calculation');
      expect(classifySubTaskType('convert 5 miles to km')).toBe('calculation');
    });

    it('classifies creative keywords', () => {
      expect(classifySubTaskType('write a short story')).toBe('creative');
      expect(classifySubTaskType('compose an email')).toBe('creative');
      expect(classifySubTaskType('draft a letter')).toBe('creative');
    });

    it('defaults to lookup for unrecognized text', () => {
      expect(classifySubTaskType('something random')).toBe('lookup');
      expect(classifySubTaskType('just do it')).toBe('lookup');
    });
  });

  describe('detectUnsupportedAction', () => {
    it('returns null for supported actions', () => {
      expect(detectUnsupportedAction('Find the weather')).toBeNull();
      expect(detectUnsupportedAction('Summarize this text')).toBeNull();
      expect(detectUnsupportedAction('Calculate 2 + 2')).toBeNull();
    });

    it('detects send email/message', () => {
      const result = detectUnsupportedAction('Send an email to John');
      expect(result).not.toBeNull();
      expect(result!.description).toContain('sending emails');
      expect(result!.alternatives.length).toBeGreaterThanOrEqual(1);
    });

    it('detects make a call', () => {
      const result = detectUnsupportedAction('Make a phone call');
      expect(result).not.toBeNull();
      expect(result!.description).toContain('phone calls');
      expect(result!.alternatives.length).toBeGreaterThanOrEqual(1);
    });

    it('detects purchase actions', () => {
      const result = detectUnsupportedAction('Buy a new laptop');
      expect(result).not.toBeNull();
      expect(result!.description).toContain('purchases');
      expect(result!.alternatives.length).toBeGreaterThanOrEqual(1);
    });

    it('detects booking actions', () => {
      const result = detectUnsupportedAction('Book a flight to Tokyo');
      expect(result).not.toBeNull();
      expect(result!.description).toContain('bookings');
      expect(result!.alternatives.length).toBeGreaterThanOrEqual(1);
    });

    it('detects download/install actions', () => {
      const result = detectUnsupportedAction('Download a file from the server');
      expect(result).not.toBeNull();
      expect(result!.description).toContain('downloading');
      expect(result!.alternatives.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe('defaultSubTaskHandler', () => {
    const session = createMockSession();

    it('handles all supported task categories', async () => {
      for (const type of SUPPORTED_TASK_CATEGORIES) {
        const task: SubTask = { id: 1, description: `Test ${type}`, type, dependencies: [] };
        const result = await defaultSubTaskHandler(session, task);
        expect(result.status).toBe('completed');
        expect(result.result).toBeDefined();
      }
    });
  });
});
