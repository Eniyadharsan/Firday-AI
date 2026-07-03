/**
 * Data Fetcher Service
 *
 * Responsibility: Real-time data retrieval from external sources
 * with fallback, source verification, and citation formatting.
 *
 * Requirements: 3.1–3.6, 9.2
 */

import {
  DataFetcher,
  DataQuery,
  DataCategory,
  DataFetchResult,
  DataItem,
} from '../interfaces/data-fetcher.js';
import { DATA_FRESHNESS_MAX_AGE_MINUTES, DATA_FETCH_TIMEOUT_SECONDS } from '../config/defaults.js';

/**
 * Source provider abstraction for fetching data from a specific source.
 */
export interface SourceProvider {
  name: string;
  category: DataCategory;
  fetch(queryText: string, timeoutMs: number): Promise<RawDataItem[]>;
}

export interface RawDataItem {
  content: string;
  source: string;
  retrievedAt: Date;
  category: DataCategory;
}

/**
 * Circuit breaker states for source providers.
 */
interface CircuitBreakerState {
  state: 'closed' | 'open' | 'half-open';
  failureCount: number;
  lastFailureAt: Date | null;
  cooldownMs: number;
}

/**
 * DataFetcherService implements real-time data retrieval with:
 * - Source fallback (at least 2 alternatives per category)
 * - Data freshness filtering (max 15 min)
 * - Source verification (2+ independent sources → verified)
 * - Citation formatting (source + timestamp)
 * - Outbound query sanitization (no conversation context or personal data)
 * - Circuit breaker pattern for resilience
 */
export class DataFetcherService implements DataFetcher {
  private providers: Map<DataCategory, SourceProvider[]>;
  private circuitBreakers: Map<string, CircuitBreakerState>;

  constructor(providers: SourceProvider[] = []) {
    this.providers = new Map();
    this.circuitBreakers = new Map();

    for (const provider of providers) {
      const existing = this.providers.get(provider.category) ?? [];
      existing.push(provider);
      this.providers.set(provider.category, existing);
      this.circuitBreakers.set(provider.name, {
        state: 'closed',
        failureCount: 0,
        lastFailureAt: null,
        cooldownMs: 30_000,
      });
    }
  }

  /**
   * Fetch real-time data for a query with fallback and verification.
   * Requirements: 3.1, 3.3, 3.4, 3.5, 3.6, 9.2
   */
  async fetch(query: DataQuery): Promise<DataFetchResult> {
    const timeoutMs = query.timeoutMs ?? DATA_FETCH_TIMEOUT_SECONDS * 1000;
    const maxAgeMinutes = query.maxAgeMinutes ?? DATA_FRESHNESS_MAX_AGE_MINUTES;
    const now = new Date();

    // Sanitize outbound query to ensure no conversation context leaks (Req 9.2)
    const sanitizedText = this.sanitizeOutboundQuery(query);

    const allItems: DataItem[] = [];
    const failedCategories: DataCategory[] = [];

    for (const category of query.categories) {
      const categoryItems = await this.fetchCategory(
        sanitizedText,
        category,
        timeoutMs,
        now,
        maxAgeMinutes,
      );

      if (categoryItems.length === 0) {
        failedCategories.push(category);
      } else {
        allItems.push(...categoryItems);
      }
    }

    // Verify items by corroboration across independent sources (Req 3.6)
    const verifiedItems = this.verifyItems(allItems);

    return {
      items: verifiedItems,
      failedCategories,
      allFailed: failedCategories.length === query.categories.length && query.categories.length > 0,
    };
  }

  /**
   * Fetch data for a specific category with fallback to alternative sources.
   * Attempts primary source first, then up to 2 alternatives on failure.
   * Requirements: 3.4
   */
  private async fetchCategory(
    queryText: string,
    category: DataCategory,
    timeoutMs: number,
    now: Date,
    maxAgeMinutes: number,
  ): Promise<DataItem[]> {
    const providers = this.providers.get(category) ?? [];
    const items: DataItem[] = [];

    let attempts = 0;
    const maxAttempts = Math.min(providers.length, 3); // primary + 2 alternatives

    for (const provider of providers) {
      if (attempts >= maxAttempts) break;

      const breaker = this.circuitBreakers.get(provider.name);
      if (breaker && !this.isCircuitAvailable(breaker, now)) {
        continue;
      }

      attempts++;

      try {
        const rawItems = await provider.fetch(queryText, timeoutMs);
        this.recordSuccess(provider.name);

        // Filter by freshness (Req 3.1)
        const freshItems = rawItems
          .filter((item) => this.isWithinFreshness(item.retrievedAt, now, maxAgeMinutes))
          .map((item): DataItem => ({
            content: item.content,
            source: item.source,
            retrievedAt: item.retrievedAt,
            category: item.category,
            verified: false, // Will be set by verifyItems
          }));

        items.push(...freshItems);
      } catch {
        this.recordFailure(provider.name);
      }
    }

    return items;
  }

