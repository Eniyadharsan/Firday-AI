/**
 * Orchestrator Service interfaces.
 *
 * Responsibility: Central coordination of all subsystems; routes queries,
 * assembles context, manages multi-step tasks.
 */

import { SourceLabel, Citation } from './common-types.js';
import { Session } from './session-manager.js';

export interface Orchestrator {
  /** Process a user query end-to-end */
  processQuery(session: Session, query: UserQuery): Promise<AssistantResponse>;
  /** Decompose complex tasks into subtasks */
  decomposeTask(query: UserQuery): Promise<SubTask[]>;
  /** Execute subtasks sequentially */
  executeSubTasks(session: Session, tasks: SubTask[]): Promise<TaskResult[]>;
}

export interface UserQuery {
  text: string;
  transcriptionConfidence: number;
  sessionId: string;
  timestamp: Date;
}

export interface AssistantResponse {
  text: string;
  confidenceScore: number;
  sourceLabels: SourceLabel[];
  citations: Citation[];
  disclaimers: string[];
}

export interface SubTask {
  id: number;
  description: string;
  type: 'lookup' | 'summarization' | 'reminder' | 'calculation' | 'creative';
  dependencies: number[];
}

export interface TaskResult {
  subtaskId: number;
  status: 'completed' | 'failed' | 'skipped';
  result?: string;
  error?: string;
}
