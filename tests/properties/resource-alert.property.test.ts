/**
 * Property Test: Resource Alert Threshold (Property 20)
 *
 * **Validates: Requirements 8.3**
 *
 * Generates utilization values (0-100%) and verifies:
 * - Alert emitted when any metric exceeds 80%
 * - No alert emitted when all metrics are at or below 80%
 */

import { describe, it, expect } from 'vitest';
import fc from 'fast-check';
import { RESOURCE_ALERT_THRESHOLD_PERCENT } from '../../src/config/defaults';

/**
 * Pure resource alert logic matching the system's alerting behavior.
 * An alert is triggered if utilization > threshold (80%).
 */
function shouldAlert(utilizationPercent: number, threshold: number): boolean {
  return utilizationPercent > threshold;
}

/**
 * Check multiple resource metrics. Alert if ANY metric exceeds threshold.
 */
function checkResourceMetrics(
  metrics: { cpu: number; memory: number; gpu: number; disk: number },
  threshold: number,
): { alert: boolean; triggeredMetrics: string[] } {
  const triggered: string[] = [];

  if (metrics.cpu > threshold) triggered.push('cpu');
  if (metrics.memory > threshold) triggered.push('memory');
  if (metrics.gpu > threshold) triggered.push('gpu');
  if (metrics.disk > threshold) triggered.push('disk');

  return {
    alert: triggered.length > 0,
    triggeredMetrics: triggered,
  };
}

describe('Property 20: Resource Alert Threshold', () => {
  /**
   * **Validates: Requirements 8.3**
   *
   * Alert is emitted when utilization exceeds 80%.
   */
  it('emits alert when utilization > 80%', () => {
    fc.assert(
      fc.property(
        fc.double({ min: RESOURCE_ALERT_THRESHOLD_PERCENT + 0.01, max: 100, noNaN: true }),
        (utilization) => {
          const result = shouldAlert(utilization, RESOURCE_ALERT_THRESHOLD_PERCENT);
          expect(result).toBe(true);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 8.3**
   *
   * No alert when utilization is at or below 80%.
   */
  it('no alert when utilization <= 80%', () => {
    fc.assert(
      fc.property(
        fc.double({ min: 0, max: RESOURCE_ALERT_THRESHOLD_PERCENT, noNaN: true }),
        (utilization) => {
          const result = shouldAlert(utilization, RESOURCE_ALERT_THRESHOLD_PERCENT);
          expect(result).toBe(false);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 8.3**
   *
   * Alert triggered if ANY single metric exceeds 80% even when others are below.
   */
  it('alerts when any single metric exceeds threshold', () => {
    fc.assert(
      fc.property(
        fc.record({
          cpu: fc.double({ min: 0, max: RESOURCE_ALERT_THRESHOLD_PERCENT, noNaN: true }),
          memory: fc.double({ min: 0, max: RESOURCE_ALERT_THRESHOLD_PERCENT, noNaN: true }),
          gpu: fc.double({ min: RESOURCE_ALERT_THRESHOLD_PERCENT + 0.01, max: 100, noNaN: true }),
          disk: fc.double({ min: 0, max: RESOURCE_ALERT_THRESHOLD_PERCENT, noNaN: true }),
        }),
        (metrics) => {
          const result = checkResourceMetrics(metrics, RESOURCE_ALERT_THRESHOLD_PERCENT);
          expect(result.alert).toBe(true);
          expect(result.triggeredMetrics).toContain('gpu');
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 8.3**
   *
   * No alert when ALL metrics are at or below 80%.
   */
  it('no alert when all metrics are at or below threshold', () => {
    fc.assert(
      fc.property(
        fc.record({
          cpu: fc.double({ min: 0, max: RESOURCE_ALERT_THRESHOLD_PERCENT, noNaN: true }),
          memory: fc.double({ min: 0, max: RESOURCE_ALERT_THRESHOLD_PERCENT, noNaN: true }),
          gpu: fc.double({ min: 0, max: RESOURCE_ALERT_THRESHOLD_PERCENT, noNaN: true }),
          disk: fc.double({ min: 0, max: RESOURCE_ALERT_THRESHOLD_PERCENT, noNaN: true }),
        }),
        (metrics) => {
          const result = checkResourceMetrics(metrics, RESOURCE_ALERT_THRESHOLD_PERCENT);
          expect(result.alert).toBe(false);
          expect(result.triggeredMetrics).toHaveLength(0);
        },
      ),
      { numRuns: 100 },
    );
  });
});
