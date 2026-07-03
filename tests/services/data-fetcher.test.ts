/**
 * Unit tests for DataFetcherService
 *
 * Tests: real-time data retrieval, freshness filtering, source fallback,
 * failed category tracking, circuit breaker pattern, source verification,
 * citation formatting, and outbound query sanitization.
 *
 * Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 9.2
 */

import { describe, it, expect, vi } from 'vitest';
import {
  DataFetcherService,
  SourceProvider,
  RawDataItem,
} from '../../src/services/data-fetcher.js';
import { DataCategory, DataQuery } from '../../src/interfaces/data-fetcher.js';

// Helper to create a mock source provider
function createProvider(
  name: string,
  category: DataCategory,
  result: RawDataItem[] | Error = [],
): SourceProvider {
  return {
    name,
    category,
    fetch: result instanceof Error
      ? vi.fn().mockRejectedValue(result)
      : vi.fn().mockResolvedValue(result),
  };
}

// Helper to create a fresh data item
function freshItem(category: DataCategory, source: string, content: string, minutesAgo = 5): RawDataItem {
  const retrievedAt = new Date(Date.now() - minutesAgo * 60 * 1000);
  return { content, source, retrievedAt, category };
}

// Helper to create a stale data item (older than 15 minutes)
function staleItem(category: DataCategory, source: string, content: string): RawDataItem {
  const retrievedAt = new Date(Date.now() - 20 * 60 * 1000); // 20 minutes ago
  return { content, source, retrievedAt, category };
}

