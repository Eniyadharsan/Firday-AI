/**
 * TaskExecutor — helper class for multi-step task decomposition and execution.
 *
 * Breaks complex user requests into 1–10 subtasks (constrained by MAX_SUBTASKS),
 * executes them sequentially respecting dependencies, preserves completed results
 * on failure, and handles unsupported capabilities gracefully.
 *
 * Requirements: 7.1, 7.4, 7.5, 7.6
 */

import { SubTask, TaskResult, UserQuery } from '../interfaces/orchestrator.js';
import { Session } from '../interfaces/session-manager.js';
import { MAX_SUBTASKS } from '../config/defaults.js';

/** Supported task categories per Requirement 7.4 */
export const SUPPORTED_TASK_CATEGORIES: SubTask['type'][] = [
  'lookup',
  'summarization',
  'reminder',
  'calculation',
  'creative',
];

/** Keywords that indicate multi-step requests */
const SEQUENTIAL_INDICATORS = [
  ' and then ',
  ' then ',
  ' after that ',
  ' next ',
  ' finally ',
  ' also ',
  ' additionally ',
  ' followed by ',
  ' before that ',
  ' first ',
];

/** Keywords that map to subtask types */
const TYPE_KEYWORDS: Record<SubTask['type'], string[]> = {
  lookup: ['find', 'search', 'look up', 'what is', 'who is', 'where is', 'when', 'how many', 'tell me about', 'get info', 'information'],
  summarization: ['summarize', 'summary', 'brief', 'overview', 'recap', 'condense', 'shorten', 'tldr'],
  reminder: ['remind', 'reminder', 'schedule', 'alert', 'notify', 'set a reminder', 'alarm', 'calendar'],
  calculation: ['calculate', 'compute', 'math', 'add', 'subtract', 'multiply', 'divide', 'total', 'average', 'percentage', 'convert'],
  creative: ['write', 'compose', 'draft', 'create', 'generate', 'poem', 'story', 'email', 'letter', 'essay'],
};

/** Actions the assistant cannot perform (unsupported capabilities) */
const UNSUPPORTED_ACTIONS: { pattern: RegExp; description: string; alternatives: string[] }[] = [
  {
    pattern: /\b(send|deliver|transmit)\s+(an?\s+)?(email|message|text|sms)\b/i,
    description: 'sending emails or messages directly',
    alternatives: ['I can draft the message content for you to send manually', 'I can set a reminder to send it yourself'],
  },
  {
    pattern: /\b(make|place|dial)\s+(a\s+)?(phone\s*call|call)\b/i,
    description: 'making phone calls',
    alternatives: ['I can look up the phone number for you', 'I can draft what you want to say'],
  },
  {
    pattern: /\b(buy|purchase|order|checkout)\b/i,
    description: 'making purchases or placing orders',
    alternatives: ['I can look up product information and prices', 'I can help you compare options'],
  },
  {
    pattern: /\b(download|install|upload)\s+(a\s+)?(file|app|software|program)\b/i,
    description: 'downloading or installing software',
    alternatives: ['I can provide download links and instructions', 'I can summarize what the software does'],
  },
  {
    pattern: /\b(book|reserve)\s+(a\s+)?(flight|hotel|restaurant|ticket)\b/i,
    description: 'making bookings or reservations directly',
    alternatives: ['I can look up available options and prices', 'I can help you compare choices and draft a booking request'],
  },
];

/**
 * Handler function type for executing individual subtasks.
 * Consumers can inject custom execution logic or use the default placeholder.
 */
export type SubTaskHandler = (session: Session, task: SubTask) => Promise<TaskResult>;

/**
 * Classifies a text segment into a subtask type based on keyword matching.
 */
export function classifySubTaskType(text: string): SubTask['type'] {
  const lowerText = text.toLowerCase();

  for (const [type, keywords] of Object.entries(TYPE_KEYWORDS) as [SubTask['type'], string[]][]) {
    for (const keyword of keywords) {
      if (lowerText.includes(keyword)) {
        return type;
      }
    }
  }

  // Default to lookup if no specific type detected
  return 'lookup';
}

/**
 * Checks if a text segment describes an unsupported action.
 * Returns description + alternatives if unsupported, or null if supported.
 */
export function detectUnsupportedAction(text: string): { description: string; alternatives: string[] } | null {
  for (const action of UNSUPPORTED_ACTIONS) {
    if (action.pattern.test(text)) {
      return { description: action.description, alternatives: action.alternatives };
    }
  }
  return null;
}

/**
 * Splits a complex query into individual step descriptions.
 */
function splitQueryIntoSteps(text: string): string[] {
  let parts: string[] = [text];

  for (const indicator of SEQUENTIAL_INDICATORS) {
    const newParts: string[] = [];
    for (const part of parts) {
      const lowerPart = part.toLowerCase();
      const idx = lowerPart.indexOf(indicator);
      if (idx !== -1) {
        const before = part.substring(0, idx).trim();
        const after = part.substring(idx + indicator.length).trim();
        if (before) newParts.push(before);
        if (after) newParts.push(after);
      } else {
        newParts.push(part);
      }
    }
    parts = newParts;
  }

  // Also split on " and " as conjunction of separate tasks
  const finalParts: string[] = [];
  for (const part of parts) {
    const andSplit = part.split(/\s+and\s+/i);
    if (andSplit.length > 1 && andSplit.every(s => s.trim().length > 3)) {
      finalParts.push(...andSplit.map(s => s.trim()).filter(s => s.length > 0));
    } else {
      finalParts.push(part);
    }
  }

  return [...new Set(finalParts.filter(p => p.length > 0))];
}

/**
 * Default handler that executes a subtask based on its type.
 * Returns a placeholder result for each supported category.
 */
