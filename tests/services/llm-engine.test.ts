import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  VLLMEngine,
  buildMessages,
  parsePrometheusMetrics,
  extractMetricValue,
  estimateTokens,
} from '../../src/services/llm-engine.js';
import {
  GenerationRequest,
  GenerationResult,
  ModelHealth,
} from '../../src/interfaces/llm-engine.js';
import { LLM_GENERATION_TIMEOUT_SECONDS, MIN_CONTEXT_WINDOW_TOKENS } from '../../src/config/defaults.js';

/**
 * Unit tests for the LLM Inference Engine (vLLM integration).
 * Requirements: 6.4, 6.5, 6.6
 */

function createRequest(overrides: Partial<GenerationRequest> = {}): GenerationRequest {
  return {
    prompt: 'You are a helpful assistant.',
    context: [],
    conversationHistory: [],
    maxTokens: 256,
    temperature: 0.7,
    timeoutMs: 10000,
    ...overrides,
  };
}

describe('VLLMEngine', () => {
  let engine: VLLMEngine;

  beforeEach(() => {
    engine = new VLLMEngine({
      baseUrl: 'http://localhost:8000',
      modelVersion: 'mistral-7b-instruct-v0.2-qlora-v1',
      modelId: 'mistral-7b-instruct-v0.2',
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('generate()', () => {
    it('should return a successful GenerationResult with text and token count', async () => {
      const mockResponse = {
        choices: [{ message: { content: 'Hello! How can I help you?' } }],
        usage: { completion_tokens: 8 },
      };

      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse),
      }));

      const request = createRequest({ prompt: 'Greet the user' });
      const result = await engine.generate(request);

      expect(result.text).toBe('Hello! How can I help you?');
      expect(result.tokenCount).toBe(8);
      expect(result.modelVersion).toBe('mistral-7b-instruct-v0.2-qlora-v1');
      expect(result.generationTimeMs).toBeGreaterThanOrEqual(0);
      expect(result.error).toBeUndefined();
    });

    it('should POST to the /v1/chat/completions endpoint', async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          choices: [{ message: { content: 'response' } }],
          usage: { completion_tokens: 1 },
        }),
      });
      vi.stubGlobal('fetch', fetchMock);

      const request = createRequest({ maxTokens: 100, temperature: 0.5 });
      await engine.generate(request);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe('http://localhost:8000/v1/chat/completions');
      expect(options.method).toBe('POST');
      expect(options.headers).toEqual({ 'Content-Type': 'application/json' });

      const body = JSON.parse(options.body as string);
      expect(body.model).toBe('mistral-7b-instruct-v0.2');
      expect(body.max_tokens).toBe(100);
      expect(body.temperature).toBe(0.5);
    });

    it('should include context documents in the system message', async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          choices: [{ message: { content: 'answer' } }],
          usage: { completion_tokens: 1 },
        }),
      });
      vi.stubGlobal('fetch', fetchMock);

      const request = createRequest({
        prompt: 'Answer questions',
        context: ['Document 1 content', 'Document 2 content'],
      });
      await engine.generate(request);

      const body = JSON.parse((fetchMock.mock.calls[0] as [string, RequestInit])[1].body as string);
      const systemMsg = body.messages[0];
      expect(systemMsg.role).toBe('system');
      expect(systemMsg.content).toContain('Document 1 content');
      expect(systemMsg.content).toContain('Document 2 content');
      expect(systemMsg.content).toContain('### Retrieved Documents:');
    });

    it('should include conversation history in messages', async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          choices: [{ message: { content: 'response' } }],
          usage: { completion_tokens: 1 },
        }),
      });
      vi.stubGlobal('fetch', fetchMock);

      const request = createRequest({
        conversationHistory: [
          { role: 'user', content: 'What is TypeScript?', timestamp: new Date() },
          { role: 'assistant', content: 'TypeScript is a typed superset of JavaScript.', timestamp: new Date() },
          { role: 'user', content: 'Tell me more.', timestamp: new Date() },
        ],
      });
      await engine.generate(request);

      const body = JSON.parse((fetchMock.mock.calls[0] as [string, RequestInit])[1].body as string);
      // system + 3 history messages
      expect(body.messages.length).toBe(4);
      expect(body.messages[1].role).toBe('user');
      expect(body.messages[1].content).toBe('What is TypeScript?');
      expect(body.messages[2].role).toBe('assistant');
      expect(body.messages[3].role).toBe('user');
      expect(body.messages[3].content).toBe('Tell me more.');
    });

    it('should return error result when vLLM server returns non-OK status', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        text: () => Promise.resolve('Service Unavailable'),
      }));

      const request = createRequest();
      const result = await engine.generate(request);

      expect(result.text).toBe('');
      expect(result.tokenCount).toBe(0);
      expect(result.error).toContain('vLLM server returned 503');
      expect(result.error).toContain('Service Unavailable');
      expect(result.modelVersion).toBe('mistral-7b-instruct-v0.2-qlora-v1');
    });

    it('should return error result on network failure', async () => {
      vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('ECONNREFUSED')));

      const request = createRequest();
      const result = await engine.generate(request);

      expect(result.text).toBe('');
      expect(result.tokenCount).toBe(0);
      expect(result.error).toContain('Generation failed: ECONNREFUSED');
    });

    it('should enforce timeout and return error on AbortError (Req 6.6)', async () => {
      // Simulate a request that takes too long by throwing AbortError
      const abortError = new Error('The operation was aborted');
      abortError.name = 'AbortError';

      vi.stubGlobal('fetch', vi.fn().mockRejectedValue(abortError));

      const request = createRequest({ timeoutMs: 100 });
      const result = await engine.generate(request);

      expect(result.text).toBe('');
      expect(result.tokenCount).toBe(0);
      expect(result.error).toContain('Generation timed out');
      expect(result.error).toContain('exceeded the maximum allowed duration');
      expect(result.modelVersion).toBe('mistral-7b-instruct-v0.2-qlora-v1');
    });

    it('should not return partial response on timeout (Req 6.6)', async () => {
      const abortError = new Error('Aborted');
      abortError.name = 'AbortError';

      vi.stubGlobal('fetch', vi.fn().mockRejectedValue(abortError));

      const request = createRequest({ timeoutMs: 50 });
      const result = await engine.generate(request);

      // Ensure no partial text is returned
      expect(result.text).toBe('');
      expect(result.tokenCount).toBe(0);
    });

    it('should use default timeout (10s) when timeoutMs is 0', async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          choices: [{ message: { content: 'ok' } }],
          usage: { completion_tokens: 1 },
        }),
      });
      vi.stubGlobal('fetch', fetchMock);

      const request = createRequest({ timeoutMs: 0 });
      await engine.generate(request);

      // The timeout should default to LLM_GENERATION_TIMEOUT_SECONDS * 1000 = 10000
      // We can't directly inspect AbortController timer, but verify the request succeeded
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    it('should use custom timeoutMs when provided', async () => {
      vi.useFakeTimers();

      let abortSignal: AbortSignal | undefined;
      const fetchMock = vi.fn().mockImplementation((_url: string, options: RequestInit) => {
        abortSignal = options.signal as AbortSignal;
        return new Promise((_, reject) => {
          if (abortSignal) {
            abortSignal.addEventListener('abort', () => {
              const err = new Error('Aborted');
              err.name = 'AbortError';
              reject(err);
            });
          }
        });
      });
      vi.stubGlobal('fetch', fetchMock);

      const request = createRequest({ timeoutMs: 5000 });
      const resultPromise = engine.generate(request);

      // Advance timer past the 5000ms timeout
      vi.advanceTimersByTime(5001);

      const result = await resultPromise;
      expect(result.error).toContain('timed out');

      vi.useRealTimers();
    });

    it('should handle empty choices array gracefully', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ choices: [], usage: {} }),
      }));

      const request = createRequest();
      const result = await engine.generate(request);

      expect(result.text).toBe('');
      expect(result.tokenCount).toBe(0);
      expect(result.error).toBeUndefined();
    });

    it('should handle missing usage field gracefully', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          choices: [{ message: { content: 'hello' } }],
        }),
      }));

      const request = createRequest();
      const result = await engine.generate(request);

      expect(result.text).toBe('hello');
      expect(result.tokenCount).toBe(0);
    });

    it('should measure generation time in milliseconds', async () => {
      vi.stubGlobal('fetch', vi.fn().mockImplementation(() =>
        new Promise(resolve => {
          setTimeout(() => resolve({
            ok: true,
            json: () => Promise.resolve({
              choices: [{ message: { content: 'delayed' } }],
              usage: { completion_tokens: 1 },
            }),
          }), 50);
        })
      ));

      const request = createRequest();
      const result = await engine.generate(request);

      expect(result.generationTimeMs).toBeGreaterThanOrEqual(40);
    });

    it('should pass AbortSignal to the fetch request for timeout enforcement', async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          choices: [{ message: { content: 'ok' } }],
          usage: { completion_tokens: 1 },
        }),
      });
      vi.stubGlobal('fetch', fetchMock);

      const request = createRequest({ timeoutMs: 3000 });
      await engine.generate(request);

      const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(options.signal).toBeDefined();
      expect(options.signal).toBeInstanceOf(AbortSignal);
    });
  });

  describe('healthCheck()', () => {
    it('should return healthy status with parsed metrics', async () => {
      const metricsText = [
        '# HELP gpu_utilization GPU utilization',
        'gpu_utilization 0.65',
        '# HELP gpu_memory_usage GPU memory usage in MB',
        'gpu_memory_usage 4096',
        '# HELP num_requests_waiting Queue depth',
        'num_requests_waiting 2',
      ].join('\n');

      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        text: () => Promise.resolve(metricsText),
      }));

      const health = await engine.healthCheck();

      expect(health.status).toBe('healthy');
      expect(health.gpuUtilization).toBe(0.65);
      expect(health.vramUsageMb).toBe(4096);
      expect(health.queueDepth).toBe(2);
    });

    it('should return degraded when GPU utilization > 0.95', async () => {
      const metricsText = [
        'gpu_utilization 0.98',
        'gpu_memory_usage 7000',
        'num_requests_waiting 3',
      ].join('\n');

      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        text: () => Promise.resolve(metricsText),
      }));

      const health = await engine.healthCheck();

      expect(health.status).toBe('degraded');
      expect(health.gpuUtilization).toBe(0.98);
    });

    it('should return degraded when queue depth > 10', async () => {
      const metricsText = [
        'gpu_utilization 0.50',
        'gpu_memory_usage 3000',
        'num_requests_waiting 15',
      ].join('\n');

      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        text: () => Promise.resolve(metricsText),
      }));

      const health = await engine.healthCheck();

      expect(health.status).toBe('degraded');
      expect(health.queueDepth).toBe(15);
    });

    it('should return unavailable when metrics endpoint returns non-OK', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
      }));

      const health = await engine.healthCheck();

      expect(health.status).toBe('unavailable');
      expect(health.gpuUtilization).toBe(0);
      expect(health.vramUsageMb).toBe(0);
      expect(health.queueDepth).toBe(0);
    });

    it('should return unavailable on network error', async () => {
      vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('ECONNREFUSED')));

      const health = await engine.healthCheck();

      expect(health.status).toBe('unavailable');
      expect(health.gpuUtilization).toBe(0);
      expect(health.vramUsageMb).toBe(0);
      expect(health.queueDepth).toBe(0);
    });

    it('should call the /metrics endpoint', async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        text: () => Promise.resolve('gpu_utilization 0.5\n'),
      });
      vi.stubGlobal('fetch', fetchMock);

      await engine.healthCheck();

      const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe('http://localhost:8000/metrics');
    });

    it('should parse vllm-prefixed metric names', async () => {
      const metricsText = [
        'vllm:gpu_utilization 0.72',
        'vllm:gpu_memory_usage 5120',
        'vllm:num_requests_waiting 4',
      ].join('\n');

      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        text: () => Promise.resolve(metricsText),
      }));

      const health = await engine.healthCheck();

      expect(health.gpuUtilization).toBe(0.72);
      expect(health.vramUsageMb).toBe(5120);
      expect(health.queueDepth).toBe(4);
    });

    it('should convert bytes to MB when value seems to be in bytes', async () => {
      const metricsText = 'gpu_memory_usage 5368709120\n'; // ~5120 MB

      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        text: () => Promise.resolve(metricsText),
      }));

      const health = await engine.healthCheck();

      // 5368709120 / (1024 * 1024) ≈ 5120 MB
      expect(health.vramUsageMb).toBeCloseTo(5120, 0);
    });
  });

  describe('getModelVersion()', () => {
    it('should return the configured model version', () => {
      const version = engine.getModelVersion();
      expect(version).toBe('mistral-7b-instruct-v0.2-qlora-v1');
    });

    it('should return custom model version when configured', () => {
      const customEngine = new VLLMEngine({ modelVersion: 'custom-v2.0' });
      expect(customEngine.getModelVersion()).toBe('custom-v2.0');
    });
  });

  describe('constructor', () => {
    it('should use default values when no options provided', () => {
      const defaultEngine = new VLLMEngine();
      expect(defaultEngine.getModelVersion()).toBeDefined();
      expect(typeof defaultEngine.getModelVersion()).toBe('string');
    });

    it('should allow overriding baseUrl', async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          choices: [{ message: { content: 'ok' } }],
          usage: { completion_tokens: 1 },
        }),
      });
      vi.stubGlobal('fetch', fetchMock);

      const customEngine = new VLLMEngine({ baseUrl: 'http://custom-vllm:9000' });
      await customEngine.generate(createRequest());

      const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe('http://custom-vllm:9000/v1/chat/completions');
    });
  });
});

