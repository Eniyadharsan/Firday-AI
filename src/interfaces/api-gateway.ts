/**
 * API Gateway / Authentication Layer interfaces.
 *
 * Responsibility: Entry point for all requests; handles authentication,
 * rate limiting, and TLS termination.
 */

import { AudioBuffer } from './common-types.js';

export interface APIGateway {
  /** Authenticate incoming request */
  authenticate(request: IncomingRequest): Promise<AuthResult>;
  /** Track failed attempts for lockout */
  recordFailedAttempt(source: string): void;
  /** Check if source is blocked */
  isBlocked(source: string): boolean;
}

export interface AuthResult {
  authenticated: boolean;
  userId: string | null;
  method: 'api_key' | 'voice_biometric';
  error?: string;
}

export interface IncomingRequest {
  apiKey?: string;
  voiceSample?: AudioBuffer;
  sourceIp: string;
  timestamp: Date;
}