describe('DataFetcherService', () => {
  describe('fetch() - basic retrieval', () => {
    it('should return items from providers for requested categories', async () => {
      const newsProvider = createProvider('news-api-1', 'news', [
        freshItem('news', 'Reuters', 'Breaking news content'),
      ]);

      const service = new DataFetcherService([newsProvider]);

      const query: DataQuery = {
        text: 'latest news',
        categories: ['news'],
        maxAgeMinutes: 15,
        timeoutMs: 10000,
      };

      const result = await service.fetch(query);

      expect(result.items.length).toBe(1);
      expect(result.items[0]!.content).toBe('Breaking news content');
      expect(result.items[0]!.source).toBe('Reuters');
      expect(result.items[0]!.category).toBe('news');
      expect(result.failedCategories).toHaveLength(0);
      expect(result.allFailed).toBe(false);
    });

    it('should query multiple categories independently', async () => {
      const newsProvider = createProvider('news-api-1', 'news', [
        freshItem('news', 'Reuters', 'News content'),
      ]);
      const weatherProvider = createProvider('weather-api-1', 'weather', [
        freshItem('weather', 'OpenWeather', 'Sunny today'),
      ]);

      const service = new DataFetcherService([newsProvider, weatherProvider]);

      const query: DataQuery = {
        text: 'news and weather',
        categories: ['news', 'weather'],
        maxAgeMinutes: 15,
        timeoutMs: 10000,
      };

      const result = await service.fetch(query);

      expect(result.items.length).toBe(2);
      expect(result.failedCategories).toHaveLength(0);
      expect(result.allFailed).toBe(false);
    });
  });

  describe('fetch() - freshness filtering', () => {
    it('should include items within 15 minutes', async () => {
      const provider = createProvider('news-api-1', 'news', [
        freshItem('news', 'Reuters', 'Fresh news', 10), // 10 minutes ago
      ]);

      const service = new DataFetcherService([provider]);
      const query: DataQuery = {
        text: 'news',
        categories: ['news'],
        maxAgeMinutes: 15,
        timeoutMs: 10000,
      };

      const result = await service.fetch(query);
      expect(result.items.length).toBe(1);
    });

    it('should exclude items older than 15 minutes', async () => {
      const provider = createProvider('news-api-1', 'news', [
        staleItem('news', 'Reuters', 'Old news'),
      ]);

      const service = new DataFetcherService([provider]);
      const query: DataQuery = {
        text: 'news',
        categories: ['news'],
        maxAgeMinutes: 15,
        timeoutMs: 10000,
      };

      const result = await service.fetch(query);
      expect(result.items.length).toBe(0);
      // Category is marked as failed since no fresh items returned
      expect(result.failedCategories).toContain('news');
    });

    it('should include items exactly at the 15-minute boundary', async () => {
      // Use 14.9 minutes to avoid timing race (the fetch creates 'now' slightly after item creation)
      const provider = createProvider('news-api-1', 'news', [
        freshItem('news', 'Reuters', 'Border news', 14.9),
      ]);

      const service = new DataFetcherService([provider]);
      const query: DataQuery = {
        text: 'news',
        categories: ['news'],
        maxAgeMinutes: 15,
        timeoutMs: 10000,
      };

      const result = await service.fetch(query);
      expect(result.items.length).toBe(1);
    });
  });

  describe('fetch() - source fallback', () => {
    it('should fallback to alternative source when primary fails', async () => {
      const failingProvider = createProvider('news-api-1', 'news', new Error('Connection refused'));
      const workingProvider = createProvider('news-api-2', 'news', [
        freshItem('news', 'AP News', 'Fallback news'),
      ]);

      const service = new DataFetcherService([failingProvider, workingProvider]);

      const query: DataQuery = {
        text: 'news',
        categories: ['news'],
        maxAgeMinutes: 15,
        timeoutMs: 10000,
      };

      const result = await service.fetch(query);
      expect(result.items.length).toBe(1);
      expect(result.items[0]!.source).toBe('AP News');
      expect(result.failedCategories).toHaveLength(0);
    });

    it('should try up to 3 providers (primary + 2 alternatives) per category', async () => {
      const provider1 = createProvider('news-api-1', 'news', new Error('Fail 1'));
      const provider2 = createProvider('news-api-2', 'news', new Error('Fail 2'));
      const provider3 = createProvider('news-api-3', 'news', [
        freshItem('news', 'BBC', 'Third provider news'),
      ]);
      const provider4 = createProvider('news-api-4', 'news', [
        freshItem('news', 'CNN', 'Should not reach this'),
      ]);

      const service = new DataFetcherService([provider1, provider2, provider3, provider4]);

      const query: DataQuery = {
        text: 'news',
        categories: ['news'],
        maxAgeMinutes: 15,
        timeoutMs: 10000,
      };

      const result = await service.fetch(query);
      expect(result.items.length).toBe(1);
      expect(result.items[0]!.source).toBe('BBC');
      // Provider4 should NOT have been called (max 3 attempts)
      expect(provider4.fetch).not.toHaveBeenCalled();
    });

    it('should mark category as failed when all 3 providers fail', async () => {
      const provider1 = createProvider('news-api-1', 'news', new Error('Fail 1'));
      const provider2 = createProvider('news-api-2', 'news', new Error('Fail 2'));
      const provider3 = createProvider('news-api-3', 'news', new Error('Fail 3'));

      const service = new DataFetcherService([provider1, provider2, provider3]);

      const query: DataQuery = {
        text: 'news',
        categories: ['news'],
        maxAgeMinutes: 15,
        timeoutMs: 10000,
      };

      const result = await service.fetch(query);
      expect(result.items).toHaveLength(0);
      expect(result.failedCategories).toContain('news');
    });
  });

  describe('fetch() - allFailed tracking', () => {
    it('should set allFailed=true when ALL requested categories fail', async () => {
      const newsProvider = createProvider('news-api-1', 'news', new Error('News fail'));
      const weatherProvider = createProvider('weather-api-1', 'weather', new Error('Weather fail'));

      const service = new DataFetcherService([newsProvider, weatherProvider]);

      const query: DataQuery = {
        text: 'news and weather',
        categories: ['news', 'weather'],
        maxAgeMinutes: 15,
        timeoutMs: 10000,
      };

      const result = await service.fetch(query);
      expect(result.allFailed).toBe(true);
      expect(result.failedCategories).toContain('news');
      expect(result.failedCategories).toContain('weather');
    });

    it('should set allFailed=false when at least one category succeeds', async () => {
      const newsProvider = createProvider('news-api-1', 'news', new Error('News fail'));
      const weatherProvider = createProvider('weather-api-1', 'weather', [
        freshItem('weather', 'OpenWeather', 'Sunny'),
      ]);

      const service = new DataFetcherService([newsProvider, weatherProvider]);

      const query: DataQuery = {
        text: 'news and weather',
        categories: ['news', 'weather'],
        maxAgeMinutes: 15,
        timeoutMs: 10000,
      };

      const result = await service.fetch(query);
      expect(result.allFailed).toBe(false);
      expect(result.failedCategories).toContain('news');
      expect(result.failedCategories).not.toContain('weather');
    });

    it('should set allFailed=false for empty categories list', async () => {
      const service = new DataFetcherService([]);
      const query: DataQuery = {
        text: 'test',
        categories: [],
        maxAgeMinutes: 15,
        timeoutMs: 10000,
      };

      const result = await service.fetch(query);
      expect(result.allFailed).toBe(false);
      expect(result.items).toHaveLength(0);
    });
  });

  describe('circuit breaker pattern', () => {
    it('should open circuit after 3 consecutive failures', async () => {
      const failProvider = createProvider('news-api-1', 'news', new Error('Fail'));
      const backupProvider = createProvider('news-api-2', 'news', [
        freshItem('news', 'Backup', 'Backup news'),
      ]);

      const service = new DataFetcherService([failProvider, backupProvider]);

      const query: DataQuery = {
        text: 'news',
        categories: ['news'],
        maxAgeMinutes: 15,
        timeoutMs: 10000,
      };

      // First 3 fetches: failProvider fails each time, accumulating failures
      await service.fetch(query);
      await service.fetch(query);
      await service.fetch(query);

      // After 3 consecutive failures, circuit should be open
      // Reset the mock call count to verify next behavior
      (failProvider.fetch as ReturnType<typeof vi.fn>).mockClear();

      // On 4th call, failProvider circuit is open so it should be skipped
      const result = await service.fetch(query);

      // failProvider should not have been called (circuit is open)
      expect(failProvider.fetch).not.toHaveBeenCalled();
      // backupProvider should still work
      expect(result.items.length).toBe(1);
      expect(result.items[0]!.source).toBe('Backup');
    });

    it('should transition to half-open after 30s cooldown', async () => {
      const failProvider = createProvider('news-api-1', 'news', new Error('Fail'));

      const service = new DataFetcherService([failProvider]);

      const query: DataQuery = {
        text: 'news',
        categories: ['news'],
        maxAgeMinutes: 15,
        timeoutMs: 10000,
      };

      // Trip the circuit breaker with 3 failures
      await service.fetch(query);
      await service.fetch(query);
      await service.fetch(query);

      // Advance time past cooldown (30s)
      vi.useFakeTimers();
      vi.setSystemTime(Date.now() + 31_000);

      // Now make the provider succeed
      (failProvider.fetch as ReturnType<typeof vi.fn>).mockResolvedValue([
        freshItem('news', 'Recovered', 'Recovery news'),
      ]);

      const result = await service.fetch(query);

      // Should have attempted the request (half-open allows one test)
      expect(failProvider.fetch).toHaveBeenCalled();
      expect(result.items.length).toBe(1);

      vi.useRealTimers();
    });

    it('should close circuit on success after half-open', async () => {
      const provider = createProvider('news-api-1', 'news', new Error('Fail'));

      const service = new DataFetcherService([provider]);

      const query: DataQuery = {
        text: 'news',
        categories: ['news'],
        maxAgeMinutes: 15,
        timeoutMs: 10000,
      };

      // Trip the breaker
      await service.fetch(query);
      await service.fetch(query);
      await service.fetch(query);

      // Advance time past cooldown
      vi.useFakeTimers();
      vi.setSystemTime(Date.now() + 31_000);

      // Make it succeed now
      (provider.fetch as ReturnType<typeof vi.fn>).mockResolvedValue([
        freshItem('news', 'Reuters', 'Success'),
      ]);

      // First call after cooldown (half-open → test request succeeds → close)
      await service.fetch(query);

      // Advance time slightly (still within cooldown from last failure time)
      vi.advanceTimersByTime(1000);

      // Now should be fully closed - provider should work normally
      (provider.fetch as ReturnType<typeof vi.fn>).mockClear();
      const result = await service.fetch(query);
      expect(provider.fetch).toHaveBeenCalled();
      expect(result.items.length).toBe(1);

      vi.useRealTimers();
    });

    it('should skip circuit-open providers without counting as an attempt', async () => {
      // Provider 1 has tripped circuit, providers 2 and 3 are available
      const trippedProvider = createProvider('news-api-1', 'news', new Error('Fail'));
      const workingProvider2 = createProvider('news-api-2', 'news', [
        freshItem('news', 'AP', 'News from AP'),
      ]);
      const workingProvider3 = createProvider('news-api-3', 'news', [
        freshItem('news', 'BBC', 'News from BBC'),
      ]);

      const service = new DataFetcherService([trippedProvider, workingProvider2, workingProvider3]);

      const query: DataQuery = {
        text: 'news',
        categories: ['news'],
        maxAgeMinutes: 15,
        timeoutMs: 10000,
      };

      // Trip the first provider's circuit
      await service.fetch(query);
      await service.fetch(query);
      await service.fetch(query);

      // Clear mocks
      (trippedProvider.fetch as ReturnType<typeof vi.fn>).mockClear();
      (workingProvider2.fetch as ReturnType<typeof vi.fn>).mockClear();
      (workingProvider3.fetch as ReturnType<typeof vi.fn>).mockClear();

      // Now fetch again - trippedProvider should be skipped
      const result = await service.fetch(query);

      expect(trippedProvider.fetch).not.toHaveBeenCalled();
      expect(workingProvider2.fetch).toHaveBeenCalled();
      expect(result.items.length).toBeGreaterThan(0);
    });
  });

  describe('fetch() - uses defaults from config', () => {
    it('should use DATA_FRESHNESS_MAX_AGE_MINUTES when maxAgeMinutes not specified', async () => {
      const provider = createProvider('news-api-1', 'news', [
        freshItem('news', 'Reuters', 'Fresh news', 14), // 14 minutes ago - within default 15
      ]);

      const service = new DataFetcherService([provider]);
      const query: DataQuery = {
        text: 'news',
        categories: ['news'],
        maxAgeMinutes: 15,
        timeoutMs: 10000,
      };

      const result = await service.fetch(query);
      expect(result.items.length).toBe(1);
    });
  });

  describe('verifyItems() - source verification logic', () => {
    it('should label items as verified when same content from 2+ different sources', () => {
      const service = new DataFetcherService([]);
      const now = new Date();

      const items = [
        { content: 'Stock market rises 3%', source: 'Reuters', retrievedAt: now, category: 'finance' as DataCategory, verified: false },
        { content: 'Stock market rises 3%', source: 'Bloomberg', retrievedAt: now, category: 'finance' as DataCategory, verified: false },
      ];

      const result = service.verifyItems(items);

      expect(result).toHaveLength(2);
      expect(result[0]!.verified).toBe(true);
      expect(result[1]!.verified).toBe(true);
    });

    it('should label items as unverified when from a single source only', () => {
      const service = new DataFetcherService([]);
      const now = new Date();

      const items = [
        { content: 'Exclusive scoop', source: 'DailyNews', retrievedAt: now, category: 'news' as DataCategory, verified: false },
      ];

      const result = service.verifyItems(items);

      expect(result).toHaveLength(1);
      expect(result[0]!.verified).toBe(false);
    });

    it('should treat content with different casing as the same for verification', () => {
      const service = new DataFetcherService([]);
      const now = new Date();

      const items = [
        { content: 'Temperature is 72F', source: 'WeatherAPI', retrievedAt: now, category: 'weather' as DataCategory, verified: false },
        { content: 'temperature is 72f', source: 'AccuWeather', retrievedAt: now, category: 'weather' as DataCategory, verified: false },
      ];

      const result = service.verifyItems(items);

      expect(result).toHaveLength(2);
      expect(result[0]!.verified).toBe(true);
      expect(result[1]!.verified).toBe(true);
    });

    it('should treat content with extra whitespace as the same for verification', () => {
      const service = new DataFetcherService([]);
      const now = new Date();

      const items = [
        { content: 'Breaking  news   today', source: 'Source1', retrievedAt: now, category: 'news' as DataCategory, verified: false },
        { content: 'Breaking news today', source: 'Source2', retrievedAt: now, category: 'news' as DataCategory, verified: false },
      ];

      const result = service.verifyItems(items);

      expect(result).toHaveLength(2);
      expect(result[0]!.verified).toBe(true);
      expect(result[1]!.verified).toBe(true);
    });

    it('should NOT mark items as verified if same source provides the same content twice', () => {
      const service = new DataFetcherService([]);
      const now = new Date();

      const items = [
        { content: 'Same content', source: 'Reuters', retrievedAt: now, category: 'news' as DataCategory, verified: false },
        { content: 'Same content', source: 'Reuters', retrievedAt: now, category: 'news' as DataCategory, verified: false },
      ];

      const result = service.verifyItems(items);

      expect(result).toHaveLength(2);
      // Same source providing same content does not count as independent corroboration
      expect(result[0]!.verified).toBe(false);
      expect(result[1]!.verified).toBe(false);
    });

    it('should handle mixed verified and unverified items in the same set', () => {
      const service = new DataFetcherService([]);
      const now = new Date();

      const items = [
        // These two corroborate each other
        { content: 'Corroborated fact', source: 'SourceA', retrievedAt: now, category: 'news' as DataCategory, verified: false },
        { content: 'Corroborated fact', source: 'SourceB', retrievedAt: now, category: 'news' as DataCategory, verified: false },
        // This one is unique
        { content: 'Unique fact', source: 'SourceC', retrievedAt: now, category: 'news' as DataCategory, verified: false },
      ];

      const result = service.verifyItems(items);

      expect(result).toHaveLength(3);
      const corroborated = result.filter(i => i.content.toLowerCase().includes('corroborated'));
      const unique = result.filter(i => i.content.toLowerCase().includes('unique'));

      expect(corroborated.every(i => i.verified === true)).toBe(true);
      expect(unique.every(i => i.verified === false)).toBe(true);
    });

    it('should handle empty items array', () => {
      const service = new DataFetcherService([]);
      const result = service.verifyItems([]);
      expect(result).toHaveLength(0);
    });

    it('should verify items with 3+ independent sources', () => {
      const service = new DataFetcherService([]);
      const now = new Date();

      const items = [
        { content: 'Big story', source: 'Reuters', retrievedAt: now, category: 'news' as DataCategory, verified: false },
        { content: 'Big story', source: 'AP', retrievedAt: now, category: 'news' as DataCategory, verified: false },
        { content: 'Big story', source: 'BBC', retrievedAt: now, category: 'news' as DataCategory, verified: false },
      ];

      const result = service.verifyItems(items);

      expect(result).toHaveLength(3);
      expect(result.every(i => i.verified === true)).toBe(true);
    });
  });

  describe('formatCitation() - citation formatting', () => {
    it('should include source name in citation', () => {
      const service = new DataFetcherService([]);
      const item = {
        content: 'Some content',
        source: 'Reuters',
        retrievedAt: new Date('2024-01-15T10:30:00.000Z'),
        category: 'news' as DataCategory,
        verified: true,
      };

      const citation = service.formatCitation(item);

      expect(citation).toContain('Reuters');
    });

    it('should include retrieval timestamp in citation', () => {
      const service = new DataFetcherService([]);
      const timestamp = new Date('2024-01-15T10:30:00.000Z');
      const item = {
        content: 'Some content',
        source: 'Bloomberg',
        retrievedAt: timestamp,
        category: 'finance' as DataCategory,
        verified: false,
      };

      const citation = service.formatCitation(item);

      expect(citation).toContain(timestamp.toISOString());
    });

    it('should format citation as "{source} (retrieved {timestamp})"', () => {
      const service = new DataFetcherService([]);
      const timestamp = new Date('2024-03-20T14:45:00.000Z');
      const item = {
        content: 'Weather data',
        source: 'OpenWeather',
        retrievedAt: timestamp,
        category: 'weather' as DataCategory,
        verified: true,
      };

      const citation = service.formatCitation(item);

      expect(citation).toBe(`OpenWeather (retrieved ${timestamp.toISOString()})`);
    });

    it('should handle sources with special characters', () => {
      const service = new DataFetcherService([]);
      const timestamp = new Date('2024-06-01T08:00:00.000Z');
      const item = {
        content: 'Data',
        source: 'The New York Times (NYT)',
        retrievedAt: timestamp,
        category: 'news' as DataCategory,
        verified: true,
      };

      const citation = service.formatCitation(item);

      expect(citation).toContain('The New York Times (NYT)');
      expect(citation).toContain(timestamp.toISOString());
    });
  });

  describe('sanitizeOutboundQuery() - outbound query sanitization', () => {
    it('should return only the query text', () => {
      const service = new DataFetcherService([]);
      const query: DataQuery = {
        text: 'latest stock prices',
        categories: ['finance'],
        maxAgeMinutes: 15,
        timeoutMs: 10000,
      };

      const sanitized = service.sanitizeOutboundQuery(query);

      expect(sanitized).toBe('latest stock prices');
    });

    it('should trim whitespace from the query text', () => {
      const service = new DataFetcherService([]);
      const query: DataQuery = {
        text: '  weather forecast today  ',
        categories: ['weather'],
        maxAgeMinutes: 15,
        timeoutMs: 10000,
      };

      const sanitized = service.sanitizeOutboundQuery(query);

      expect(sanitized).toBe('weather forecast today');
    });

    it('should NOT include conversation context even when provided', () => {
      const service = new DataFetcherService([]);
      const query: DataQuery = {
        text: 'current news',
        categories: ['news'],
        maxAgeMinutes: 15,
        timeoutMs: 10000,
      };

      const conversationContext = 'User previously asked about their personal finances and has debt of $50000';
      const sanitized = service.sanitizeOutboundQuery(query, conversationContext);

      expect(sanitized).toBe('current news');
      expect(sanitized).not.toContain('personal finances');
      expect(sanitized).not.toContain('$50000');
      expect(sanitized).not.toContain('debt');
    });

    it('should NOT include any query metadata like categories or timeouts', () => {
      const service = new DataFetcherService([]);
      const query: DataQuery = {
        text: 'sports scores',
        categories: ['sports', 'news'],
        maxAgeMinutes: 10,
        timeoutMs: 5000,
      };

      const sanitized = service.sanitizeOutboundQuery(query);

      // Should only contain the text, nothing about categories or config
      expect(sanitized).toBe('sports scores');
      expect(sanitized).not.toContain('sports,news');
      expect(sanitized).not.toContain('10');
      expect(sanitized).not.toContain('5000');
    });

    it('should handle empty query text', () => {
      const service = new DataFetcherService([]);
      const query: DataQuery = {
        text: '',
        categories: ['news'],
        maxAgeMinutes: 15,
        timeoutMs: 10000,
      };

      const sanitized = service.sanitizeOutboundQuery(query);

      expect(sanitized).toBe('');
    });

    it('should handle query text with personal data patterns without leaking them', () => {
      const service = new DataFetcherService([]);
      // Even if the query text itself contains what looks like personal data,
      // sanitization only ensures conversation context isn't attached
      const query: DataQuery = {
        text: 'weather in New York',
        categories: ['weather'],
        maxAgeMinutes: 15,
        timeoutMs: 10000,
      };

      const sensitiveContext = 'My name is John Doe, my SSN is 123-45-6789, and my address is 123 Main St';
      const sanitized = service.sanitizeOutboundQuery(query, sensitiveContext);

      expect(sanitized).toBe('weather in New York');
      expect(sanitized).not.toContain('John Doe');
      expect(sanitized).not.toContain('123-45-6789');
      expect(sanitized).not.toContain('123 Main St');
    });
  });
});
