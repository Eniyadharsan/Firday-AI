/**
 * Data Fetcher interfaces.
 *
 * Responsibility: Real-time data retrieval from external sources
 * with fallback and verification logic.
 */

export interface DataFetcher {
  /** Fetch real-time data for a query */
  fetch(query: DataQuery): Promise<DataFetchResult>;
}

export interface DataQuery {
  text: string;
  categories: DataCategory[];
  maxAgeMinutes: number;    // default 15
  timeoutMs: number;        // default 10000
}

export type DataCategory = 'news' | 'web_search' | 'weather' | 'finance' | 'sports';

export interface DataFetchResult {
  items: DataItem[];
  failedCategories: DataCategory[];
  allFailed: boolean;
}

export interface DataItem {
  content: string;
  source: string;
  retrievedAt: Date;
  category: DataCategory;
  verified: boolean;        // true if corroborated by 2+ sources
}
