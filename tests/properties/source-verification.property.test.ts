/**
 * Property Test: Source Verification Labeling (Property 9)
 *
 * **Validates: Requirements 3.6**
 *
 * Generates items with varying corroborating source counts and verifies:
 * - Items are labeled "verified" if and only if corroborated by 2+ independent sources
 * - Items from a single source are labeled "unverified"
 */

import { describe, it, expect } from 'vitest';
import fc from 'fast-check';
import { DataFetcherService } from '../../src/services/data-fetcher';
import type { DataItem } from '../../src/interfaces/data-fetcher';

describe('Property 9: Source Verification Labeling', () => {
  /**
   * **Validates: Requirements 3.6**
   *
   * Items corroborated by 2+ independent sources are labeled verified.
   */
  it('labels items as verified when corroborated by 2+ independent sources', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 3, maxLength: 50 }),
        fc.array(
          fc.string({ minLength: 3, maxLength: 20 }),
          { minLength: 2, maxLength: 5 },
        ),
        (content, sources) => {
          // Ensure sources are unique (independent)
          const uniqueSources = [...new Set(sources)];
          if (uniqueSources.length < 2) return; // Skip if not enough unique sources

          const service = new DataFetcherService();

          // Create items with same content from different sources
          const items: DataItem[] = uniqueSources.map((source) => ({
            content,
            source,
            retrievedAt: new Date(),
            category: 'news' as const,
            verified: false,
          }));

          const verified = service.verifyItems(items);

          // All items with the same content from 2+ sources should be verified
          for (const item of verified) {
            expect(item.verified).toBe(true);
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 3.6**
   *
   * Items from a single source are labeled unverified.
   */
  it('labels items as unverified when from a single source only', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 3, maxLength: 50 }),
        fc.string({ minLength: 3, maxLength: 20 }),
        (content, source) => {
          const service = new DataFetcherService();

          const items: DataItem[] = [
            {
              content,
              source,
              retrievedAt: new Date(),
              category: 'news' as const,
              verified: false,
            },
          ];

          const verified = service.verifyItems(items);

          // Single source items should be unverified
          for (const item of verified) {
            expect(item.verified).toBe(false);
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 3.6**
   *
   * In a mixed set, only items with 2+ corroborating sources are verified.
   */
  it('correctly distinguishes verified vs unverified in mixed sets', () => {
    fc.assert(
      fc.property(
        fc.record({
          sharedContent: fc.string({ minLength: 3, maxLength: 30 }),
          uniqueContent: fc.string({ minLength: 3, maxLength: 30 }),
          source1: fc.string({ minLength: 3, maxLength: 15 }),
          source2: fc.string({ minLength: 3, maxLength: 15 }),
          source3: fc.string({ minLength: 3, maxLength: 15 }),
        }),
        ({ sharedContent, uniqueContent, source1, source2, source3 }) => {
          // Ensure all sources and contents are distinct
          if (source1 === source2 || sharedContent === uniqueContent) return;

          const service = new DataFetcherService();

          const items: DataItem[] = [
            // Corroborated item (shared content from 2 sources)
            { content: sharedContent, source: source1, retrievedAt: new Date(), category: 'news', verified: false },
            { content: sharedContent, source: source2, retrievedAt: new Date(), category: 'news', verified: false },
            // Unique item (single source)
            { content: uniqueContent, source: source3, retrievedAt: new Date(), category: 'web_search', verified: false },
          ];

          const verified = service.verifyItems(items);

          // Shared content items should be verified
          const sharedItems = verified.filter((i) => i.content === sharedContent);
          for (const item of sharedItems) {
            expect(item.verified).toBe(true);
          }

          // Unique item should remain unverified
          const uniqueItems = verified.filter((i) => i.content === uniqueContent);
          for (const item of uniqueItems) {
            expect(item.verified).toBe(false);
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});
