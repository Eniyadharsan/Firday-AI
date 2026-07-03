/**
 * Property Test: Training Opt-In Enforcement (Property 25)
 *
 * **Validates: Requirements 9.5**
 *
 * Generates training requests with opt-in true/false and verifies:
 * - Training proceeds only when opt-in is true
 * - Training is rejected when opt-in is false
 */

import { describe, it, expect } from 'vitest';
import fc from 'fast-check';
import { SecurityService } from '../../src/services/security';
import type { UserProfile } from '../../src/models/entities';

/** Create a user profile with a specific opt-in setting */
function createUserProfile(userId: string, trainingOptIn: boolean): UserProfile {
  return {
    id: userId,
    voiceConfig: { speed: 1.0, pitch: 1.0, voiceId: 'default' },
    confidenceThreshold: 0.7,
    ragTopK: 5,
    ragRelevanceThreshold: 0.7,
    dataRetentionDays: 90,
    trainingOptIn,
    createdAt: new Date(),
    updatedAt: new Date(),
  };
}

describe('Property 25: Training Opt-In Enforcement', () => {
  /**
   * **Validates: Requirements 9.5**
   *
   * Training proceeds when opt-in is true.
   */
  it('training allowed when opt-in is true', () => {
    fc.assert(
      fc.property(
        fc.uuid(),
        (userId) => {
          const service = new SecurityService();
          const profile = createUserProfile(userId, true);
          service.registerUserProfile(profile);

          const isAllowed = service.isTrainingOptInEnabled(userId);
          expect(isAllowed).toBe(true);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 9.5**
   *
   * Training is rejected when opt-in is false.
   */
  it('training rejected when opt-in is false', () => {
    fc.assert(
      fc.property(
        fc.uuid(),
        (userId) => {
          const service = new SecurityService();
          const profile = createUserProfile(userId, false);
          service.registerUserProfile(profile);

          const isAllowed = service.isTrainingOptInEnabled(userId);
          expect(isAllowed).toBe(false);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 9.5**
   *
   * Unregistered users default to opt-in false (no training allowed).
   */
  it('unregistered users default to training rejected', () => {
    fc.assert(
      fc.property(
        fc.uuid(),
        (userId) => {
          const service = new SecurityService();
          // Do not register the user
          const isAllowed = service.isTrainingOptInEnabled(userId);
          expect(isAllowed).toBe(false);
        },
      ),
      { numRuns: 100 },
    );
  });
});