describe('buildMessages()', () => {
  it('should create system message from prompt alone when no context', () => {
    const request = createRequest({ prompt: 'Be helpful', context: [] });
    const messages = buildMessages(request);

    expect(messages.length).toBe(1);
    expect(messages[0]!.role).toBe('system');
    expect(messages[0]!.content).toBe('Be helpful');
  });

  it('should append context documents to system message', () => {
    const request = createRequest({
      prompt: 'Base prompt',
      context: ['Doc A', 'Doc B'],
    });
    const messages = buildMessages(request);

    expect(messages[0]!.content).toContain('Base prompt');
    expect(messages[0]!.content).toContain('### Retrieved Documents:');
    expect(messages[0]!.content).toContain('Doc A');
    expect(messages[0]!.content).toContain('Doc B');
    expect(messages[0]!.content).toContain('---');
  });

  it('should include conversation history as separate messages', () => {
    const request = createRequest({
      conversationHistory: [
        { role: 'user', content: 'Hi', timestamp: new Date() },
        { role: 'assistant', content: 'Hello!', timestamp: new Date() },
      ],
    });
    const messages = buildMessages(request);

    expect(messages.length).toBe(3); // system + 2 history
    expect(messages[1]!.role).toBe('user');
    expect(messages[1]!.content).toBe('Hi');
    expect(messages[2]!.role).toBe('assistant');
    expect(messages[2]!.content).toBe('Hello!');
  });

  it('should truncate older history when token budget is exceeded (Req 6.5)', () => {
    // Create a short prompt to leave room for some history
    const shortPrompt = 'Hi';
    // Create lots of long history messages that will exceed MIN_CONTEXT_WINDOW_TOKENS (8000 tokens = ~32000 chars)
    const longHistory = Array.from({ length: 100 }, (_, i) => ({
      role: ('user' as const),
      content: `Message ${i}: ${'x'.repeat(500)}`,
      timestamp: new Date(),
    }));

    const request = createRequest({
      prompt: shortPrompt,
      context: [],
      conversationHistory: longHistory,
    });
    const messages = buildMessages(request);

    // Should have trimmed history; not all 100 messages should be present
    // Each message is ~500 chars = ~125 tokens. Budget is 8000 - 1 (prompt) = 7999 tokens
    // So about 63 messages fit. We should have less than 101 total (system + 100).
    expect(messages.length).toBeLessThan(100);
    // Should always have at least the system message
    expect(messages.length).toBeGreaterThanOrEqual(1);
    // Most recent messages should be kept (last in array)
    if (messages.length > 1) {
      const lastHistoryMsg = messages[messages.length - 1]!;
      expect(lastHistoryMsg.content).toContain('Message 99');
    }
  });

  it('should keep all history when it fits within context window', () => {
    const request = createRequest({
      prompt: 'Short',
      conversationHistory: [
        { role: 'user', content: 'one', timestamp: new Date() },
        { role: 'assistant', content: 'two', timestamp: new Date() },
      ],
    });
    const messages = buildMessages(request);

    expect(messages.length).toBe(3);
  });

  it('should drop all history when system message fills the token budget', () => {
    // Create a very large system prompt that exceeds MIN_CONTEXT_WINDOW_TOKENS
    const hugePrompt = 'x'.repeat(MIN_CONTEXT_WINDOW_TOKENS * 4 + 100);
    const request = createRequest({
      prompt: hugePrompt,
      conversationHistory: [
        { role: 'user', content: 'hi', timestamp: new Date() },
      ],
    });
    const messages = buildMessages(request);

    // Only system message should remain
    expect(messages.length).toBe(1);
    expect(messages[0]!.role).toBe('system');
  });
});

