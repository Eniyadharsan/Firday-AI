import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { Readable } from 'stream';
import { VoiceInterfaceService } from '../../src/services/voice-interface.js';
import {
  TRANSCRIPTION_CONFIDENCE_THRESHOLD,
  SESSION_SILENCE_TIMEOUT_SECONDS,
  MAX_TRANSCRIPTION_RETRIES,
} from '../../src/config/defaults.js';

/**
 * Creates a readable stream from a buffer for testing.
 */
function createAudioStream(data: Buffer = Buffer.from('fake-audio-data')): NodeJS.ReadableStream {
  return Readable.from([data]);
}

describe('VoiceInterfaceService', () => {
  let service: VoiceInterfaceService;

  beforeEach(() => {
    service = new VoiceInterfaceService('http://localhost:8001');
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('transcribe()', () => {
    it('should return TranscriptionResult with text, confidence, language, and durationMs', async () => {
      const mockResponse = {
        text: 'Hello world',
        confidence: 0.95,
        language: 'en',
        duration: 1.5,
      };

      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse),
      }));

      const audio = createAudioStream();
      const result = await service.transcribe(audio);

      expect(result).toEqual({
        text: 'Hello world',
        confidence: 0.95,
        language: 'en',
        durationMs: 1500,
      });
    });

    it('should return low confidence when confidence < 0.50 (threshold)', async () => {
      const mockResponse = {
        text: 'mumble',
        confidence: 0.3,
        language: 'en',
        duration: 2.0,
      };

      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse),
      }));

      const audio = createAudioStream();
      const result = await service.transcribe(audio);

      expect(result.confidence).toBeLessThan(TRANSCRIPTION_CONFIDENCE_THRESHOLD);
      expect(result.confidence).toBe(0.3);
      expect(result.text).toBe('mumble');
    });

    it('should derive confidence from segments avg_logprob when confidence not provided', async () => {
      const mockResponse = {
        text: 'Hello from segments',
        language: 'en',
        duration: 1.0,
        segments: [
          { text: 'Hello', avg_logprob: -0.1 },
          { text: 'from segments', avg_logprob: -0.2 },
        ],
      };

      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse),
      }));

      const audio = createAudioStream();
      const result = await service.transcribe(audio);

      // avg_logprob mean = (-0.1 + -0.2) / 2 = -0.15
      // confidence = exp(-0.15) ≈ 0.861
      expect(result.confidence).toBeGreaterThan(0.8);
      expect(result.confidence).toBeLessThan(0.9);
    });

    it('should default to 0.85 confidence when no confidence data and text is present', async () => {
      const mockResponse = {
        text: 'Hello',
        language: 'en',
        duration: 1.0,
      };

      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse),
      }));

      const audio = createAudioStream();
      const result = await service.transcribe(audio);

      expect(result.confidence).toBe(0.85);
    });

    it('should default to 0.0 confidence when no confidence data and text is empty', async () => {
      const mockResponse = {
        text: '',
        language: 'en',
        duration: 0.5,
      };

      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse),
      }));

      const audio = createAudioStream();
      const result = await service.transcribe(audio);

      expect(result.confidence).toBe(0.0);
    });

    it('should throw on network failure', async () => {
      vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('ECONNREFUSED')));

      const audio = createAudioStream();
      await expect(service.transcribe(audio)).rejects.toThrow('STT service unavailable: ECONNREFUSED');
    });

    it('should throw on non-OK HTTP response', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
      }));

      const audio = createAudioStream();
      await expect(service.transcribe(audio)).rejects.toThrow(
        'STT request failed with status 500: Internal Server Error'
      );
    });

    it('should post audio to the correct STT endpoint', async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ text: 'test', confidence: 0.9, language: 'en', duration: 1 }),
      });
      vi.stubGlobal('fetch', fetchMock);

      const audio = createAudioStream();
      await service.transcribe(audio);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe('http://localhost:8001/asr');
      expect(options.method).toBe('POST');
    });

    it('should default language to en when not provided by API', async () => {
      const mockResponse = {
        text: 'Hello',
        confidence: 0.9,
        duration: 1.0,
      };

      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse),
      }));

      const audio = createAudioStream();
      const result = await service.transcribe(audio);

      expect(result.language).toBe('en');
    });

    it('should use STT_URL from environment variable when no URL provided in constructor', async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ text: 'test', confidence: 0.9, language: 'en', duration: 1 }),
      });
      vi.stubGlobal('fetch', fetchMock);

      process.env['STT_URL'] = 'http://custom-stt:9000';
      const envService = new VoiceInterfaceService();
      const audio = createAudioStream();
      await envService.transcribe(audio);

      const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe('http://custom-stt:9000/asr');

      delete process.env['STT_URL'];
    });
  });

  describe('synthesize()', () => {
    let ttsService: VoiceInterfaceService;

    beforeEach(() => {
      ttsService = new VoiceInterfaceService(
        'http://localhost:8001',
        'http://localhost:8002',
        ['default', 'female-1']
      );
    });

    it('should reject speed below minimum (0.5)', async () => {
      await expect(
        ttsService.synthesize('hello', { speed: 0.4, pitch: 1.0, voiceId: 'default' })
      ).rejects.toThrow('Voice speed must be between 0.5 and 2');
    });

    it('should reject speed above maximum (2.0)', async () => {
      await expect(
        ttsService.synthesize('hello', { speed: 2.1, pitch: 1.0, voiceId: 'default' })
      ).rejects.toThrow('Voice speed must be between 0.5 and 2');
    });

    it('should reject pitch below minimum (0.5)', async () => {
      await expect(
        ttsService.synthesize('hello', { speed: 1.0, pitch: 0.3, voiceId: 'default' })
      ).rejects.toThrow('Voice pitch must be between 0.5 and 2');
    });

    it('should reject pitch above maximum (2.0)', async () => {
      await expect(
        ttsService.synthesize('hello', { speed: 1.0, pitch: 2.5, voiceId: 'default' })
      ).rejects.toThrow('Voice pitch must be between 0.5 and 2');
    });

    it('should reject an unknown voiceId', async () => {
      await expect(
        ttsService.synthesize('hello', { speed: 1.0, pitch: 1.0, voiceId: 'unknown-voice' })
      ).rejects.toThrow('Voice ID "unknown-voice" is not available');
    });

    it('should accept valid boundary values (speed=0.5, pitch=2.0)', async () => {
      const mockBody = {
        getReader: () => ({
          read: vi.fn()
            .mockResolvedValueOnce({ done: false, value: new Uint8Array([1, 2, 3]) })
            .mockResolvedValueOnce({ done: true, value: undefined }),
        }),
      };
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        body: mockBody,
      }));

      const stream = await ttsService.synthesize('hello', {
        speed: 0.5,
        pitch: 2.0,
        voiceId: 'default',
      });
      expect(stream).toBeDefined();
    });

    it('should POST to the correct TTS endpoint with text and config', async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        body: {
          getReader: () => ({
            read: vi.fn().mockResolvedValueOnce({ done: true, value: undefined }),
          }),
        },
      });
      vi.stubGlobal('fetch', fetchMock);

      await ttsService.synthesize('Hello world', {
        speed: 1.5,
        pitch: 1.2,
        voiceId: 'female-1',
      });

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe('http://localhost:8002/api/tts');
      expect(options.method).toBe('POST');
      expect(options.headers).toEqual({
        'Content-Type': 'application/json',
        'Accept': 'audio/wav',
      });
      const body = JSON.parse(options.body as string);
      expect(body).toEqual({
        text: 'Hello world',
        speaker_id: 'female-1',
        speed: 1.5,
        pitch: 1.2,
      });
    });

    it('should return a readable audio stream on success', async () => {
      const audioChunk = new Uint8Array([0x52, 0x49, 0x46, 0x46]); // RIFF header start
      const mockBody = {
        getReader: () => ({
          read: vi.fn()
            .mockResolvedValueOnce({ done: false, value: audioChunk })
            .mockResolvedValueOnce({ done: true, value: undefined }),
        }),
      };
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        body: mockBody,
      }));

      const stream = await ttsService.synthesize('test', {
        speed: 1.0,
        pitch: 1.0,
        voiceId: 'default',
      });

      // Read the stream
      const chunks: Buffer[] = [];
      for await (const chunk of stream) {
        chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk as unknown as ArrayBuffer));
      }
      const result = Buffer.concat(chunks);
      expect(result).toEqual(Buffer.from(audioChunk));
    });

    it('should throw on network failure', async () => {
      vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('ECONNREFUSED')));

      await expect(
        ttsService.synthesize('hello', { speed: 1.0, pitch: 1.0, voiceId: 'default' })
      ).rejects.toThrow('TTS service unavailable: ECONNREFUSED');
    });

    it('should throw on non-OK HTTP response', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        statusText: 'Service Unavailable',
      }));

      await expect(
        ttsService.synthesize('hello', { speed: 1.0, pitch: 1.0, voiceId: 'default' })
      ).rejects.toThrow('TTS request failed with status 503: Service Unavailable');
    });

    it('should throw when response body is empty', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        body: null,
      }));

      await expect(
        ttsService.synthesize('hello', { speed: 1.0, pitch: 1.0, voiceId: 'default' })
      ).rejects.toThrow('TTS response body is empty');
    });

    it('should use TTS_URL from environment variable when no URL provided', async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        body: {
          getReader: () => ({
            read: vi.fn().mockResolvedValueOnce({ done: true, value: undefined }),
          }),
        },
      });
      vi.stubGlobal('fetch', fetchMock);

      process.env['TTS_URL'] = 'http://custom-tts:9001';
      const envService = new VoiceInterfaceService();
      await envService.synthesize('hello', { speed: 1.0, pitch: 1.0, voiceId: 'default' });

      const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe('http://custom-tts:9001/api/tts');

      delete process.env['TTS_URL'];
    });
  });

  describe('startListening() / stopListening()', () => {
    it('should create a listening state with isActive=true when startListening is called', () => {
      service.startListening('session-1');
      const state = service.getListeningState('session-1');
      expect(state).toBeDefined();
      expect(state!.isActive).toBe(true);
      expect(state!.sessionId).toBe('session-1');
      expect(state!.silenceDurationMs).toBe(0);
      expect(state!.retryCount).toBe(0);
    });

    it('should remove listening state when stopListening is called', () => {
      service.startListening('session-1');
      service.stopListening('session-1');
      const state = service.getListeningState('session-1');
      expect(state).toBeUndefined();
    });

    it('should not throw when stopping a non-existent session', () => {
      expect(() => service.stopListening('non-existent')).not.toThrow();
    });

    it('should support multiple concurrent sessions', () => {
      service.startListening('session-1');
      service.startListening('session-2');
      expect(service.getListeningState('session-1')).toBeDefined();
      expect(service.getListeningState('session-2')).toBeDefined();
      service.stopListening('session-1');
      expect(service.getListeningState('session-1')).toBeUndefined();
      expect(service.getListeningState('session-2')).toBeDefined();
    });
  });

  describe('handleSilenceDetected()', () => {
    it('should return null when silence is below 60 seconds', () => {
      service.startListening('session-1');
      const result = service.handleSilenceDetected('session-1', 30000);
      expect(result).toBeNull();
    });

    it('should return session-end notification at exactly 60 seconds of silence', () => {
      service.startListening('session-1');
      const result = service.handleSilenceDetected('session-1', 60000);
      expect(result).not.toBeNull();
      expect(result!.type).toBe('session-end');
      expect(result!.message).toContain('Session ending due to inactivity');
    });

    it('should return session-end notification when silence exceeds 60 seconds', () => {
      service.startListening('session-1');
      const result = service.handleSilenceDetected('session-1', 75000);
      expect(result).not.toBeNull();
      expect(result!.type).toBe('session-end');
    });

    it('should return null for non-existent session', () => {
      const result = service.handleSilenceDetected('non-existent', 60000);
      expect(result).toBeNull();
    });

    it('should return null for inactive session', () => {
      service.startListening('session-1');
      service.stopListening('session-1');
      const result = service.handleSilenceDetected('session-1', 60000);
      expect(result).toBeNull();
    });

    it('should update the silence duration on the state', () => {
      service.startListening('session-1');
      service.handleSilenceDetected('session-1', 25000);
      const state = service.getListeningState('session-1');
      expect(state!.silenceDurationMs).toBe(25000);
    });
  });

  describe('handleLowConfidence()', () => {
    it('should return please-repeat on first low-confidence result', () => {
      service.startListening('session-1');
      const result = service.handleLowConfidence('session-1');
      expect(result).not.toBeNull();
      expect(result!.type).toBe('please-repeat');
      expect(result!.message).toContain('Please repeat');
    });

    it('should return please-repeat on second low-confidence result', () => {
      service.startListening('session-1');
      service.handleLowConfidence('session-1'); // 1st
      const result = service.handleLowConfidence('session-1'); // 2nd
      expect(result!.type).toBe('please-repeat');
      expect(result!.message).toContain('Attempt 2');
    });

    it('should return recognition-failed after 3 consecutive low-confidence results', () => {
      service.startListening('session-1');
      service.handleLowConfidence('session-1'); // 1st - please repeat
      service.handleLowConfidence('session-1'); // 2nd - please repeat
      const result = service.handleLowConfidence('session-1'); // 3rd - recognition failed
      expect(result).not.toBeNull();
      expect(result!.type).toBe('recognition-failed');
      expect(result!.message).toContain('could not be recognized');
    });

    it('should reset retry count after recognition-failed', () => {
      service.startListening('session-1');
      service.handleLowConfidence('session-1'); // 1st
      service.handleLowConfidence('session-1'); // 2nd
      service.handleLowConfidence('session-1'); // 3rd - resets
      const state = service.getListeningState('session-1');
      expect(state!.retryCount).toBe(0);
    });

    it('should return null for non-existent session', () => {
      const result = service.handleLowConfidence('non-existent');
      expect(result).toBeNull();
    });

    it('should return null for inactive session', () => {
      service.startListening('session-1');
      service.stopListening('session-1');
      const result = service.handleLowConfidence('session-1');
      expect(result).toBeNull();
    });
  });

  describe('resetRetryCount()', () => {
    it('should reset retry count to 0 after successful transcription', () => {
      service.startListening('session-1');
      service.handleLowConfidence('session-1'); // retryCount = 1
      service.handleLowConfidence('session-1'); // retryCount = 2
      service.resetRetryCount('session-1');
      const state = service.getListeningState('session-1');
      expect(state!.retryCount).toBe(0);
    });

    it('should not throw for non-existent session', () => {
      expect(() => service.resetRetryCount('non-existent')).not.toThrow();
    });

    it('should allow retry cycle to restart after reset', () => {
      service.startListening('session-1');
      service.handleLowConfidence('session-1'); // 1
      service.handleLowConfidence('session-1'); // 2
      service.resetRetryCount('session-1');
      // After reset, next low-confidence should give please-repeat (attempt 1 again)
      const result = service.handleLowConfidence('session-1');
      expect(result!.type).toBe('please-repeat');
      expect(result!.message).toContain('Attempt 1');
    });
  });
});
