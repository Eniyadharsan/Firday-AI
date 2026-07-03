/**
 * Voice Interface Service - Speech-to-Text with Faster-Whisper integration.
 *
 * Responsibility: Speech-to-text conversion via Faster-Whisper (CTranslate2) HTTP API;
 * text-to-speech synthesis; continuous listening management.
 *
 * Requirements: 1.1, 1.4
 */

import { Readable } from 'node:stream';
import { AudioStream } from '../interfaces/common-types.js';
import {
  VoiceInterface,
  TranscriptionResult,
  VoiceConfig,
  ListeningState,
} from '../interfaces/voice-interface.js';
import {
  TRANSCRIPTION_CONFIDENCE_THRESHOLD,
  VOICE_SPEED_MIN,
  VOICE_SPEED_MAX,
  VOICE_PITCH_MIN,
  VOICE_PITCH_MAX,
  SESSION_SILENCE_TIMEOUT_SECONDS,
  MAX_TRANSCRIPTION_RETRIES,
} from '../config/defaults.js';

/** Default Faster-Whisper STT server URL */
const DEFAULT_STT_URL = 'http://localhost:8001';

/** Default Coqui TTS server URL */
const DEFAULT_TTS_URL = 'http://localhost:8002';

/** Default set of available voice IDs */
const DEFAULT_AVAILABLE_VOICES: string[] = ['default', 'female-1'];

/** Silence timeout in milliseconds (derived from config constant) */
const SILENCE_TIMEOUT_MS = SESSION_SILENCE_TIMEOUT_SECONDS * 1000;

/**
 * Notification returned by listening management methods.
 */
export interface ListeningNotification {
  type: 'session-end' | 'please-repeat' | 'recognition-failed';
  message: string;
}

/**
 * Collects all chunks from a readable stream into a single Buffer.
 */
async function streamToBuffer(stream: AudioStream): Promise<Buffer> {
  const chunks: Buffer[] = [];
  for await (const chunk of stream) {
    if (Buffer.isBuffer(chunk)) {
      chunks.push(chunk);
    } else {
      chunks.push(Buffer.from(chunk as unknown as ArrayBuffer));
    }
  }
  return Buffer.concat(chunks);
}

/**
 * VoiceInterfaceService provides speech-to-text transcription
 * via the Faster-Whisper (CTranslate2) HTTP API, and text-to-speech
 * synthesis via the Coqui TTS (XTTS v2) HTTP API.
 */
export class VoiceInterfaceService implements VoiceInterface {
  private readonly sttUrl: string;
  readonly ttsUrl: string;
  readonly availableVoices: string[];
  private readonly listeningSessions: Map<string, ListeningState> = new Map();

  constructor(sttUrl?: string, ttsUrl?: string, availableVoices?: string[]) {
    this.sttUrl = sttUrl ?? process.env['STT_URL'] ?? DEFAULT_STT_URL;
    this.ttsUrl = ttsUrl ?? process.env['TTS_URL'] ?? DEFAULT_TTS_URL;
    this.availableVoices = availableVoices ?? DEFAULT_AVAILABLE_VOICES;
  }

  /**
   * Convert speech audio to text using Faster-Whisper.
   *
   * Posts the audio buffer to the Faster-Whisper API and returns
   * a TranscriptionResult including confidence scoring. If confidence
   * is below the threshold (0.50), the result includes a low-confidence
   * indicator via the confidence field.
   *
   * Requirements: 1.1, 1.4
   */
  async transcribe(audio: AudioStream): Promise<TranscriptionResult> {
    const startTime = Date.now();

    const audioBuffer = await streamToBuffer(audio);

    const formData = new FormData();
    const blob = new Blob([audioBuffer], { type: 'audio/wav' });
    formData.append('audio_file', blob, 'audio.wav');

    let response: Response;
    try {
      response = await fetch(`${this.sttUrl}/asr`, {
        method: 'POST',
        body: formData,
        headers: {
          'Accept': 'application/json',
        },
      });
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      throw new Error(`STT service unavailable: ${message}`);
    }

    if (!response.ok) {
      throw new Error(
        `STT request failed with status ${response.status}: ${response.statusText}`
      );
    }

    const data = await response.json() as {
      text?: string;
      confidence?: number;
      language?: string;
      duration?: number;
      segments?: Array<{ text: string; avg_logprob?: number }>;
    };

    const text = data.text ?? '';
    const language = data.language ?? 'en';
    const durationMs = data.duration != null
      ? Math.round(data.duration * 1000)
      : Date.now() - startTime;

    // Compute confidence: use API-provided value, or derive from segments avg_logprob
    let confidence: number;
    if (data.confidence != null) {
      confidence = data.confidence;
    } else if (data.segments && data.segments.length > 0) {
      // Convert average log probability to a 0-1 confidence score
      const avgLogProb =
        data.segments.reduce((sum, seg) => sum + (seg.avg_logprob ?? -1), 0) /
        data.segments.length;
      // Logprob is typically in [-inf, 0]; map roughly to [0, 1]
      confidence = Math.max(0, Math.min(1, Math.exp(avgLogProb)));
    } else {
      confidence = text.length > 0 ? 0.85 : 0.0;
    }

    const result: TranscriptionResult = {
      text,
      confidence,
      language,
      durationMs,
    };

    // Low-confidence indicator: if below threshold, the caller should
    // prompt the user to repeat (Requirement 1.4). The confidence value
    // itself signals this — callers check against TRANSCRIPTION_CONFIDENCE_THRESHOLD.
    if (result.confidence < TRANSCRIPTION_CONFIDENCE_THRESHOLD) {
      result.text = result.text || '';
    }

    return result;
  }

