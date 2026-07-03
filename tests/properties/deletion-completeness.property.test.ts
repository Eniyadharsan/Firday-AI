/**
 * Property Test: Deletion Completeness (Property 23)
 *
 * **Validates: Requirements 9.3**
 *
 * Generates sets of items to delete and verifies:
 * - Items are no longer queryable after deletion
 * - Confirmation includes the deleted items list and a timestamp
 */

import { describe, it, expect } from 'vitest';
import fc from 'fast-check';
import { SecurityService } from '../../src/services/security';

describe('Property 23: Deletion Completeness', () => {
  /**
   * **Validates: Requirements 9.3**
   *
   * After deletion, items are no longer queryable.
   */
  it('items are not queryable after deletion', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.uuid(),
        fc.array(fc.uuid(), { minLength: 1, maxLength: 20 }),
        async (userId, itemIds) => {
          const service = new SecurityService();

          // Register items
          service.registerUserData(userId, itemIds);

          // Verify items exist before deletion
          for (const id of itemIds) {
            expect(service.hasUserData(userId, id)).toBe(true);
          }

          // Delete items
          await service.deleteUserData(userId, itemIds);

          // Verify items no longer exist
          for (const id of itemIds) {
            expect(service.hasUserData(userId, id)).toBe(false);
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 9.3**
   *
   * Deletion confirmation includes the deleted items list and a timestamp.
   */
  it('confirmation includes deleted items list and timestamp', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.uuid(),
        fc.array(fc.uuid(), { minLength: 1, maxLength: 20 }),
        async (userId, itemIds) => {
          const service = new SecurityService();
          service.registerUserData(userId, itemIds);

          const beforeDeletion = new Date();
          const confirmation = await service.deleteUserData(userId, itemIds);

          // Confirmation must include the list of deleted items
          expect(confirmation.deletedItems).toEqual(expect.arrayContaining(itemIds));
          expect(confirmation.deletedItems.length).toBe(itemIds.length);

          // Confirmation must include a completion timestamp
          expect(confirmation.completionTimestamp).toBeInstanceOf(Date);
          expect(confirmation.completionTimestamp.getTime()).toBeGreaterThanOrEqual(
            beforeDeletion.getTime(),
          );

          // Success flag must be true
          expect(confirmation.success).toBe(true);
        },
      ),
      { numRuns: 100 },
    );
  });
});