export const defaultSubTaskHandler: SubTaskHandler = async (_session, task) => {
  if (!SUPPORTED_TASK_CATEGORIES.includes(task.type)) {
    return {
      subtaskId: task.id,
      status: 'failed' as const,
      error: `Unsupported task type: ${task.type}. Supported types are: ${SUPPORTED_TASK_CATEGORIES.join(', ')}. ` +
        `You can retry this step or skip to the next one.`,
    };
  }

  switch (task.type) {
    case 'lookup':
      return { subtaskId: task.id, status: 'completed' as const, result: `Looked up information: "${task.description}"` };
    case 'summarization':
      return { subtaskId: task.id, status: 'completed' as const, result: `Summarized: "${task.description}"` };
    case 'reminder':
      return { subtaskId: task.id, status: 'completed' as const, result: `Reminder set: "${task.description}"` };
    case 'calculation':
      return { subtaskId: task.id, status: 'completed' as const, result: `Calculated: "${task.description}"` };
    case 'creative':
      return { subtaskId: task.id, status: 'completed' as const, result: `Created: "${task.description}"` };
    default:
      return {
        subtaskId: task.id,
        status: 'failed' as const,
        error: `Unsupported task type: ${task.type}. Supported types are: ${SUPPORTED_TASK_CATEGORIES.join(', ')}.`,
      };
  }
};

/**
 * TaskExecutor handles multi-step task decomposition and sequential execution.
 *
 * Features:
 * - Decomposes complex requests into 1–10 subtasks (MAX_SUBTASKS enforced)
 * - Classifies subtasks into supported categories: lookup, summarization,
 *   reminder, calculation, creative
 * - Executes subtasks sequentially respecting dependencies
 * - On failure: preserves prior completed results, identifies failed step,
 *   offers retry/skip
 * - Detects unsupported capabilities and suggests alternatives
 */
export class TaskExecutor {
  private handler: SubTaskHandler;

  constructor(handler?: SubTaskHandler) {
    this.handler = handler ?? defaultSubTaskHandler;
  }

  /**
   * Decompose a complex user request into 1–10 subtasks.
   *
   * Analyzes the query to determine if it requires multiple steps by looking
   * for sequential indicators and conjunctions. Each subtask is classified
   * by type and assigned dependencies.
   *
   * Guarantees:
   * - Always returns at least 1 subtask
   * - Never returns more than MAX_SUBTASKS (10) subtasks
   * - Each subtask is classified into a supported category
   *
   * Requirements: 7.1, 7.4
   */
  async decomposeTask(query: UserQuery): Promise<SubTask[]> {
    const text = query.text.trim();

    // Empty or trivial input → single subtask
    if (!text) {
      return [{
        id: 1,
        description: text,
        type: 'lookup',
        dependencies: [],
      }];
    }

    // Split the query into individual step descriptions
    const steps = splitQueryIntoSteps(text);

    // If only one step detected, return a single subtask
    if (steps.length <= 1) {
      return [{
        id: 1,
        description: text,
        type: classifySubTaskType(text),
        dependencies: [],
      }];
    }

    // Enforce MAX_SUBTASKS limit
    const limitedSteps = steps.slice(0, MAX_SUBTASKS);

    const subtasks: SubTask[] = limitedSteps.map((step, index) => ({
      id: index + 1,
      description: step,
      type: classifySubTaskType(step),
      dependencies: index > 0 ? [index] : [], // Each step depends on the previous one
    }));

    return subtasks;
  }

  /**
   * Execute subtasks sequentially, reporting each outcome.
   *
   * Behavior on subtask failure (Requirement 7.6):
   * - Preserves results of all previously completed subtasks
   * - Identifies the failed subtask in the error field
   * - Offers retry/skip option via the error message
   * - Stops execution (does not proceed to subsequent subtasks)
   *
   * Behavior for unsupported capabilities (Requirement 7.5):
   * - Detects actions the assistant cannot perform
   * - States what specific capability is missing
   * - Suggests at least one alternative approach
   *
   * Requirements: 7.1, 7.5, 7.6
   */
  async executeSubTasks(session: Session, tasks: SubTask[]): Promise<TaskResult[]> {
    const results: TaskResult[] = [];

    for (const task of tasks) {
      // Check if dependencies are met
      const dependenciesMet = task.dependencies.every(depId => {
        const depResult = results.find(r => r.subtaskId === depId);
        return depResult && depResult.status === 'completed';
      });

      if (!dependenciesMet) {
        results.push({
          subtaskId: task.id,
          status: 'skipped',
          error: `Skipped because a dependency (subtask ${task.dependencies.find(depId => {
            const r = results.find(res => res.subtaskId === depId);
            return !r || r.status !== 'completed';
          })}) was not completed.`,
        });
        continue;
      }

      // Check for unsupported capabilities (Requirement 7.5)
      const unsupported = detectUnsupportedAction(task.description);
      if (unsupported) {
        results.push({
          subtaskId: task.id,
          status: 'failed',
          error: `This capability is not available: ${unsupported.description}. ` +
            `Alternatives: ${unsupported.alternatives.join('; ')}. ` +
            `You can retry this step or skip to the next one.`,
        });
        // Stop execution on failure — preserve prior results
        break;
      }

      // Execute the subtask via the handler
      try {
        const result = await this.handler(session, task);
        results.push(result);

        if (result.status === 'failed') {
          // Stop on failure — preserve prior results
          break;
        }
      } catch (error) {
        results.push({
          subtaskId: task.id,
          status: 'failed',
          error: `Subtask ${task.id} failed: ${error instanceof Error ? error.message : String(error)}. ` +
            `You can retry this step or skip to the next one.`,
        });
        // Stop on failure — preserve prior results
        break;
      }
    }

    return results;
  }
}
