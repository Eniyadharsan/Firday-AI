/**
 * Property Test: Data Access Authorization (Property 27)
 *
 * **Validates: Requirements 9.7**
 *
 * Generates access requests from owner vs non-owner sessions and verifies:
 * - Access is permitted if and only if the session belongs to the data owner
 * - Access is denied for non-owner sessions
 */

import { describe, it, expect } from 'vitest';
import fc from 'fast-check';
import { SecurityService } from '../../src/services/security';

describe('Property 27: Data Access Authorization', () => {
  /**
   * **Validates: Requirements 9.7**
   *
   * Access is permitted when the session user matches the data owner.
   */
  it('access permitted when session belongs to data owner', () => {
    fc.assert(
      fc.property(
        fc.uuid(),
        (userId) => {
          const service = new SecurityService();

          // Owner accessing their own data
          const hasAccess = service.checkDataAccess(userId, userId);
          expect(hasAccess).toBe(true);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 9.7**
   *
   * Access is denied when the session user does NOT match the data owner.
   */
  it('access denied when session does not belong to data owner', () => {
    fc.assert(
      fc.property(
        fc.uuid(),
        fc.uuid(),
        (ownerId, requesterId) => {
          // Only test when IDs are different
          fc.pre(ownerId !== requesterId);

          const service = new SecurityService();

          const hasAccess = service.checkDataAccess(ownerId, requesterId);
          expect(hasAccess).toBe(false);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 9.7**
   *
   * Access is denied for empty/missing session user IDs.
   */
  it('access denied for empty or missing session identifiers', () => {
    fc.assert(
      fc.property(
        fc.uuid(),
        fc.constantFrom('', undefined as unknown as string),
        (ownerId, emptySession) => {
          const service = new SecurityService();

          const hasAccess = service.checkDataAccess(ownerId, emptySession);
          expect(hasAccess).toBe(false);
        },
      ),
      { numRuns: 100 },
    );
  });
});
