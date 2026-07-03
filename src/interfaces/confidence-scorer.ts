/**
 * Confidence Scorer interfaces.
 *
 * Responsibility: Assess response grounding; label segments by source basis;
 * compute confidence scores.
 */

import { RetrievedDocument } from './rag-pipeline.js';
import { DataItem } from './data-fetcher.js';

export interface ConfidenceScorer {
  /** Score a generated response against its sources */
  score(response: string, context: ScoringContext): Promise<ConfidenceResult>;
}

export interface ScoringContext {
  retrievedDocuments: RetrievedDocument[];
  fetchedData: DataItem[];
  query: string;
}

export interface ConfidenceResult {
  overallScore: number;     // 0.0 - 1.0
  segments: ResponseSegment[];
  needsDisclaimer: boolean; // true if score < threshold (default 0.7)
}

export interface ResponseSegment {
  text: string;
  sourceBasis: 'retrieved_evidence' | 'model_knowledge';
  supportingDocIds: string[];
  segmentConfidence: number;
}
