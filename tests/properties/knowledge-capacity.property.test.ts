/**
 * Property Test: Knowledge Store Capacity Enforcement (Property 18)
 *
 * **Validates: Requirements 7.3**
 *
 * Generates sequences of store/delete operations and verifies:
 * - Items accepted while count < 500
 * - Items rejected at 500
 * - Deletion reduces count by exactly 1
 */

import { describe, it, expect } from 'vitest';
import fc from 'fast-check';
import { KnowledgeStoreService } from '../../src/services/knowledge-store';
import { KNOWLEDGE_STORE_MAX_ITEMS } from '../../src/config/defaults';
import type { KnowledgeItem } from '../../src/interfaces/knowledge-store';

/** Create a valid KnowledgeItem for testing */
function createKnowledgeItem(index: number): KnowledgeItem {
  return {
    id: '', // Will be assigned by the store
    type: 'fact',
    content: `knowledge-item-${index}`,
    createdAt: new Date(),
    metadata: {},
  };
}

describe('Property 18: Knowledge Store Capacity Enforcement', () => {
  /**
   * **Validates: Requirements 7.3**
   *
   * Items are accepted while the total count is below 500.
   */
  it('accepts items while count < 500', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 1, max: 50 }),
        async (itemCount) => {
          const store = new KnowledgeStoreService();
          const userId = 'test-user';

          for (let i = 0; i < itemCount; i++) {
            const itemId = await store.storeItem(userId, createKnowledgeItem(i));
            expect(itemId).toBeDefined();
            expect(typeof itemId).toBe('string');
          }

          const count = await store.getItemCount(userId);
          expect(count).toBe(itemCount);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 7.3**
   *
   * Items are rejected when count reaches 500.
   */
  it('rejects items at capacity (500)', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 1, max: 5 }),
        async (extraAttempts) => {
          const store = new KnowledgeStoreService();
          const userId = 'test-user';

          // Fill to capacity
          for (let i = 0; i < KNOWLEDGE_STORE_MAX_ITEMS; i++) {
            await store.storeItem(userId, createKnowledgeItem(i));
          }

          const countAtCapacity = await store.getItemCount(userId);
          expect(countAtCapacity).toBe(KNOWLEDGE_STORE_MAX_ITEMS);

          // Attempt to add beyond capacity
          for (let i = 0; i < extraAttempts; i++) {
            await expect(
              store.storeItem(userId, createKnowledgeItem(KNOWLEDGE_STORE_MAX_ITEMS + i)),
            ).rejects.toThrow(/capacity exceeded/i);
          }

          // Count should remain at max
          const countAfter = await store.getItemCount(userId);
          expect(countAfter).toBe(KNOWLEDGE_STORE_MAX_ITEMS);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 7.3**
   *
   * Deletion reduces count by exactly 1.
   */
  it('deletion reduces count by exactly 1', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 2, max: 20 }),
        fc.integer({ min: 1, max: 5 }),
        async (initialCount, deletions) => {
          const store = new KnowledgeStoreService();
          const userId = 'test-user';
          const itemIds: string[] = [];

          // Add items
          for (let i = 0; i < initialCount; i++) {
            const itemId = await store.storeItem(userId, createKnowledgeItem(i));
            itemIds.push(itemId);
          }

          const actualDeletions = Math.min(deletions, initialCount);

          // Delete items and verify count decreases by 1 each time
          for (let i = 0; i < actualDeletions; i++) {
            const countBefore = await store.getItemCount(userId);
            await store.removeItem(userId, itemIds[i]);
            const countAfter = await store.getItemCount(userId);
            expect(countAfter).toBe(countBefore - 1);
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});
