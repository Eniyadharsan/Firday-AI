/**
 * Session Manager interfaces.
 *
 * Responsibility: Maintain conversation history; handle session lifecycle;
 * persist user preferences.
 */

export interface SessionManager {
  /** Create a new session */
  createSession(userId: string): Promise<Session>;
  /** Get existing session */
  getSession(sessionId: string): Promise<Session | null>;
  /** Update session with new exchange */
  addExchange(sessionId: string, exchange: Exchange): Promise<void>;
  /** End a session */
  endSession(sessionId: string): Promise<void>;
}

export interface Session {
  id: string;
  userId: string;
  startedAt: Date;
  lastActivityAt: Date;
  exchanges: Exchange[];    // max 50 retained
  isActive: boolean;
}

export interface Exchange {
  userMessage: string;
  assistantResponse: string;
  timestamp: Date;
  metadata: ExchangeMetadata;
}

export interface ExchangeMetadata {
  confidenceScore: number;
  sourcesUsed: string[];
  responseTimeMs: number;
}
