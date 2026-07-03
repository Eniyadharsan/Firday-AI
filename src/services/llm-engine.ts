/**
 * LLM Inference Engine implementation using vLLM server.
 *
 * Communicates with a vLLM instance (OpenAI-compatible API) for text generation,
 * enforces generation timeouts, and reports model health metrics.
 *
 * Requirements: 6.4, 6.5, 6.6
 */

import {
  LLMEngine,
  GenerationRequest,
  GenerationResult,
  ModelHealth,
} from '../interfaces/llm-engine.js';
import { LLM_GENERATION_TIMEOUT_SECONDS, MIN_CONTEXT_WINDOW_TOKENS } from '../config/defaults.js';

/** Environment-based vLLM server URL (default: http://localhost:8000) */
const VLLM_URL = process.env['VLLM_URL'] || 'http://localhost:8000';

/** Active model version string (configurable via env) */
const MODEL_VERSION = process.env['MODEL_VERSION'] || 'mistral-7b-instruct-v0.2-qlora-v1';

/** Model ID used in vLLM completions API */
const MODEL_ID = process.env['VLLM_MODEL_ID'] || 'mistral-7b-instruct-v0.2';

/**
 * Estimate the number of tokens in a string.
 * Uses a simple heuristic of ~4 characters per token (common for English text).
 */
function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

/**
 * Build the messages array for the chat completions API from the generation request.
 * If total tokens exceed MIN_CONTEXT_WINDOW_TOKENS (8000), conversation history
 * is truncated from the oldest messages first to fit within the limit.
 */
function buildMessages(request: GenerationRequest): Array<{ role: string; content: string }> {
  const messages: Array<{ role: string; content: string }> = [];

  // System context: prompt + retrieved documents
  let systemContent = request.prompt;
  if (request.context.length > 0) {
    systemContent += '\n\n### Retrieved Documents:\n' + request.context.join('\n---\n');
  }
  messages.push({ role: 'system', content: systemContent });

  // Calculate tokens used by the system message
  const systemTokens = estimateTokens(systemContent);
  const availableTokens = MIN_CONTEXT_WINDOW_TOKENS - systemTokens;

  // Truncate conversation history if it exceeds available token budget
  let historyMessages = request.conversationHistory.map(msg => ({
    role: msg.role,
    content: msg.content,
  }));

  if (availableTokens > 0) {
    // Calculate total history tokens
    let totalHistoryTokens = 0;
    for (const msg of historyMessages) {
      totalHistoryTokens += estimateTokens(msg.content);
    }

    // If history exceeds budget, trim from oldest (beginning of array)
    if (totalHistoryTokens > availableTokens) {
      const trimmed: typeof historyMessages = [];
      let remaining = availableTokens;

      // Keep most recent messages that fit (iterate from newest)
      for (let i = historyMessages.length - 1; i >= 0; i--) {
        const msg = historyMessages[i]!;
        const msgTokens = estimateTokens(msg.content);
        if (msgTokens <= remaining) {
          trimmed.unshift(msg);
          remaining -= msgTokens;
        } else {
          break;
        }
      }
      historyMessages = trimmed;
    }
  } else {
    // No room for history at all
    historyMessages = [];
  }

  for (const msg of historyMessages) {
    messages.push(msg);
  }

  return messages;
}

/**
 * VLLMEngine implements the LLMEngine interface using a vLLM server
 * with OpenAI-compatible chat/completions endpoint.
 */
export class VLLMEngine implements LLMEngine {
  private readonly baseUrl: string;
  private readonly modelVersion: string;
  private readonly modelId: string;

  constructor(options?: { baseUrl?: string; modelVersion?: string; modelId?: string }) {
    this.baseUrl = options?.baseUrl ?? VLLM_URL;
    this.modelVersion = options?.modelVersion ?? MODEL_VERSION;
    this.modelId = options?.modelId ?? MODEL_ID;
  }