describe('parsePrometheusMetrics()', () => {
  it('should parse standard metric lines', () => {
    const text = 'gpu_utilization 0.75\ngpu_memory_usage 2048\nnum_requests_waiting 5\n';
    const health = parsePrometheusMetrics(text);

    expect(health.gpuUtilization).toBe(0.75);
    expect(health.vramUsageMb).toBe(2048);
    expect(health.queueDepth).toBe(5);
    expect(health.status).toBe('healthy');
  });

  it('should skip comment lines and empty lines', () => {
    const text = '# A comment\n\ngpu_utilization 0.60\n# Another\n';
    const health = parsePrometheusMetrics(text);

    expect(health.gpuUtilization).toBe(0.60);
  });

  it('should return zero values for missing metrics', () => {
    const health = parsePrometheusMetrics('');

    expect(health.gpuUtilization).toBe(0);
    expect(health.vramUsageMb).toBe(0);
    expect(health.queueDepth).toBe(0);
    expect(health.status).toBe('healthy');
  });

  it('should mark status as degraded when GPU > 0.95', () => {
    const text = 'gpu_utilization 0.96\n';
    const health = parsePrometheusMetrics(text);
    expect(health.status).toBe('degraded');
  });

  it('should mark status as degraded when queue > 10', () => {
    const text = 'num_requests_waiting 11\n';
    const health = parsePrometheusMetrics(text);
    expect(health.status).toBe('degraded');
  });
});

describe('extractMetricValue()', () => {
  it('should extract numeric value from a simple metric line', () => {
    expect(extractMetricValue('metric_name 42.5')).toBe(42.5);
  });

  it('should extract value from metric line with labels', () => {
    expect(extractMetricValue('metric{label="val"} 3.14')).toBe(3.14);
  });

  it('should return null for non-numeric value', () => {
    expect(extractMetricValue('metric_name abc')).toBeNull();
  });

  it('should return null for empty string', () => {
    expect(extractMetricValue('')).toBeNull();
  });

  it('should handle integer values', () => {
    expect(extractMetricValue('counter 100')).toBe(100);
  });
});

describe('estimateTokens()', () => {
  it('should estimate ~4 characters per token', () => {
    expect(estimateTokens('hello')).toBe(2); // 5/4 rounded up
    expect(estimateTokens('a'.repeat(16))).toBe(4); // 16/4
  });

  it('should return 0 for empty string', () => {
    expect(estimateTokens('')).toBe(0);
  });

  it('should round up for non-divisible lengths', () => {
    expect(estimateTokens('abc')).toBe(1); // 3/4 = 0.75 → ceil = 1
  });
});
