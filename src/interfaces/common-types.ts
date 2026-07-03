/**
 * Common types shared across interface definitions.
 */

/** Audio buffer for voice samples */
export type AudioBuffer = Buffer;

/** Audio stream for continuous audio input/output */
export type AudioStream = NodeJS.ReadableStream;

/** A message in conversation history */
export interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
}

/** Source label indicating where data came from */
export interface SourceLabel {
  documentId: string;
  source: string;
  basis: 'retrieved_evidence' | 'model_knowledge';
}

/** Citation referencing a supporting document */
export interface Citation {
  claimText: string;
  documentId: string;
  source: string;
}