  /**
   * Generate a response by sending prompt, context, and conversation history
   * to the vLLM chat completions endpoint.
   *
   * Enforces a timeout (default 10 seconds). On timeout the generation is
   * terminated and an error result is returned with no partial content.
   */
  async generate(request: GenerationRequest): Promise<GenerationResult> {
    const timeoutMs = request.timeoutMs > 0
      ? request.timeoutMs
      : LLM_GENERATION_TIMEOUT_SECONDS * 1000;

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    const startTime = Date.now();

    try {
      const messages = buildMessages(request);

      const response = await fetch(`${this.baseUrl}/v1/chat/completions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: this.modelId,
          messages,
          max_tokens: request.maxTokens,
          temperature: request.temperature,
        }),
        signal: controller.signal,
      });

      clearTimeout(timer);

      if (!response.ok) {
        const errorBody = await response.text().catch(() => 'Unknown error');
        return {
          text: '',
          tokenCount: 0,
          generationTimeMs: Date.now() - startTime,
          modelVersion: this.modelVersion,
          error: `vLLM server returned ${response.status}: ${errorBody}`,
        };
      }

      const data = await response.json() as {
        choices?: Array<{ message?: { content?: string } }>;
        usage?: { completion_tokens?: number };
      };

      const generatedText = data.choices?.[0]?.message?.content ?? '';
      const tokenCount = data.usage?.completion_tokens ?? 0;

      return {
        text: generatedText,
        tokenCount,
        generationTimeMs: Date.now() - startTime,
        modelVersion: this.modelVersion,
      };
    } catch (error: unknown) {
      clearTimeout(timer);

      const elapsed = Date.now() - startTime;

      // AbortError indicates timeout was triggered
      if (error instanceof Error && error.name === 'AbortError') {
        return {
          text: '',
          tokenCount: 0,
          generationTimeMs: elapsed,
          modelVersion: this.modelVersion,
          error: 'Generation timed out: request exceeded the maximum allowed duration',
        };
      }

      // Network or other unexpected errors
      const message = error instanceof Error ? error.message : 'Unknown error';
      return {
        text: '',
        tokenCount: 0,
        generationTimeMs: elapsed,
        modelVersion: this.modelVersion,
        error: `Generation failed: ${message}`,
      };
    }
  }

  /**
   * Check model health by querying the vLLM metrics endpoint.
   * Reports GPU utilization, VRAM usage, and queue depth.
   */
  async healthCheck(): Promise<ModelHealth> {
    try {
      const response = await fetch(`${this.baseUrl}/metrics`, {
        method: 'GET',
        signal: AbortSignal.timeout(5000),
      });

      if (!response.ok) {
        return {
          status: 'unavailable',
          gpuUtilization: 0,
          vramUsageMb: 0,
          queueDepth: 0,
        };
      }

      const metricsText = await response.text();
      const health = parsePrometheusMetrics(metricsText);
      return health;
    } catch {
      return {
        status: 'unavailable',
        gpuUtilization: 0,
        vramUsageMb: 0,
        queueDepth: 0,
      };
    }
  }

  /**
   * Return the active model version string.
   */
  getModelVersion(): string {
    return this.modelVersion;
  }
}

/**
 * Parse Prometheus-format metrics text from vLLM and extract
 * GPU utilization, VRAM usage, and queue depth.
 */
function parsePrometheusMetrics(metricsText: string): ModelHealth {
  let gpuUtilization = 0;
  let vramUsageMb = 0;
  let queueDepth = 0;

  for (const line of metricsText.split('\n')) {
    // Skip comments and empty lines
    if (line.startsWith('#') || line.trim() === '') continue;

    if (line.startsWith('vllm:gpu_utilization') || line.startsWith('gpu_utilization')) {
      const value = extractMetricValue(line);
      if (value !== null) gpuUtilization = value;
    } else if (line.startsWith('vllm:gpu_memory_usage') || line.startsWith('gpu_memory_usage')) {
      const value = extractMetricValue(line);
      // Convert bytes to MB if value seems to be in bytes
      if (value !== null) vramUsageMb = value > 10000 ? value / (1024 * 1024) : value;
    } else if (line.startsWith('vllm:num_requests_waiting') || line.startsWith('num_requests_waiting')) {
      const value = extractMetricValue(line);
      if (value !== null) queueDepth = value;
    }
  }

  // Determine health status based on metrics
  let status: 'healthy' | 'degraded' | 'unavailable';
  if (gpuUtilization > 0.95 || queueDepth > 10) {
    status = 'degraded';
  } else {
    status = 'healthy';
  }

  return { status, gpuUtilization, vramUsageMb, queueDepth };
}

/**
 * Extract numeric value from a Prometheus metric line.
 * Format: `metric_name{labels} value` or `metric_name value`
 */
function extractMetricValue(line: string): number | null {
  // Match the last numeric value on the line
  const parts = line.trim().split(/\s+/);
  const lastPart = parts[parts.length - 1];
  if (lastPart === undefined) return null;
  const value = parseFloat(lastPart);
  return isNaN(value) ? null : value;
}

export { buildMessages, parsePrometheusMetrics, extractMetricValue, estimateTokens };
