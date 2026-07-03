/**
 * Orchestrator Service implementation.
 *
 * Responsibility: Central coordination of all subsystems; routes queries,
 * assembles context, manages multi-step tasks.
 *
 * Implements graceful degradation: if RAG or Data Fetcher is unavailable,
 * the system continues with reduced capability and appropriate disclaimers.
 * Errors in one exchange do not corrupt session state.
 *
 * Requirements: 4.6, 5.1–5.5, 7.1, 7.4, 7.5, 7.6, 8.1
 */

import {
  Orchestrator,
  UserQuery,
  AssistantResponse,
  SubTask,
  TaskResult,
} from '../interfaces/orchestrator.js';
import { Session } from '../interfaces/session-manager.js';
import { RAGPipeline } from '../interfaces/rag-pipeline.js';
import { DataFetcher, DataCategory } from '../interfaces/data-fetcher.js';
import { LLMEngine } from '../interfaces/llm-engine.js';
import { ConfidenceScorer } from '../interfaces/confidence-scorer.js';
import { RetrievedDocument } from '../interfaces/rag-pipeline.js';
import { DataItem } from '../interfaces/data-fetcher.js';
import { Message, SourceLabel, Citation } from '../interfaces/common-types.js';
import { MAX_SUBTASKS, RAG_TOP_K, RAG_RELEVANCE_THRESHOLD } from '../config/defaults.js';

/** Query intent classification */
export type QueryIntent = 'factual' | 'real-time' | 'creative' | 'general';

/** Dependencies injected into the orchestrator */
export interface OrchestratorDeps {
  ragPipeline: RAGPipeline;
  dataFetcher: DataFetcher;
  llmEngine: LLMEngine;
  confidenceScorer: ConfidenceScorer;
}

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

/** Real-time query indicators */
const REAL_TIME_KEYWORDS = [
  'today', 'now', 'current', 'latest', 'recent', 'live',
  'weather', 'stock', 'price', 'news', 'score', 'trending',
];

/** Creative query indicators */
const CREATIVE_KEYWORDS = [
  'write', 'compose', 'create', 'imagine', 'draft', 'poem',
  'story', 'haiku', 'fiction', 'novel',
];

/** Factual query indicators */
const FACTUAL_KEYWORDS = [
  'what is', 'who is', 'who invented', 'who created', 'who discovered',
  'how does', 'explain', 'define',
  'describe', 'history of', 'meaning of', 'theory',
];

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
 * Classifies a text segment into a subtask type based on keyword matching.
 */
function classifySubTaskType(text: string): SubTask['type'] {
  const lowerText = text.toLowerCase();

  for (const [type, keywords] of Object.entries(TYPE_KEYWORDS) as [SubTask['type'], string[]][]) {
    for (const keyword of keywords) {
      if (lowerText.includes(keyword)) {
        return type;
      }
    }
  }

  return 'lookup';
}

/**
 * Checks if a text segment describes an unsupported action.
 */
