/**
 * Voice Interface interfaces.
 *
 * Responsibility: Speech-to-text and text-to-speech conversion;
 * continuous listening management; voice configuration.
 */

import { AudioStream } from './common-types.js';

export interface VoiceInterface {
  /** Convert speech to text */
  transcribe(audio: AudioStream): Promise<TranscriptionResult>;
  /** Convert text to speech */
  synthesize(text: string, config: VoiceConfig): Promise<AudioStream>;
  /** Start continuous listening session */
  startListening(sessionId: string): void;
  /** Stop listening */
  stopListening(sessionId: string): void;
}

export interface TranscriptionResult {
  text: string;
  confidence: number;  // 0.0 - 1.0
  language: string;
  durationMs: number;
}

export interface VoiceConfig {
  speed: number;       // 0.5 - 2.0
  pitch: number;       // 0.5 - 2.0
  voiceId: string;     // from available voices list
}

export interface ListeningState {
  sessionId: string;
  isActive: boolean;
  silenceDurationMs: number;
  retryCount: number;  // for low-confidence retries, max 3
}