  /**
   * Verify data items by checking corroboration across independent sources.
   *
   * Items corroborated by 2+ different sources → verified = true
   * Items from a single source only → verified = false
   *
   * Corroboration is determined by content similarity (exact match on normalized content).
   *
   * Requirements: 3.6, 9.2
   */
  verifyItems(items: DataItem[]): DataItem[] {
    // Group items by normalized content to find corroborated information
    const contentGroups = new Map<string, DataItem[]>();

    for (const item of items) {
      const normalizedContent = this.normalizeContent(item.content);
      const group = contentGroups.get(normalizedContent) ?? [];
      group.push(item);
      contentGroups.set(normalizedContent, group);
    }

    // For each group, check how many independent sources corroborate
    const verifiedItems: DataItem[] = [];

    for (const group of contentGroups.values()) {
      const uniqueSources = new Set(group.map((item) => item.source));
      const isVerified = uniqueSources.size >= 2;

      for (const item of group) {
        verifiedItems.push({
          ...item,
          verified: isVerified,
        });
      }
    }

    return verifiedItems;
  }

  /**
   * Format a citation string for a data item.
   * Format: "{source} (retrieved {timestamp})"
   *
   * Requirements: 3.2
   */
  formatCitation(item: DataItem): string {
    const timestamp = item.retrievedAt.toISOString();
    return `${item.source} (retrieved ${timestamp})`;
  }

  /**
   * Sanitize an outbound query to ensure only search text is sent.
   * Strips any conversation context or personal data from the query.
   * Returns only the query.text field content, ignoring all other fields.
   *
   * The conversationContext parameter is intentionally accepted but never used,
   * to enforce data isolation — no conversation context or personal data is
   * ever included in outbound requests.
   *
   * Requirements: 9.2
   */
  sanitizeOutboundQuery(query: DataQuery, _conversationContext?: string): string {
    // Only extract the text field - never include conversation context or personal data
    // The conversationContext parameter is intentionally ignored to enforce data isolation
    return query.text.trim();
  }

  /**
   * Normalize content for comparison purposes.
   * Lowercases, trims whitespace, and collapses multiple spaces.
   */
  private normalizeContent(content: string): string {
    return content.toLowerCase().trim().replace(/\s+/g, ' ');
  }

  /**
   * Check if a data item is within the freshness window.
   */
  private isWithinFreshness(retrievedAt: Date, now: Date, maxAgeMinutes: number): boolean {
    const ageMs = now.getTime() - retrievedAt.getTime();
    const maxAgeMs = maxAgeMinutes * 60 * 1000;
    return ageMs <= maxAgeMs;
  }

  /**
   * Check if a circuit breaker allows requests.
   */
  private isCircuitAvailable(breaker: CircuitBreakerState, now: Date): boolean {
    if (breaker.state === 'closed') return true;
    if (breaker.state === 'open' && breaker.lastFailureAt) {
      const elapsed = now.getTime() - breaker.lastFailureAt.getTime();
      if (elapsed >= breaker.cooldownMs) {
        breaker.state = 'half-open';
        return true;
      }
      return false;
    }
    // half-open: allow one test request
    return breaker.state === 'half-open';
  }

  /**
   * Record a successful request for circuit breaker tracking.
   */
  private recordSuccess(providerName: string): void {
    const breaker = this.circuitBreakers.get(providerName);
    if (breaker) {
      breaker.state = 'closed';
      breaker.failureCount = 0;
    }
  }

  /**
   * Record a failed request for circuit breaker tracking.
   * Opens circuit after 3 consecutive failures.
   */
  private recordFailure(providerName: string): void {
    const breaker = this.circuitBreakers.get(providerName);
    if (breaker) {
      breaker.failureCount++;
      breaker.lastFailureAt = new Date();
      if (breaker.failureCount >= 3) {
        breaker.state = 'open';
      }
    }
  }
}
