/**
 * Property 21: Authentication Access Control
 *
 * For any incoming request, access SHALL be granted if and only if valid
 * credentials (API key or verified voice biometric) are provided; failed
 * authentication SHALL produce an error response indicating invalid
 * credentials AND create a log entry recording the attempt.
 *
 * Feature: personal-ai-model, Property 21: Authentication Access Control
 *
 * **Validates: Requirements 8.5, 8.6**
 */

import { describe, it, expect, beforeEach } from 'vitest';
import * as fc from 'fast-check';
import { APIGatewayService } from '../../src/services/api-gateway.js';
import { IncomingRequest } from '../../src/interfaces/api-gateway.js';

describe('Property 21: Authentication Access Control', () => {
  let gateway: APIGatewayService;

  // Arbitrary for generating valid API key strings (non-empty alphanumeric)
  const arbApiKey = fc.string({ minLength: 8, maxLength: 64 }).filter((s) => s.length >= 8);

  // Arbitrary for generating source IPs
  const arbSourceIp = fc.tuple(
    fc.integer({ min: 1, max: 255 }),
    fc.integer({ min: 0, max: 255 }),
    fc.integer({ min: 0, max: 255 }),
    fc.integer({ min: 1, max: 254 })
  ).map(([a, b, c, d]) => `${a}.${b}.${c}.${d}`);

  // Arbitrary for generating user IDs
  const arbUserId = fc.string({ minLength: 3, maxLength: 32 }).filter((s) => s.trim().length >= 3);

  beforeEach(() => {
    gateway = new APIGatewayService();
  });

  it('access is granted if and only if a valid API key is provided', async () => {
    await fc.assert(
      fc.asyncProperty(
        arbUserId,
        arbApiKey,
        arbSourceIp,
        async (userId, validKey, sourceIp) => {
          // Register the valid key
          gateway = new APIGatewayService();
          gateway.registerApiKey(userId, validKey);

          const request: IncomingRequest = {
            apiKey: validKey,
            sourceIp,
            timestamp: new Date(),
          };

          const result = await gateway.authenticate(request);

          // Access SHALL be granted with valid credentials
          expect(result.authenticated).toBe(true);
          expect(result.userId).toBe(userId);
          expect(result.error).toBeUndefined();
        }
      ),
      { numRuns: 100 }
    );
  });

  it('access is denied when an invalid API key is provided', async () => {
    await fc.assert(
      fc.asyncProperty(
        arbUserId,
        arbApiKey,
        arbApiKey,
        arbSourceIp,
        async (userId, registeredKey, attemptedKey, sourceIp) => {
          // Only test when keys are actually different
          fc.pre(registeredKey !== attemptedKey);

          gateway = new APIGatewayService();
          gateway.registerApiKey(userId, registeredKey);

          const request: IncomingRequest = {
            apiKey: attemptedKey,
            sourceIp,
            timestamp: new Date(),
          };

          const result = await gateway.authenticate(request);

          // Access SHALL be denied with invalid credentials
          expect(result.authenticated).toBe(false);
          expect(result.userId).toBeNull();
          expect(result.error).toBeDefined();
          expect(result.error!.length).toBeGreaterThan(0);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('access is denied when no API key is provided', async () => {
    await fc.assert(
      fc.asyncProperty(
        arbUserId,
        arbApiKey,
        arbSourceIp,
        async (userId, registeredKey, sourceIp) => {
          gateway = new APIGatewayService();
          gateway.registerApiKey(userId, registeredKey);

          const request: IncomingRequest = {
            apiKey: undefined,
            sourceIp,
            timestamp: new Date(),
          };

          const result = await gateway.authenticate(request);

          // Access SHALL be denied when no credentials provided
          expect(result.authenticated).toBe(false);
          expect(result.userId).toBeNull();
          expect(result.error).toBeDefined();
          expect(result.error!.length).toBeGreaterThan(0);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('failed authentication produces an error response AND creates a log entry', async () => {
    await fc.assert(
      fc.asyncProperty(
        arbUserId,
        arbApiKey,
        arbApiKey,
        arbSourceIp,
        async (userId, registeredKey, invalidKey, sourceIp) => {
          fc.pre(registeredKey !== invalidKey);

          gateway = new APIGatewayService();
          gateway.registerApiKey(userId, registeredKey);

          const logBefore = gateway.getAccessLog();
          const logCountBefore = logBefore.length;

          const request: IncomingRequest = {
            apiKey: invalidKey,
            sourceIp,
            timestamp: new Date(),
          };

          const result = await gateway.authenticate(request);

          // Failed auth SHALL produce an error response
          expect(result.authenticated).toBe(false);
          expect(result.error).toBeDefined();
          expect(result.error!.length).toBeGreaterThan(0);

          // Failed auth SHALL create a log entry recording the attempt
          const logAfter = gateway.getAccessLog();
          expect(logAfter.length).toBe(logCountBefore + 1);

          const logEntry = logAfter[logAfter.length - 1];
          expect(logEntry.success).toBe(false);
          expect(logEntry.sourceIp).toBe(sourceIp);
          expect(logEntry.method).toBe('api_key');
          expect(logEntry.failureReason).toBeDefined();
        }
      ),
      { numRuns: 100 }
    );
  });

  it('successful authentication also creates a log entry', async () => {
    await fc.assert(
      fc.asyncProperty(
        arbUserId,
        arbApiKey,
        arbSourceIp,
        async (userId, validKey, sourceIp) => {
          gateway = new APIGatewayService();
          gateway.registerApiKey(userId, validKey);

          const logBefore = gateway.getAccessLog();
          const logCountBefore = logBefore.length;

          const request: IncomingRequest = {
            apiKey: validKey,
            sourceIp,
            timestamp: new Date(),
          };

          const result = await gateway.authenticate(request);

          expect(result.authenticated).toBe(true);

          // Successful auth SHALL also be logged
          const logAfter = gateway.getAccessLog();
          expect(logAfter.length).toBe(logCountBefore + 1);

          const logEntry = logAfter[logAfter.length - 1];
          expect(logEntry.success).toBe(true);
          expect(logEntry.sourceIp).toBe(sourceIp);
          expect(logEntry.method).toBe('api_key');
          expect(logEntry.userId).toBe(userId);
        }
      ),
      { numRuns: 100 }
    );
  });
});
