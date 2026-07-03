/**
 * Confidence Scorer service.
 *
 * Responsibility: Assess response grounding against retrieved documents and
 * fetched data; label each response segment by source basis; compute an overall
 * confidence score and determine whether a disclaimer is needed.
 *
 * Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
 */

import {
  ConfidenceScorer,
  ScoringContext,
  ConfidenceResult,
  ResponseSegment,
} from '../interfaces/confidence-scorer.js';
import { CONFIDENCE_THRESHOLD } from '../config/defaults.js';

/**
 * Tokenize text into lowercase word tokens, stripping punctuation.
 */
function tokenize(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^\w\s]/g, '')
    .split(/\s+/)
    .filter((t) => t.length > 0);
}

/**
 * Compute the token overlap ratio between a segment and a reference text.
 * Returns a value between 0.0 and 1.0 representing the fraction of segment
 * tokens that appear in the reference.
 */
function computeOverlap(segmentTokens: string[], referenceTokens: Set<string>): number {
  if (segmentTokens.length === 0) return 0;
  const matchCount = segmentTokens.filter((t) => referenceTokens.has(t)).length;
  return matchCount / segmentTokens.length;
}

/**
 * Split a response into segments (sentences). Falls back to the full text
 * as a single segment if no sentence boundaries are found.
 */
function splitIntoSegments(response: string): string[] {
  // Split on sentence-ending punctuation followed by whitespace or end of string
  const segments = response
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);

  if (segments.length === 0 && response.trim().length > 0) {
    return [response.trim()];
  }
  return segments;
}

export class ConfidenceScorerService implements ConfidenceScorer {
  private readonly threshold: number;

  constructor(threshold: number = CONFIDENCE_THRESHOLD) {
    this.threshold = threshold;
  }

  async score(response: string, context: ScoringContext): Promise<ConfidenceResult> {
    const segments = splitIntoSegments(response);

    // Build token sets for each evidence source
    const docTokenSets = context.retrievedDocuments.map((doc) => ({
      id: doc.id,
      tokens: new Set(tokenize(doc.content)),
    }));

    const dataTokenSets = context.fetchedData.map((item) => ({
      source: item.source,
      tokens: new Set(tokenize(item.content)),
    }));

    const responseSegments: ResponseSegment[] = segments.map((segmentText) => {
      const segmentTokens = tokenize(segmentText);

      // Find best overlap among retrieved documents
      let bestDocOverlap = 0;
      const supportingDocIds: string[] = [];

      for (const docSet of docTokenSets) {
        const overlap = computeOverlap(segmentTokens, docSet.tokens);
        if (overlap > bestDocOverlap) {
          bestDocOverlap = overlap;
        }
        // A document supports the segment if overlap exceeds a minimum threshold
        if (overlap >= 0.3) {
          supportingDocIds.push(docSet.id);
        }
      }

      // Find best overlap among fetched data
      let bestDataOverlap = 0;
      for (const dataSet of dataTokenSets) {
        const overlap = computeOverlap(segmentTokens, dataSet.tokens);
        if (overlap > bestDataOverlap) {
          bestDataOverlap = overlap;
        }
        // If fetched data supports it, we can treat it as evidence too
        if (overlap >= 0.3) {
          // Fetched data doesn't have a doc ID, but contributes to evidence
          // We use a synthetic ID for tracking
          const syntheticId = `data:${dataSet.source}`;
          if (!supportingDocIds.includes(syntheticId)) {
            supportingDocIds.push(syntheticId);
          }
        }
      }

      // The segment's confidence is the best overlap from any source
      const segmentConfidence = Math.min(1.0, Math.max(bestDocOverlap, bestDataOverlap));

      // Determine source basis: if any supporting docs/data found, it's retrieved_evidence
      const sourceBasis: 'retrieved_evidence' | 'model_knowledge' =
        supportingDocIds.length > 0 ? 'retrieved_evidence' : 'model_knowledge';

      return {
        text: segmentText,
        sourceBasis,
        supportingDocIds,
        segmentConfidence,
      };
    });

    // Compute overall confidence as weighted average (weight by token count)
    const overallScore = this.computeOverallScore(responseSegments);

    // Determine if disclaimer is needed
    const needsDisclaimer = overallScore < this.threshold;

    return {
      overallScore,
      segments: responseSegments,
      needsDisclaimer,
    };
  }

  /**
   * Compute overall confidence as a weighted average of segment confidences,
   * weighted by the number of tokens in each segment.
   */
  private computeOverallScore(segments: ResponseSegment[]): number {
    if (segments.length === 0) return 0;

    let totalWeight = 0;
    let weightedSum = 0;

    for (const segment of segments) {
      const weight = tokenize(segment.text).length || 1;
      weightedSum += segment.segmentConfidence * weight;
      totalWeight += weight;
    }

    if (totalWeight === 0) return 0;

    const score = weightedSum / totalWeight;
    // Clamp to [0.0, 1.0]
    return Math.min(1.0, Math.max(0.0, score));
  }
}
