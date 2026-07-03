/**
 * Unit tests for HealthManager service.
 *
 * Tests cover:
 * - Service health checking (healthy/degraded/unavailable transitions)
 * - checkAllServices() for all registered services
 * - Auto-recovery with retry logic (up to 3 attempts)
 * - User notification on complete recovery failure
 * - Uptime metrics calculation with trackingSince
 * - SLA target checking (99.5% monthly)
 * - recordDowntime with startTime/endTime
 *
 * Requirements: 2.2, 2.3, 2.5, 8.7
 */

import { describe, it, expect, vi } from 'vitest';
import { HealthManager } from '../../src/services/health-manager.js';
import { RECOVERY_MAX_RETRIES } from '../../src/config/defaults.js';

describe('HealthManager', () => {
  describe('checkService', () => {
    it('should report healthy when health check returns true', async () => {
      const manager = new HealthManager();
      const healthCheck = vi.fn().mockResolvedValue(true);

      const result = await manager.checkService('llm-engine', healthCheck);

      expect(result.serviceName).toBe('llm-engine');
      expect(result.status).toBe('healthy');
      expect(result.lastCheckAt).toBeInstanceOf(Date);
      expect(result.responseTimeMs).toBeGreaterThanOrEqual(0);
    });

    it('should report degraded when health check returns false (first failure)', async () => {
      const manager = new HealthManager();
      const healthCheck = vi.fn().mockResolvedValue(false);

      const result = await manager.checkService('rag-pipeline', healthCheck);

      expect(result.serviceName).toBe('rag-pipeline');
      expect(result.status).toBe('degraded');
    });

    it('should report degraded when health check throws an error', async () => {
      const manager = new HealthManager();
      const healthCheck = vi.fn().mockRejectedValue(new Error('Connection refused'));

      const result = await manager.checkService('data-fetcher', healthCheck);

      expect(result.status).toBe('degraded');
    });

    it('should report unavailable after 3 consecutive failures', async () => {
      const manager = new HealthManager();
      const failingCheck = vi.fn().mockResolvedValue(false);

      await manager.checkService('voice-stt', failingCheck);
      await manager.checkService('voice-stt', failingCheck);
      const result = await manager.checkService('voice-stt', failingCheck);

      expect(result.status).toBe('unavailable');
    });

    it('should reset to healthy on successful check after failures', async () => {
      const manager = new HealthManager();
      const failingCheck = vi.fn().mockResolvedValue(false);
      const passingCheck = vi.fn().mockResolvedValue(true);

      await manager.checkService('service-a', failingCheck);
      await manager.checkService('service-a', failingCheck);
      const result = await manager.checkService('service-a', passingCheck);

      expect(result.status).toBe('healthy');
    });

    it('should measure response time in milliseconds', async () => {
      const manager = new HealthManager();
      const healthCheck = vi.fn().mockImplementation(
        () => new Promise(resolve => setTimeout(() => resolve(true), 10))
      );

      const result = await manager.checkService('timed-service', healthCheck);

      expect(result.responseTimeMs).toBeGreaterThanOrEqual(10);
    });
  });

  describe('checkAllServices', () => {
    it('should return health reports for all registered services', async () => {
      const manager = new HealthManager();
      manager.registerService('svc-a', () => Promise.resolve(true));
      manager.registerService('svc-b', () => Promise.resolve(false));
      manager.registerService('svc-c', () => Promise.resolve(true));

      const reports = await manager.checkAllServices();

      expect(reports).toHaveLength(3);
      expect(reports.map(r => r.serviceName)).toContain('svc-a');
      expect(reports.map(r => r.serviceName)).toContain('svc-b');
      expect(reports.map(r => r.serviceName)).toContain('svc-c');
    });

    it('should return empty array when no services are registered', async () => {
      const manager = new HealthManager();
      const reports = await manager.checkAllServices();
      expect(reports).toHaveLength(0);
    });

    it('should include ServiceHealthReport fields for each service', async () => {
      const manager = new HealthManager();
      manager.registerService('svc-healthy', () => Promise.resolve(true));

      const reports = await manager.checkAllServices();

      expect(reports[0]).toHaveProperty('serviceName');
      expect(reports[0]).toHaveProperty('status');
      expect(reports[0]).toHaveProperty('lastCheckAt');
      expect(reports[0]).toHaveProperty('responseTimeMs');
    });
  });

  describe('attemptRecovery', () => {
    it('should return success on first attempt when restart succeeds immediately', async () => {
      const manager = new HealthManager();
      const restartFn = vi.fn().mockResolvedValue(true);

      const result = await manager.attemptRecovery('llm-engine', restartFn);

      expect(result.success).toBe(true);
      expect(result.attempts).toBe(1);
      expect(result.recoveredAt).toBeInstanceOf(Date);
      expect(result.error).toBeUndefined();
      expect(restartFn).toHaveBeenCalledTimes(1);
    });

    it('should retry and succeed on second attempt', async () => {
      const manager = new HealthManager();
      const restartFn = vi.fn()
        .mockResolvedValueOnce(false)
        .mockResolvedValueOnce(true);

      const result = await manager.attemptRecovery('rag-pipeline', restartFn);

      expect(result.success).toBe(true);
      expect(result.attempts).toBe(2);
      expect(result.recoveredAt).toBeInstanceOf(Date);
      expect(restartFn).toHaveBeenCalledTimes(2);
    });

    it('should retry and succeed on third (final) attempt', async () => {
      const manager = new HealthManager();
      const restartFn = vi.fn()
        .mockResolvedValueOnce(false)
        .mockResolvedValueOnce(false)
        .mockResolvedValueOnce(true);

      const result = await manager.attemptRecovery('data-fetcher', restartFn);

      expect(result.success).toBe(true);
      expect(result.attempts).toBe(3);
      expect(result.recoveredAt).toBeInstanceOf(Date);
      expect(restartFn).toHaveBeenCalledTimes(3);
    });

    it('should fail with error after all 3 attempts fail', async () => {
      const manager = new HealthManager();
      const restartFn = vi.fn().mockResolvedValue(false);

      const result = await manager.attemptRecovery('voice-tts', restartFn);

      expect(result.success).toBe(false);
      expect(result.attempts).toBe(RECOVERY_MAX_RETRIES);
      expect(result.error).toBeDefined();
      expect(result.error).toContain('voice-tts');
      expect(result.error).toContain('temporarily unavailable');
      expect(result.recoveredAt).toBeUndefined();
      expect(restartFn).toHaveBeenCalledTimes(RECOVERY_MAX_RETRIES);
    });

    it('should not retry beyond RECOVERY_MAX_RETRIES', async () => {
      const manager = new HealthManager();
      const restartFn = vi.fn().mockResolvedValue(false);

      await manager.attemptRecovery('service-x', restartFn);

      expect(restartFn).toHaveBeenCalledTimes(3);
    });

    it('should handle restart function throwing errors as failures', async () => {
      const manager = new HealthManager();
      const restartFn = vi.fn().mockRejectedValue(new Error('Crash'));

      const result = await manager.attemptRecovery('crashing-service', restartFn);

      expect(result.success).toBe(false);
      expect(result.attempts).toBe(RECOVERY_MAX_RETRIES);
      expect(result.error).toBeDefined();
    });

    it('should emit a notification message when all recovery attempts fail', async () => {
      const manager = new HealthManager();
      const restartFn = vi.fn().mockResolvedValue(false);

      await manager.attemptRecovery('important-service', restartFn);

      const notifications = manager.getNotifications();
      expect(notifications).toHaveLength(1);
      expect(notifications[0]).toContain('important-service');
      expect(notifications[0]).toContain('temporarily unavailable');
    });

    it('should clear health state on successful recovery', async () => {
      const manager = new HealthManager();
      // First, mark the service as unhealthy
      await manager.checkService('llm-engine', () => Promise.resolve(false));
      await manager.checkService('llm-engine', () => Promise.resolve(false));

      const healthBefore = manager.getServiceHealth('llm-engine');
      expect(healthBefore?.status).toBe('degraded');

      // Now recover successfully
      const restartFn = vi.fn().mockResolvedValue(true);
      await manager.attemptRecovery('llm-engine', restartFn);

      const healthAfter = manager.getServiceHealth('llm-engine');
      expect(healthAfter?.status).toBe('healthy');
    });

    it('should return error when no restart function is available', async () => {
      const manager = new HealthManager();

      const result = await manager.attemptRecovery('unregistered-service');

      expect(result.success).toBe(false);
      expect(result.attempts).toBe(0);
      expect(result.error).toContain('No restart function');
    });

    it('should use registered restart function when none provided directly', async () => {
      const manager = new HealthManager();
      const restartFn = vi.fn().mockResolvedValue(true);
      manager.registerService('my-service', () => Promise.resolve(true), restartFn);

      const result = await manager.attemptRecovery('my-service');

      expect(result.success).toBe(true);
      expect(restartFn).toHaveBeenCalledTimes(1);
    });
  });

  describe('uptime tracking', () => {
    it('should report 100% uptime with no recorded downtime', () => {
      const startTime = new Date(Date.now() - 60_000); // started 60s ago
      const manager = new HealthManager(startTime);

      const metrics = manager.getUptime();

      expect(metrics.uptimePercent).toBeCloseTo(100, 0);
      expect(metrics.totalDowntimeMs).toBe(0);
      expect(metrics.trackingSince).toEqual(startTime);
    });

    it('should correctly calculate uptime after recording downtime', () => {
      // Start 100 seconds ago
      const startTime = new Date(Date.now() - 100_000);
      const manager = new HealthManager(startTime);

      // Record 10 seconds of downtime (10% downtime → ~90% uptime)
      const downtimeStart = new Date(Date.now() - 50_000);
      const downtimeEnd = new Date(downtimeStart.getTime() + 10_000);
      manager.recordDowntime(downtimeStart, downtimeEnd);

      const metrics = manager.getUptime();

      expect(metrics.totalDowntimeMs).toBe(10_000);
      // Uptime should be approximately 90%
      expect(metrics.uptimePercent).toBeGreaterThan(89);
      expect(metrics.uptimePercent).toBeLessThan(91);
    });

    it('should accumulate multiple downtime records', () => {
      const startTime = new Date(Date.now() - 100_000);
      const manager = new HealthManager(startTime);

      const now = Date.now();
      manager.recordDowntime(new Date(now - 30_000), new Date(now - 25_000)); // 5s
      manager.recordDowntime(new Date(now - 20_000), new Date(now - 17_000)); // 3s
      manager.recordDowntime(new Date(now - 10_000), new Date(now - 8_000));  // 2s

      const metrics = manager.getUptime();
      expect(metrics.totalDowntimeMs).toBe(10_000);
    });

    it('should ignore downtime where end is before start', () => {
      const startTime = new Date(Date.now() - 60_000);
      const manager = new HealthManager(startTime);

      const now = Date.now();
      // end before start — should be ignored
      manager.recordDowntime(new Date(now - 5_000), new Date(now - 10_000));
      // same time — zero duration, should be ignored
      const sameTime = new Date(now - 5_000);
      manager.recordDowntime(sameTime, sameTime);

      const metrics = manager.getUptime();
      expect(metrics.totalDowntimeMs).toBe(0);
    });

    it('should include trackingSince in uptime metrics', () => {
      const startTime = new Date('2024-01-01T00:00:00Z');
      const manager = new HealthManager(startTime);

      const metrics = manager.getUptime();
      expect(metrics.trackingSince).toEqual(startTime);
    });
  });

  describe('isWithinSLA', () => {
    it('should return true when uptime meets 99.5% target', () => {
      const startTime = new Date(Date.now() - 1_000_000);
      const manager = new HealthManager(startTime);

      // Record minimal downtime (well under 0.5%)
      const now = Date.now();
      manager.recordDowntime(new Date(now - 200), new Date(now - 100)); // 100ms

      expect(manager.isWithinSLA()).toBe(true);
    });

    it('should return false when uptime is below 99.5% target', () => {
      const startTime = new Date(Date.now() - 100_000);
      const manager = new HealthManager(startTime);

      // Record 1% downtime (1000ms out of ~100000ms)
      const now = Date.now();
      manager.recordDowntime(new Date(now - 2_000), new Date(now - 1_000)); // 1s

      expect(manager.isWithinSLA()).toBe(false);
    });

    it('should accept a custom SLA target', () => {
      const startTime = new Date(Date.now() - 100_000);
      const manager = new HealthManager(startTime);

      // Record 5% downtime
      const now = Date.now();
      manager.recordDowntime(new Date(now - 10_000), new Date(now - 5_000)); // 5s

      // Fails at 99.5% target
      expect(manager.isWithinSLA(99.5)).toBe(false);
      // Passes at 90% target
      expect(manager.isWithinSLA(90)).toBe(true);
    });

    it('should return true for fresh manager with no history', () => {
      const manager = new HealthManager();
      // Immediately after creation, uptime should be 100%
      expect(manager.isWithinSLA()).toBe(true);
    });
  });

  describe('getAllServiceHealth', () => {
    it('should return health reports for all checked services', async () => {
      const manager = new HealthManager();
      await manager.checkService('svc-a', () => Promise.resolve(true));
      await manager.checkService('svc-b', () => Promise.resolve(false));
      await manager.checkService('svc-c', () => Promise.resolve(true));

      const all = manager.getAllServiceHealth();

      expect(all).toHaveLength(3);
      expect(all.map(s => s.serviceName)).toContain('svc-a');
      expect(all.map(s => s.serviceName)).toContain('svc-b');
      expect(all.map(s => s.serviceName)).toContain('svc-c');
    });
  });

  describe('registerService', () => {
    it('should register a service for health checking', async () => {
      const manager = new HealthManager();
      const healthFn = vi.fn().mockResolvedValue(true);
      manager.registerService('my-service', healthFn);

      const reports = await manager.checkAllServices();

      expect(reports).toHaveLength(1);
      expect(reports[0].serviceName).toBe('my-service');
      expect(healthFn).toHaveBeenCalledTimes(1);
    });

    it('should register a service with optional restart function', async () => {
      const manager = new HealthManager();
      const healthFn = vi.fn().mockResolvedValue(true);
      const restartFn = vi.fn().mockResolvedValue(true);
      manager.registerService('my-service', healthFn, restartFn);

      const result = await manager.attemptRecovery('my-service');

      expect(result.success).toBe(true);
      expect(restartFn).toHaveBeenCalled();
    });
  });

  describe('isAvailable', () => {
    it('should return true when no services are registered', () => {
      const manager = new HealthManager();
      expect(manager.isAvailable()).toBe(true);
    });

    it('should return true when all services are healthy', async () => {
      const manager = new HealthManager();
      await manager.checkService('svc-a', () => Promise.resolve(true));
      await manager.checkService('svc-b', () => Promise.resolve(true));

      expect(manager.isAvailable()).toBe(true);
    });

    it('should return true when services are degraded but not unavailable', async () => {
      const manager = new HealthManager();
      await manager.checkService('svc-a', () => Promise.resolve(false)); // degraded (1 failure)

      expect(manager.isAvailable()).toBe(true);
    });

    it('should return false when any service is unavailable', async () => {
      const manager = new HealthManager();
      const failingCheck = () => Promise.resolve(false);

      // 3 consecutive failures → unavailable
      await manager.checkService('svc-a', failingCheck);
      await manager.checkService('svc-a', failingCheck);
      await manager.checkService('svc-a', failingCheck);

      expect(manager.isAvailable()).toBe(false);
    });

    it('should return true after recovery from unavailable state', async () => {
      const manager = new HealthManager();
      const failingCheck = () => Promise.resolve(false);
      const passingCheck = () => Promise.resolve(true);

      await manager.checkService('svc-a', failingCheck);
      await manager.checkService('svc-a', failingCheck);
      await manager.checkService('svc-a', failingCheck);
      expect(manager.isAvailable()).toBe(false);

      // Recovery
      await manager.checkService('svc-a', passingCheck);
      expect(manager.isAvailable()).toBe(true);
    });
  });

  describe('recordDowntimeMs', () => {
    it('should record downtime by duration in milliseconds', () => {
      const startTime = new Date(Date.now() - 100_000);
      const manager = new HealthManager(startTime);

      manager.recordDowntimeMs(5_000);

      const metrics = manager.getUptime();
      expect(metrics.totalDowntimeMs).toBe(5_000);
    });

    it('should accumulate multiple downtime durations', () => {
      const startTime = new Date(Date.now() - 100_000);
      const manager = new HealthManager(startTime);

      manager.recordDowntimeMs(2_000);
      manager.recordDowntimeMs(3_000);
      manager.recordDowntimeMs(1_000);

      const metrics = manager.getUptime();
      expect(metrics.totalDowntimeMs).toBe(6_000);
    });

    it('should ignore zero or negative durations', () => {
      const startTime = new Date(Date.now() - 60_000);
      const manager = new HealthManager(startTime);

      manager.recordDowntimeMs(0);
      manager.recordDowntimeMs(-500);

      const metrics = manager.getUptime();
      expect(metrics.totalDowntimeMs).toBe(0);
    });
  });
});
