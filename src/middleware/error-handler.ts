/**
 * Centralized Error Handling Middleware
 *
 * Implements the error propagation strategy from the design document:
 * 1. Local Recovery First: Each component handles retries internally before escalating
 * 2. Graceful Degradation: Non-critical component failure → continue with reduced capability
 * 3. Fail-Safe Defaults: When uncertain, label responses "unverified" + disclaimers
 * 4. Session Preservation: Errors in one exchange do not corrupt session state
 *
 * Requirements: 8.1, all requirements integrated
 */

import { Request, Response, NextFunction } from 'express';

/**
 * Application-level error categories for structured error handling.
 */
export type ErrorCategory =
  | 'authentication'
  | 'session'
  | 'voice_stt'
  | 'voice_tts'
  | 'rag_retrieval'
  | 'data_fetch'
  | 'llm_generation'
  | 'confidence_scoring'
  | 'resource_limit'
  | 'validation'
  | 'internal';

/**
 * Structured application error with category for routing error responses.
 */
export class AppError extends Error {
  readonly category: ErrorCategory;
  readonly statusCode: number;
  readonly isOperational: boolean;
  readonly sessionId?: string;

  constructor(
    message: string,
    category: ErrorCategory,
    statusCode: number = 500,
    options?: { isOperational?: boolean; sessionId?: string }
  ) {
    super(message);
    this.name = 'AppError';
    this.category = category;
    this.statusCode = statusCode;
    this.isOperational = options?.isOperational ?? true;
    this.sessionId = options?.sessionId;
  }
}

/**
 * User-facing error messages mapped by category.
 * These messages are safe to expose without revealing internals.
 */
const USER_FACING_MESSAGES: Record<ErrorCategory, string> = {
  authentication: 'Authentication failed. Access denied.',
  session: 'Session error. Please try again or start a new session.',
  voice_stt: 'Speech recognition failed. Please try again.',
  voice_tts: 'Voice output unavailable, showing text response.',
  rag_retrieval: 'Document retrieval unavailable, response may not be grounded.',
  data_fetch: 'Real-time data unavailable. Response generated without current data.',
  llm_generation: "I'm having trouble generating a response, please try again.",
  confidence_scoring: 'Unable to verify response accuracy.',
  resource_limit: 'System resources are constrained. Please try again shortly.',
  validation: 'Invalid request. Please check your input.',
  internal: 'An internal error occurred. Please try again.',
};

/**
 * HTTP status codes by error category.
 */
const STATUS_CODES: Record<ErrorCategory, number> = {
  authentication: 401,
  session: 400,
  voice_stt: 500,
  voice_tts: 500,
  rag_retrieval: 503,
  data_fetch: 503,
  llm_generation: 503,
  confidence_scoring: 500,
  resource_limit: 503,
  validation: 400,
  internal: 500,
};

/**
 * Determine the error category from a generic error.
 */
function categorizeError(error: Error): ErrorCategory {
  if (error instanceof AppError) {
    return error.category;
  }

  const message = error.message.toLowerCase();

  if (message.includes('auth') || message.includes('credential') || message.includes('api key')) {
    return 'authentication';
  }
  if (message.includes('session')) {
    return 'session';
  }
  if (message.includes('transcri') || message.includes('stt') || message.includes('speech-to-text')) {
    return 'voice_stt';
  }
  if (message.includes('tts') || message.includes('synthe') || message.includes('text-to-speech')) {
    return 'voice_tts';
  }
  if (message.includes('rag') || message.includes('retriev') || message.includes('vector')) {
    return 'rag_retrieval';
  }
  if (message.includes('fetch') || message.includes('external') || message.includes('data source')) {
    return 'data_fetch';
  }
  if (message.includes('generat') || message.includes('llm') || message.includes('timeout')) {
    return 'llm_generation';
  }
  if (message.includes('confidence') || message.includes('scor')) {
    return 'confidence_scoring';
  }
  if (message.includes('resource') || message.includes('capacity') || message.includes('limit')) {
    return 'resource_limit';
  }
  if (message.includes('valid') || message.includes('required') || message.includes('missing')) {
    return 'validation';
  }

  return 'internal';
}

/**
 * Centralized error handling middleware for Express.
 *
 * - Categorizes errors and returns appropriate HTTP status + user-facing message
 * - Logs internal details for debugging without exposing them to users
 * - Preserves session state by not mutating session on error
 * - Supports structured AppError or generic Error objects
 */
export function errorHandler(
  err: Error,
  _req: Request,
  res: Response,
  _next: NextFunction
): void {
  const category = categorizeError(err);
  const statusCode = err instanceof AppError ? err.statusCode : STATUS_CODES[category];
  const userMessage = USER_FACING_MESSAGES[category];

  // Log the full error internally for debugging
  console.error(`[ErrorHandler] [${category}] ${err.message}`, {
    stack: err.stack,
    sessionId: err instanceof AppError ? err.sessionId : undefined,
  });

  res.status(statusCode).json({
    success: false,
    error: userMessage,
    category,
    // Include session ID in response so client can continue session after error
    ...(err instanceof AppError && err.sessionId ? { sessionId: err.sessionId } : {}),
  });
}

/**
 * Not-found handler for unmatched routes.
 */
export function notFoundHandler(req: Request, res: Response): void {
  res.status(404).json({
    success: false,
    error: `Route not found: ${req.method} ${req.path}`,
  });
}

/**
 * Wrap an async route handler so that errors are properly forwarded to the
 * error handling middleware, preserving session state.
 */
export function asyncHandler(
  fn: (req: Request, res: Response, next: NextFunction) => Promise<void>
): (req: Request, res: Response, next: NextFunction) => void {
  return (req: Request, res: Response, next: NextFunction) => {
    fn(req, res, next).catch(next);
  };
}
