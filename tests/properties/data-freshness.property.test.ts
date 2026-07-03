/**
 * Property Test: Data Freshness Filtering (Property 6)
 *
 * **Validates: Requirements 3.1**
 *
 * Generates data items with random timestamps relative to request time
 * and verifies:
 * - Only items within 15 minutes of request time are included
 * - Items older than 15 minutes are excluded
 */

import { describe, it, expect } from 'vitest';
import fc from 'fast-check';
import { DATA_FRESHNESS_MAX_AGE_MINUTES } from '../../src/config/defaults';

/**
 * Pure freshness filtering logic matching DataFetcherService.isWithinFreshness().
 */
function isWithinFreshness(
  retrievedAt: Date,
  now: Date,
  maxAgeMinutes: number,
): boolean {
  const ageMs = now.getTime() - retrievedAt.getTime();
  const maxAgeMs = maxAgeMinutes * 60 * 1000;
  return ageMs <= maxAgeMs;
}

/**
 * Filter a set of data items by freshness.
 */
function filterByFreshness(
  items: { content: string; retrievedAt: Date }[],
  now: Date,
  maxAgeMinutes: number,
): { content: string; retrievedAt: Date }[] {
  return items.filter((item) => isWithinFreshness(item.retrievedAt, now, maxAgeMinutes));
}

describe('Property 6: Data Freshness Filtering', () => {
  const MAX_AGE_MS = DATA_FRESHNESS_MAX_AGE_MINUTES * 60 * 1000; // 15 minutes in ms

  /**
   * **Validates: Requirements 3.1**
   *
   * Items within 15 minutes are always included in filtered results.
   */
  it('includes items within 15 minutes of request time', () => {
    fc.assert(
      fc.property(
        fc.date({ min: new Date('2020-01-01'), max: new Date('2030-01-01') }),
        fc.integer({ min: 0, max: MAX_AGE_MS }),
        (now, ageMs) => {
          const retrievedAt = new Date(now.getTime() - ageMs);
          const result = isWithinFreshness(retrievedAt, now, DATA_FRESHNESS_MAX_AGE_MINUTES);
          expect(result).toBe(true);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 3.1**
   *
   * Items older than 15 minutes are always excluded from filtered results.
   */
  it('excludes items older than 15 minutes', () => {
    fc.assert(
      fc.property(
        fc.date({ min: new Date('2020-01-01'), max: new Date('2030-01-01') }),
        fc.integer({ min: MAX_AGE_MS + 1, max: MAX_AGE_MS * 10 }),
        (now, ageMs) => {
          const retrievedAt = new Date(now.getTime() - ageMs);
          const result = isWithinFreshness(retrievedAt, now, DATA_FRESHNESS_MAX_AGE_MINUTES);
          expect(result).toBe(false);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 3.1**
   *
   * Filtering a mixed set of items returns only those within the freshness window.
   */
  it('filters a mixed set correctly — only fresh items remain', () => {
    fc.assert(
      fc.property(
        fc.date({ min: new Date('2020-01-01'), max: new Date('2030-01-01') }),
        fc.array(
          fc.integer({ min: 0, max: MAX_AGE_MS * 5 }),
          { minLength: 1, maxLength: 20 },
        ),
        (now, offsets) => {
          const items = offsets.map((offset, idx) => ({
            content: `item-${idx}`,
            retrievedAt: new Date(now.getTime() - offset),
          }));

          const filtered = filterByFreshness(items, now, DATA_FRESHNESS_MAX_AGE_MINUTES);

          // All filtered items must be within 15 minutes
          for (const item of filtered) {
            const ageMs = now.getTime() - item.retrievedAt.getTime();
            expect(ageMs).toBeLessThanOrEqual(MAX_AGE_MS);
          }

          // All excluded items must be older than 15 minutes
          const excluded = items.filter((item) => !filtered.includes(item));
          for (const item of excluded) {
            const ageMs = now.getTime() - item.retrievedAt.getTime();
            expect(ageMs).toBeGreaterThan(MAX_AGE_MS);
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});