  /**
   * Convert text to speech using Coqui TTS (XTTS v2).
   *
   * Validates voice configuration boundaries, posts text + config to the
   * Coqui TTS HTTP API, and returns the audio stream from the response.
   *
   * Requirements: 1.2, 1.5
   */
  async synthesize(text: string, config: VoiceConfig): Promise<AudioStream> {
    // Validate voice configuration boundaries
    this.validateVoiceConfig(config);

    let response: Response;
    try {
      response = await fetch(`${this.ttsUrl}/api/tts`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'audio/wav',
        },
        body: JSON.stringify({
          text,
          speaker_id: config.voiceId,
          speed: config.speed,
          pitch: config.pitch,
        }),
      });
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      throw new Error(`TTS service unavailable: ${message}`);
    }

    if (!response.ok) {
      throw new Error(
        `TTS request failed with status ${response.status}: ${response.statusText}`
      );
    }

    if (!response.body) {
      throw new Error('TTS response body is empty');
    }

    // Convert the web ReadableStream to a Node.js Readable stream
    const reader = response.body.getReader();
    const readable = new Readable({
      async read() {
        const { done, value } = await reader.read();
        if (done) {
          this.push(null);
        } else {
          this.push(Buffer.from(value));
        }
      },
    });

    return readable;
  }

  /**
   * Validate voice configuration boundaries.
   * Throws an error if any parameter is out of range.
   */
  private validateVoiceConfig(config: VoiceConfig): void {
    if (config.speed < VOICE_SPEED_MIN || config.speed > VOICE_SPEED_MAX) {
      throw new Error(
        `Voice speed must be between ${VOICE_SPEED_MIN} and ${VOICE_SPEED_MAX}, got ${config.speed}`
      );
    }

    if (config.pitch < VOICE_PITCH_MIN || config.pitch > VOICE_PITCH_MAX) {
      throw new Error(
        `Voice pitch must be between ${VOICE_PITCH_MIN} and ${VOICE_PITCH_MAX}, got ${config.pitch}`
      );
    }

    if (!this.availableVoices.includes(config.voiceId)) {
      throw new Error(
        `Voice ID "${config.voiceId}" is not available. Available voices: ${this.availableVoices.join(', ')}`
      );
    }
  }

  /**
   * Start continuous listening session.
   *
   * Creates a new ListeningState for the session with isActive=true,
   * silenceDurationMs=0, and retryCount=0.
   *
   * Requirements: 1.3
   */
  startListening(sessionId: string): void {
    const state: ListeningState = {
      sessionId,
      isActive: true,
      silenceDurationMs: 0,
      retryCount: 0,
    };
    this.listeningSessions.set(sessionId, state);
  }

  /**
   * Stop listening for a session.
   *
   * Marks the session as inactive and cleans up the listening state.
   *
   * Requirements: 1.3, 1.6
   */
  stopListening(sessionId: string): void {
    const state = this.listeningSessions.get(sessionId);
    if (state) {
      state.isActive = false;
    }
    this.listeningSessions.delete(sessionId);
  }

  /**
   * Handle silence detected during a listening session.
   *
   * Updates the silence duration for the session. If the silence duration
   * reaches or exceeds 60 seconds (SESSION_SILENCE_TIMEOUT_SECONDS * 1000),
   * returns a session-end notification indicating the session is ending
   * due to inactivity.
   *
   * Requirements: 1.3, 1.6
   */
  handleSilenceDetected(sessionId: string, silenceDurationMs: number): ListeningNotification | null {
    const state = this.listeningSessions.get(sessionId);
    if (!state || !state.isActive) {
      return null;
    }

    state.silenceDurationMs = silenceDurationMs;

    if (state.silenceDurationMs >= SILENCE_TIMEOUT_MS) {
      return {
        type: 'session-end',
        message: 'Session ending due to inactivity. No speech detected for 60 seconds.',
      };
    }

    return null;
  }

  /**
   * Handle low-confidence transcription result.
   *
   * Increments the retry counter for the session. If retryCount is less than
   * MAX_TRANSCRIPTION_RETRIES (3), returns a "please repeat" prompt.
   * If retryCount reaches 3, returns a "recognition failed" notification
   * and resets the retry counter.
   *
   * Requirements: 1.4
   */
  handleLowConfidence(sessionId: string): ListeningNotification | null {
    const state = this.listeningSessions.get(sessionId);
    if (!state || !state.isActive) {
      return null;
    }

    state.retryCount += 1;

    if (state.retryCount < MAX_TRANSCRIPTION_RETRIES) {
      return {
        type: 'please-repeat',
        message: `Could not understand clearly. Please repeat your query. (Attempt ${state.retryCount} of ${MAX_TRANSCRIPTION_RETRIES})`,
      };
    }

    // After 3 consecutive failed retries, inform user and reset
    const notification: ListeningNotification = {
      type: 'recognition-failed',
      message: 'Speech could not be recognized after multiple attempts. Please try again later.',
    };
    state.retryCount = 0;
    return notification;
  }

  /**
   * Reset retry count after a successful transcription.
   *
   * Called when a transcription with sufficient confidence is received,
   * resetting the consecutive low-confidence retry counter.
   *
   * Requirements: 1.4
   */
  resetRetryCount(sessionId: string): void {
    const state = this.listeningSessions.get(sessionId);
    if (state) {
      state.retryCount = 0;
    }
  }

  /**
   * Get the current listening state for a session.
   * Returns undefined if no state exists for the session.
   */
  getListeningState(sessionId: string): ListeningState | undefined {
    return this.listeningSessions.get(sessionId);
  }
}
