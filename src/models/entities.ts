/**
 * Core data model entities for the personal AI assistant system.
 */

import { VoiceConfig } from '../interfaces/voice-interface.js';
import { Exchange } from '../interfaces/session-manager.js';

/** User profile and configuration */
export interface UserProfile {
  id: string;
  voiceConfig: VoiceConfig;
  confidenceThreshold: number;    // default 0.7
  ragTopK: number;                // default 5
  ragRelevanceThreshold: number;  // default 0.7
  dataRetentionDays: number;
  trainingOptIn: boolean;         // default false
  createdAt: Date;
  updatedAt: Date;
}

/** Conversation log entry (stored encrypted) */
export interface ConversationLog {
  id: string;
  sessionId: string;
  userId: string;
  exchanges: Exchange[];
  startedAt: Date;
  endedAt: Date;
  metadata: {
    totalExchanges: number;
    averageConfidence: number;
    sourcesUsed: string[];
  };
}

/** Authentication access log */
export interface AccessLogEntry {
  id: string;
  timestamp: Date;
  sourceIp: string;
  method: 'api_key' | 'voice_biometric';
  success: boolean;
  userId?: string;
  failureReason?: string;
}

/** Document stored in Knowledge Store */
export interface StoredDocument {
  id: string;
  userId: string;
  originalFormat: 'text' | 'pdf' | 'html';
  sizeMb: number;
  chunks: DocumentChunk[];
  indexedAt: Date;
  metadata: Record<string, string>;
}

export interface DocumentChunk {
  id: string;
  documentId: string;
  content: string;
  embedding: number[];      // vector representation
  chunkIndex: number;
  tokenCount: number;
}

/** Fine-tuning model version record */
export interface ModelVersion {
  id: string;
  baseModel: string;        // e.g., "mistral-7b-instruct-v0.2"
  version: string;
  trainingExamples: number;
  evaluationScore: number;  // on held-out test set
  createdAt: Date;
  status: 'active' | 'archived' | 'rolled_back';
  loraWeightsPath: string;
}

/** Multi-step task execution record */
export interface TaskExecution {
  id: string;
  sessionId: string;
  originalQuery: string;
  subtasks: SubTaskRecord[];
  status: 'in_progress' | 'completed' | 'partially_failed';
  startedAt: Date;
  completedAt?: Date;
}

export interface SubTaskRecord {
  id: number;
  description: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
  result?: string;
  error?: string;
  startedAt?: Date;
  completedAt?: Date;
}

/** Alert configuration */
export interface AlertConfig {
  cpuThreshold: number;     // default 80%
  memoryThreshold: number;  // default 80%
  gpuThreshold: number;     // default 80%
  diskThreshold: number;    // default 80%
  notificationChannel: 'email' | 'webhook' | 'sms';
  notificationTarget: string;
}
