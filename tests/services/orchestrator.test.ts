/**
 * Unit tests for OrchestratorService.
 *
 * Tests query classification, routing to subsystems, response assembly,
 * citation inclusion, and disclaimer logic.
 *
 * Requirements: 4.6, 5.1–5.5
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { OrchestratorService } from '../../src/services/orchestrator.js';
import type { RAGPipeline, RetrievalResult } from '../../src/interfaces/rag-pipeline.js';
import type { DataFetcher, DataFetchResult } from '../../src/interfaces/data-fetcher.js';
import type { LLMEngine, GenerationResult, ModelHealth } from '../../src/interfaces/llm-engine.js';
import type { ConfidenceScorer, ConfidenceResult } from '../../src/interfaces/confidence-scorer.js';
import type { Session } from '../../src/interfaces/session-manager.js';
import type { UserQuery } from '../../src/interfaces/orchestrator.js';

// --- Mock factories ---

function createMockRAGPipeline(): RAGPipeline {
  return {
    retrieve: vi.fn().mockResolvedValue({
      documents: [
        {
          id: 'doc-1',
          content: 'TypeScript is a typed superset of JavaScript that compiles to plain JavaScript.',
          similarityScore: 0.92,
          source: 'typescript-handbook',
          indexedAt: new Date('2024-01-15'),
        },
        {
          id: 'doc-2',
          content: 'TypeScript adds static type checking to JavaScript programs.',
          similarityScore: 0.85,
          source: 'ts-docs',
          indexedAt: new Date('2024-02-01'),
        },
      ],
      allBelowThreshold: false,
      queryEmbeddingTimeMs: 15,
      searchTimeMs: 42,
    } as RetrievalResult),
    indexDocument: vi.fn().mockResolvedValue({ documentId: 'new-doc', chunksCreated: 3, indexTimeMs: 500, success: true }),
    removeDocument: vi.fn().mockResolvedValue(undefined),
  };
}

function createMockDataFetcher(): DataFetcher {
  return {
    fetch: vi.fn().mockResolvedValue({
      items: [
        {
          content: 'The S&P 500 rose 1.2% today reaching new highs.',
          source: 'reuters',
          retrievedAt: new Date(),
          category: 'finance',
          verified: true,
        },
      ],
      failedCategories: [],
      allFailed: false,
    } as DataFetchResult),
  };
}

function createMockLLMEngine(): LLMEngine {
  return {
    generate: vi.fn().mockResolvedValue({
      text: 'TypeScript is a typed superset of JavaScript that adds static type checking.',
      tokenCount: 15,
      generationTimeMs: 320,
      modelVersion: 'mistral-7b-v1',
    } as GenerationResult),
    healthCheck: vi.fn().mockResolvedValue({ status: 'healthy', gpuUtilization: 0.5, vramUsageMb: 4096, queueDepth: 0 } as ModelHealth),
    getModelVersion: vi.fn().mockReturnValue('mistral-7b-v1'),
  };
}

function createMockConfidenceScorer(): ConfidenceScorer {
  return {
    score: vi.fn().mockResolvedValue({
      overallScore: 0.85,
      segments: [
        {
          text: 'TypeScript is a typed superset of JavaScript that adds static type checking.',
          sourceBasis: 'retrieved_evidence',
          supportingDocIds: ['doc-1', 'doc-2'],
          segmentConfidence: 0.85,
        },
      ],
      needsDisclaimer: false,
    } as ConfidenceResult),
  };
}

function createMockSession(overrides?: Partial<Session>): Session {
  return {
    id: 'session-123',
    userId: 'user-1',
    startedAt: new Date(),
    lastActivityAt: new Date(),
    exchanges: [],
    isActive: true,
    ...overrides,
  };
}

function createUserQuery(text: string): UserQuery {
  return {
    text,
    transcriptionConfidence: 0.95,
    sessionId: 'session-123',
    timestamp: new Date(),
  };
}

describe('OrchestratorService', () => {
  let orchestrator: OrchestratorService;
  let mockRAG: RAGPipeline;
  let mockDataFetcher: DataFetcher;
  let mockLLM: LLMEngine;
  let mockScorer: ConfidenceScorer;

  beforeEach(() => {
    mockRAG = createMockRAGPipeline();
    mockDataFetcher = createMockDataFetcher();
    mockLLM = createMockLLMEngine();
    mockScorer = createMockConfidenceScorer();

    orchestrator = new OrchestratorService({
      ragPipeline: mockRAG,
      dataFetcher: mockDataFetcher,
      llmEngine: mockLLM,
      confidenceScorer: mockScorer,
    });
  });

  describe('classifyIntent', () => {
    it('classifies real-time queries correctly', () => {
      expect(orchestrator.classifyIntent('What is the weather today?')).toBe('real-time');
      expect(orchestrator.classifyIntent('Show me the latest news')).toBe('real-time');
      expect(orchestrator.classifyIntent('What is the stock price of AAPL?')).toBe('real-time');
      expect(orchestrator.classifyIntent('Current temperature in NYC')).toBe('real-time');
    });

    it('classifies creative queries correctly', () => {
      expect(orchestrator.classifyIntent('Write a poem about spring')).toBe('creative');
      expect(orchestrator.classifyIntent('Create a story about a dragon')).toBe('creative');
      expect(orchestrator.classifyIntent('Imagine a world without gravity')).toBe('creative');
      expect(orchestrator.classifyIntent('Compose a haiku')).toBe('creative');
    });

    it('classifies factual queries correctly', () => {
      expect(orchestrator.classifyIntent('What is TypeScript?')).toBe('factual');
      expect(orchestrator.classifyIntent('How does photosynthesis work?')).toBe('factual');
      expect(orchestrator.classifyIntent('Explain the theory of relativity')).toBe('factual');
    });

    it('classifies general queries as general', () => {
      expect(orchestrator.classifyIntent('Hello')).toBe('general');
      expect(orchestrator.classifyIntent('Thanks')).toBe('general');
      expect(orchestrator.classifyIntent('Yes please')).toBe('general');
    });

    it('prioritizes real-time over other intents', () => {
      // "what is" would be factual, but "today" triggers real-time first
      expect(orchestrator.classifyIntent('What is happening today?')).toBe('real-time');
    });
  });

  describe('processQuery - factual queries', () => {
    it('routes factual queries to RAG pipeline', async () => {
      const session = createMockSession();
      const query = createUserQuery('What is TypeScript?');

      await orchestrator.processQuery(session, query);

      expect(mockRAG.retrieve).toHaveBeenCalledWith(
        'What is TypeScript?',
        expect.objectContaining({
          topK: 5,
          relevanceThreshold: 0.7,
        })
      );
      expect(mockDataFetcher.fetch).not.toHaveBeenCalled();
    });

    it('includes RAG context in LLM generation request', async () => {
      const session = createMockSession();
      const query = createUserQuery('What is TypeScript?');

      await orchestrator.processQuery(session, query);

      expect(mockLLM.generate).toHaveBeenCalledWith(
        expect.objectContaining({
          context: expect.arrayContaining([
            expect.stringContaining('doc-1'),
            expect.stringContaining('doc-2'),
          ]),
        })
      );
    });

    it('scores confidence against retrieved documents', async () => {
      const session = createMockSession();
      const query = createUserQuery('What is TypeScript?');

      await orchestrator.processQuery(session, query);

      expect(mockScorer.score).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          retrievedDocuments: expect.arrayContaining([
            expect.objectContaining({ id: 'doc-1' }),
            expect.objectContaining({ id: 'doc-2' }),
          ]),
          query: 'What is TypeScript?',
        })
      );
    });

    it('returns citations referencing supporting document IDs', async () => {
      const session = createMockSession();
      const query = createUserQuery('What is TypeScript?');

      const response = await orchestrator.processQuery(session, query);

      expect(response.citations.length).toBeGreaterThan(0);
      expect(response.citations[0]).toEqual(
        expect.objectContaining({
          documentId: expect.any(String),
          source: expect.any(String),
          claimText: expect.any(String),
        })
      );
    });

    it('returns source labels for evidence-backed segments', async () => {
      const session = createMockSession();
      const query = createUserQuery('What is TypeScript?');

      const response = await orchestrator.processQuery(session, query);

      expect(response.sourceLabels.length).toBeGreaterThan(0);
      expect(response.sourceLabels[0]).toEqual(
        expect.objectContaining({
          documentId: expect.any(String),
          source: expect.any(String),
          basis: 'retrieved_evidence',
        })
      );
    });
  });

  describe('processQuery - real-time queries', () => {
    it('routes real-time queries to Data Fetcher', async () => {
      const session = createMockSession();
      const query = createUserQuery('What is the stock market doing today?');

      await orchestrator.processQuery(session, query);

      expect(mockDataFetcher.fetch).toHaveBeenCalledWith(
        expect.objectContaining({
          text: 'What is the stock market doing today?',
          categories: expect.arrayContaining(['finance']),
        })
      );
      expect(mockRAG.retrieve).not.toHaveBeenCalled();
    });

    it('includes fetched data in LLM context', async () => {
      const session = createMockSession();
      const query = createUserQuery('Show me latest news');

      await orchestrator.processQuery(session, query);

      expect(mockLLM.generate).toHaveBeenCalledWith(
        expect.objectContaining({
          context: expect.arrayContaining([
            expect.stringContaining('reuters'),
          ]),
        })
      );
    });
  });

  describe('processQuery - creative queries', () => {
    it('routes creative queries directly to LLM without external context', async () => {
      const session = createMockSession();
      const query = createUserQuery('Write a poem about the ocean');

      await orchestrator.processQuery(session, query);

      expect(mockRAG.retrieve).not.toHaveBeenCalled();
      expect(mockDataFetcher.fetch).not.toHaveBeenCalled();
      expect(mockLLM.generate).toHaveBeenCalledWith(
        expect.objectContaining({
          context: [],
          temperature: 0.8,
        })
      );
    });
  });

  describe('processQuery - general queries', () => {
    it('routes general queries directly to LLM without external context', async () => {
      const session = createMockSession();
      const query = createUserQuery('Hello there');

      await orchestrator.processQuery(session, query);

      expect(mockRAG.retrieve).not.toHaveBeenCalled();
      expect(mockDataFetcher.fetch).not.toHaveBeenCalled();
      expect(mockLLM.generate).toHaveBeenCalledWith(
        expect.objectContaining({
          context: [],
        })
      );
    });
  });

  describe('processQuery - conversation history', () => {
    it('includes session exchanges in LLM conversation history', async () => {
      const session = createMockSession({
        exchanges: [
          {
            userMessage: 'Tell me about AI',
            assistantResponse: 'AI is artificial intelligence.',
            timestamp: new Date(),
            metadata: { confidenceScore: 0.9, sourcesUsed: [], responseTimeMs: 200 },
          },
        ],
      });
      const query = createUserQuery('Hello again');

      await orchestrator.processQuery(session, query);

      const generateCall = vi.mocked(mockLLM.generate).mock.calls[0]![0];
      expect(generateCall.conversationHistory).toHaveLength(2); // user + assistant
      expect(generateCall.conversationHistory[0]!.role).toBe('user');
      expect(generateCall.conversationHistory[0]!.content).toBe('Tell me about AI');
      expect(generateCall.conversationHistory[1]!.role).toBe('assistant');
      expect(generateCall.conversationHistory[1]!.content).toBe('AI is artificial intelligence.');
    });
  });

  describe('processQuery - error handling', () => {
    it('returns error response when LLM generation fails', async () => {
      const failingLLM: LLMEngine = {
        generate: vi.fn().mockResolvedValue({
          text: '',
          tokenCount: 0,
          generationTimeMs: 10500,
          modelVersion: 'mistral-7b-v1',
          error: 'Generation timed out',
        }),
        healthCheck: vi.fn().mockResolvedValue({ status: 'healthy', gpuUtilization: 0.5, vramUsageMb: 4096, queueDepth: 0 }),
        getModelVersion: vi.fn().mockReturnValue('mistral-7b-v1'),
      };

      orchestrator = new OrchestratorService({
        ragPipeline: mockRAG,
        dataFetcher: mockDataFetcher,
        llmEngine: failingLLM,
        confidenceScorer: mockScorer,
      });

      const session = createMockSession();
      const query = createUserQuery('What is TypeScript?');

      const response = await orchestrator.processQuery(session, query);

      expect(response.confidenceScore).toBe(0);
      expect(response.disclaimers.length).toBeGreaterThan(0);
      expect(response.text).toContain('trouble generating');
    });
  });

  describe('processQuery - disclaimers', () => {
    it('includes disclaimer when confidence is below threshold', async () => {
      const lowConfidenceScorer: ConfidenceScorer = {
        score: vi.fn().mockResolvedValue({
          overallScore: 0.4,
          segments: [
            {
              text: 'Some unverified claim.',
              sourceBasis: 'model_knowledge',
              supportingDocIds: [],
              segmentConfidence: 0.4,
            },
          ],
          needsDisclaimer: true,
        }),
      };

      orchestrator = new OrchestratorService({
        ragPipeline: mockRAG,
        dataFetcher: mockDataFetcher,
        llmEngine: mockLLM,
        confidenceScorer: lowConfidenceScorer,
      });

      const session = createMockSession();
      const query = createUserQuery('What is quantum computing?');

      const response = await orchestrator.processQuery(session, query);

      expect(response.disclaimers.length).toBeGreaterThan(0);
      expect(response.disclaimers).toContainEqual(
        expect.stringContaining('not be fully grounded')
      );
    });

    it('includes model knowledge disclaimer when segments lack evidence', async () => {
      const mixedScorer: ConfidenceScorer = {
        score: vi.fn().mockResolvedValue({
          overallScore: 0.75,
          segments: [
            {
              text: 'TypeScript is great.',
              sourceBasis: 'retrieved_evidence',
              supportingDocIds: ['doc-1'],
              segmentConfidence: 0.9,
            },
            {
              text: 'It was created in 2012.',
              sourceBasis: 'model_knowledge',
              supportingDocIds: [],
              segmentConfidence: 0.6,
            },
          ],
          needsDisclaimer: false,
        }),
      };

      orchestrator = new OrchestratorService({
        ragPipeline: mockRAG,
        dataFetcher: mockDataFetcher,
        llmEngine: mockLLM,
        confidenceScorer: mixedScorer,
      });

      const session = createMockSession();
      const query = createUserQuery('What is TypeScript?');

      const response = await orchestrator.processQuery(session, query);

      expect(response.disclaimers).toContainEqual(
        expect.stringContaining('model knowledge')
      );
    });

    it('does not include disclaimers when confidence is high and all segments are grounded', async () => {
      const session = createMockSession();
      const query = createUserQuery('What is TypeScript?');

      const response = await orchestrator.processQuery(session, query);

      // Default mock: overallScore=0.85, needsDisclaimer=false, all retrieved_evidence
      expect(response.disclaimers).toHaveLength(0);
    });
  });

  describe('processQuery - confidence score', () => {
    it('returns the confidence score from the scorer', async () => {
      const session = createMockSession();
      const query = createUserQuery('What is TypeScript?');

      const response = await orchestrator.processQuery(session, query);

      expect(response.confidenceScore).toBe(0.85);
    });
  });

  describe('decomposeTask', () => {
    it('returns at least one subtask', async () => {
      const query = createUserQuery('Do some research');
      const tasks = await orchestrator.decomposeTask(query);
      expect(tasks.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe('executeSubTasks', () => {
    it('returns results for all subtasks when all succeed', async () => {
      const session = createMockSession();
      const tasks = [
        { id: 1, description: 'Look up info', type: 'lookup' as const, dependencies: [] },
        { id: 2, description: 'Summarize results', type: 'summarization' as const, dependencies: [1] },
      ];

      const results = await orchestrator.executeSubTasks(session, tasks);

      expect(results).toHaveLength(2);
      expect(results[0]!.subtaskId).toBe(1);
      expect(results[0]!.status).toBe('completed');
      expect(results[1]!.subtaskId).toBe(2);
      expect(results[1]!.status).toBe('completed');
    });
  });

  describe('processQuery - graceful degradation', () => {
    it('continues with disclaimer when RAG pipeline throws an error', async () => {
      const failingRAG: RAGPipeline = {
        retrieve: vi.fn().mockRejectedValue(new Error('RAG retrieval timed out: Knowledge Store failed')),
        indexDocument: vi.fn().mockResolvedValue({ documentId: 'x', chunksCreated: 0, indexTimeMs: 0, success: false }),
        removeDocument: vi.fn().mockResolvedValue(undefined),
      };

      orchestrator = new OrchestratorService({
        ragPipeline: failingRAG,
        dataFetcher: mockDataFetcher,
        llmEngine: mockLLM,
        confidenceScorer: mockScorer,
      });

      const session = createMockSession();
      const query = createUserQuery('What is the theory of relativity?');

      const response = await orchestrator.processQuery(session, query);

      // Should still get a response (from LLM without RAG context)
      expect(response.text).toBeDefined();
      expect(response.text.length).toBeGreaterThan(0);
      // Should include a degradation disclaimer
      expect(response.disclaimers).toContainEqual(
        expect.stringContaining('Document retrieval was unavailable')
      );
      // LLM should still have been called (without RAG context)
      expect(mockLLM.generate).toHaveBeenCalledWith(
        expect.objectContaining({ context: [] })
      );
    });

    it('continues with disclaimer when Data Fetcher throws an error', async () => {
      const failingFetcher: DataFetcher = {
        fetch: vi.fn().mockRejectedValue(new Error('Network error: all sources unreachable')),
      };

      orchestrator = new OrchestratorService({
        ragPipeline: mockRAG,
        dataFetcher: failingFetcher,
        llmEngine: mockLLM,
        confidenceScorer: mockScorer,
      });

      const session = createMockSession();
      const query = createUserQuery('What is the current weather today?');

      const response = await orchestrator.processQuery(session, query);

      // Should still get a response
      expect(response.text).toBeDefined();
      expect(response.text.length).toBeGreaterThan(0);
      // Should include a degradation disclaimer
      expect(response.disclaimers).toContainEqual(
        expect.stringContaining('Real-time data retrieval was unavailable')
      );
    });

    it('includes category-specific disclaimer when Data Fetcher returns allFailed', async () => {
      const partiallyFailingFetcher: DataFetcher = {
        fetch: vi.fn().mockResolvedValue({
          items: [],
          failedCategories: ['weather', 'news'],
          allFailed: true,
        }),
      };

      orchestrator = new OrchestratorService({
        ragPipeline: mockRAG,
        dataFetcher: partiallyFailingFetcher,
        llmEngine: mockLLM,
        confidenceScorer: mockScorer,
      });

      const session = createMockSession();
      const query = createUserQuery('What is the weather today and latest news?');

      const response = await orchestrator.processQuery(session, query);

      expect(response.disclaimers).toContainEqual(
        expect.stringContaining('weather')
      );
      expect(response.disclaimers).toContainEqual(
        expect.stringContaining('news')
      );
    });

    it('continues with low confidence when confidence scorer throws', async () => {
      const failingScorer: ConfidenceScorer = {
        score: vi.fn().mockRejectedValue(new Error('Scorer timeout')),
      };

      orchestrator = new OrchestratorService({
        ragPipeline: mockRAG,
        dataFetcher: mockDataFetcher,
        llmEngine: mockLLM,
        confidenceScorer: failingScorer,
      });

      const session = createMockSession();
      const query = createUserQuery('What is TypeScript?');

      const response = await orchestrator.processQuery(session, query);

      // Should still return a response
      expect(response.text).toBeDefined();
      expect(response.text.length).toBeGreaterThan(0);
      // Score defaults to 0 on scorer failure
      expect(response.confidenceScore).toBe(0);
      // Needs disclaimer should be triggered
      expect(response.disclaimers).toContainEqual(
        expect.stringContaining('not be fully grounded')
      );
    });
  });
});
