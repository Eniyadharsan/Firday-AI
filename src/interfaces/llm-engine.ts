/**
 * LLM Inference Engine interfaces.
 *
 * Responsibility: Text generation via fine-tuned model;
 * context window management; timeout handling.
 */

import { Message } from './common-types.js';

export interface LLMEngine {
  /** Generate a response given context */
  generate(request: GenerationRequest): Promise<GenerationResult>;
  /** Check model health */
  healthCheck(): Promise<ModelHealth>;
  /** Get current model version */
  getModelVersion(): string;
}

export interface GenerationRequest {
  prompt: string;
  context: string[];        // RAG-retrieved documents
  conversationHistory: Message[];
  maxTokens: number;
  temperature: number;
  timeoutMs: number;        // default 10000
}

export interface GenerationResult {
  text: string;
  tokenCount: number;
  generationTimeMs: number;
  modelVersion: string;
  error?: string;
}

export interface ModelHealth {
  status: 'healthy' | 'degraded' | 'unavailable';
  gpuUtilization: number;
  vramUsageMb: number;
  queueDepth: number;
}