function detectUnsupportedAction(text: string): { description: string; alternatives: string[] } | null {
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
 * Infers data categories from a query for the Data Fetcher.
 */
function inferCategories(text: string): DataCategory[] {
  const lower = text.toLowerCase();
  const categories: DataCategory[] = [];

  if (lower.includes('news') || lower.includes('headline')) categories.push('news');
  if (lower.includes('weather') || lower.includes('temperature') || lower.includes('forecast')) categories.push('weather');
  if (lower.includes('stock') || lower.includes('market') || lower.includes('finance') || lower.includes('price')) categories.push('finance');
  if (lower.includes('sport') || lower.includes('score') || lower.includes('game')) categories.push('sports');

  if (categories.length === 0) categories.push('web_search');

  return categories;
}

/**
 * OrchestratorService implements the Orchestrator interface.
 *
 * Handles query classification, routing to subsystems, multi-step task
 * decomposition, and sequential execution with failure preservation.
 */
export class OrchestratorService implements Orchestrator {
  private ragPipeline: RAGPipeline;
  private dataFetcher: DataFetcher;
  private llmEngine: LLMEngine;
  private confidenceScorer: ConfidenceScorer;

  constructor(deps: OrchestratorDeps) {
    this.ragPipeline = deps.ragPipeline;
    this.dataFetcher = deps.dataFetcher;
    this.llmEngine = deps.llmEngine;
    this.confidenceScorer = deps.confidenceScorer;
  }

  /**
   * Classify the intent of a user query.
   */
  classifyIntent(text: string): QueryIntent {
    const lower = text.toLowerCase();

    // Check real-time first (highest priority)
    if (REAL_TIME_KEYWORDS.some(k => lower.includes(k))) {
      return 'real-time';
    }

    // Check creative
    if (CREATIVE_KEYWORDS.some(k => lower.includes(k))) {
      return 'creative';
    }

    // Check factual
    if (FACTUAL_KEYWORDS.some(k => lower.includes(k))) {
      return 'factual';
    }

    return 'general';
  }

  /**
   * Process a user query end-to-end with graceful degradation.
   *
   * Routes to appropriate subsystems based on intent classification,
   * assembles response with citations, source labels, and disclaimers.
   *
   * Graceful degradation:
   * - If RAG pipeline times out or errors: continue without RAG context, add disclaimer
   * - If Data Fetcher fails: inform user, continue without data
   * - If TTS fails: return text response without speech (handled at app layer)
   * - Session preservation: errors in one exchange don't corrupt session state
   *
   * Requirements: 4.6, 5.1–5.5, 8.1
   */
  async processQuery(session: Session, query: UserQuery): Promise<AssistantResponse> {
    const intent = this.classifyIntent(query.text);

    let retrievedDocuments: RetrievedDocument[] = [];
    let fetchedData: DataItem[] = [];
    let context: string[] = [];
    let temperature = 0.7;
    const degradationDisclaimers: string[] = [];

    // Route to appropriate subsystems with graceful degradation
    if (intent === 'factual') {
      try {
        const retrievalResult = await this.ragPipeline.retrieve(query.text, {
          topK: RAG_TOP_K,
          relevanceThreshold: RAG_RELEVANCE_THRESHOLD,
          timeoutMs: 10000,
        });
        retrievedDocuments = retrievalResult.documents;
        context = retrievedDocuments.map(d => `[${d.id}] ${d.content}`);
      } catch (error: unknown) {
        // Graceful degradation: RAG unavailable, continue with disclaimer
        const message = error instanceof Error ? error.message : 'Unknown error';
        degradationDisclaimers.push(
          'Document retrieval was unavailable. This response may not be grounded in stored knowledge.'
        );
        // Log but don't fail the entire query
        console.error(`[Orchestrator] RAG pipeline error: ${message}`);
      }
    } else if (intent === 'real-time') {
      try {
        const categories = inferCategories(query.text);
        const fetchResult = await this.dataFetcher.fetch({
          text: query.text,
          categories,
          maxAgeMinutes: 15,
          timeoutMs: 10000,
        });

        if (fetchResult.allFailed) {
          degradationDisclaimers.push(
            `Real-time data is currently unavailable for: ${fetchResult.failedCategories.join(', ')}. ` +
            'Response is generated without real-time data.'
          );
        } else {
          fetchedData = fetchResult.items;
          context = fetchedData.map(item => `[${item.source}] ${item.content}`);

          if (fetchResult.failedCategories.length > 0) {
            degradationDisclaimers.push(
              `Some data sources were unavailable: ${fetchResult.failedCategories.join(', ')}.`
            );
          }
        }
      } catch (error: unknown) {
        // Graceful degradation: Data Fetcher unavailable
        const message = error instanceof Error ? error.message : 'Unknown error';
        degradationDisclaimers.push(
          'Real-time data retrieval was unavailable. Response is generated without current data.'
        );
        console.error(`[Orchestrator] Data Fetcher error: ${message}`);
      }
    } else if (intent === 'creative') {
      temperature = 0.8;
    }

    // Build conversation history from session exchanges
    const conversationHistory: Message[] = session.exchanges.flatMap(ex => [
      { role: 'user' as const, content: ex.userMessage, timestamp: ex.timestamp },
      { role: 'assistant' as const, content: ex.assistantResponse, timestamp: ex.timestamp },
    ]);

    // Generate response via LLM
    const generation = await this.llmEngine.generate({
      prompt: query.text,
      context,
      conversationHistory,
      maxTokens: 1024,
      temperature,
      timeoutMs: 10000,
    });

    // Handle generation error
    if (generation.error || !generation.text) {
      return {
        text: "I'm having trouble generating a response, please try again.",
        confidenceScore: 0,
        sourceLabels: [],
        citations: [],
        disclaimers: ['Response generation failed: ' + (generation.error || 'unknown error')],
      };
    }

    // Score confidence with graceful degradation
    let confidenceResult;
    try {
      confidenceResult = await this.confidenceScorer.score(generation.text, {
        retrievedDocuments,
        fetchedData,
        query: query.text,
      });
    } catch (error: unknown) {
      // If confidence scorer fails, default to low confidence with disclaimer
      const message = error instanceof Error ? error.message : 'Unknown error';
      console.error(`[Orchestrator] Confidence scorer error: ${message}`);
      confidenceResult = {
        overallScore: 0,
        segments: [{ text: generation.text, sourceBasis: 'model_knowledge' as const, supportingDocIds: [], segmentConfidence: 0 }],
        needsDisclaimer: true,
      };
    }

    // Build source labels from segments
    const sourceLabels: SourceLabel[] = confidenceResult.segments
      .filter(seg => seg.sourceBasis === 'retrieved_evidence' && seg.supportingDocIds.length > 0)
      .map(seg => {
        const docId = seg.supportingDocIds[0] ?? '';
        return {
          documentId: docId,
          source: retrievedDocuments.find(d => d.id === docId)?.source || 'unknown',
          basis: seg.sourceBasis,
        };
      });

    // Build citations from retrieved documents
    const citations: Citation[] = confidenceResult.segments
      .filter(seg => seg.sourceBasis === 'retrieved_evidence' && seg.supportingDocIds.length > 0)
      .map(seg => {
        const docId = seg.supportingDocIds[0] ?? '';
        return {
          claimText: seg.text,
          documentId: docId,
          source: retrievedDocuments.find(d => d.id === docId)?.source || 'unknown',
        };
      });

    // Build disclaimers (combine degradation + confidence disclaimers)
    const disclaimers: string[] = [...degradationDisclaimers];
    if (confidenceResult.needsDisclaimer) {
      disclaimers.push('This response may not be fully grounded in verified sources and should be independently verified.');
    }
    if (confidenceResult.segments.some(seg => seg.sourceBasis === 'model_knowledge')) {
      disclaimers.push('Some portions of this response are generated from model knowledge and may not be independently verified.');
    }

    return {
      text: generation.text,
      confidenceScore: confidenceResult.overallScore,
      sourceLabels,
      citations,
      disclaimers,
    };
  }

  /**
   * Decompose a complex user request into 1–10 subtasks.
   *
   * Uses heuristics to detect multi-step requests by looking for sequential
   * indicators, conjunctions, and multiple action verbs.
   *
   * Requirements: 7.1 (max 10 subtasks), 7.4 (supported categories)
   */
  async decomposeTask(query: UserQuery): Promise<SubTask[]> {
    const text = query.text.trim();

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

    // Build subtasks from detected steps (enforce MAX_SUBTASKS limit)
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
   * On subtask failure: preserves prior results, identifies failed step,
   * offers retry/skip via the error field.
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

      // Check for unsupported capabilities
      const unsupported = detectUnsupportedAction(task.description);
      if (unsupported) {
        results.push({
          subtaskId: task.id,
          status: 'failed',
          error: `This capability is not available: ${unsupported.description}. ` +
            `Alternatives: ${unsupported.alternatives.join('; ')}. ` +
            `You can retry this step or skip to the next one.`,
        });
        // Stop execution on failure - preserve prior results
        break;
      }

      // Execute the subtask
      try {
        const result = await this.executeSingleSubTask(session, task);
        results.push(result);

        if (result.status === 'failed') {
          break;
        }
      } catch (error) {
        results.push({
          subtaskId: task.id,
          status: 'failed',
          error: `Subtask ${task.id} failed: ${error instanceof Error ? error.message : String(error)}. ` +
            `You can retry this step or skip to the next one.`,
        });
        break;
      }
    }

    return results;
  }

  /**
   * Execute a single subtask based on its type.
   */
  private async executeSingleSubTask(_session: Session, task: SubTask): Promise<TaskResult> {
    const supportedTypes: SubTask['type'][] = ['lookup', 'summarization', 'reminder', 'calculation', 'creative'];

    if (!supportedTypes.includes(task.type)) {
      return {
        subtaskId: task.id,
        status: 'failed',
        error: `Unsupported task type: ${task.type}. Supported types are: ${supportedTypes.join(', ')}. ` +
          `You can retry this step or skip to the next one.`,
      };
    }

    // Execute based on type (placeholder implementations)
    switch (task.type) {
      case 'lookup':
        return {
          subtaskId: task.id,
          status: 'completed',
          result: `Looked up information: "${task.description}"`,
        };
      case 'summarization':
        return {
          subtaskId: task.id,
          status: 'completed',
          result: `Summarized: "${task.description}"`,
        };
      case 'reminder':
        return {
          subtaskId: task.id,
          status: 'completed',
          result: `Reminder set: "${task.description}"`,
        };
      case 'calculation':
        return {
          subtaskId: task.id,
          status: 'completed',
          result: `Calculated: "${task.description}"`,
        };
      case 'creative':
        return {
          subtaskId: task.id,
          status: 'completed',
          result: `Created: "${task.description}"`,
        };
    }
  }
}
