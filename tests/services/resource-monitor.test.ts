/**
 * Unit tests for ResourceMonitor service.
 *
 * Covers: threshold evaluation, alert emission, no alert below threshold.
 * Requirements: 8.3
 */

import { describe, it, expect, vi } from 'vitest';
import { ResourceMonitor, ResourceMetrics } from '../../src/services/resource-monitor.js';
import { RESOURCE_ALERT_THRESHOLD_PERCENT } from '../../src/config/defaults.js';

describe('ResourceMonitor', () => {
  describe('evaluateThresholds', () => {
    it('should detect CPU breach when value exceeds threshold', () => {
      const monitor = new ResourceMonitor();
      const metrics: ResourceMetrics = {
        cpuPercent: 85,
        memoryPercent: 50,
        gpuPercent: 30,
        diskPercent: 40,
        timestamp: new Date(),
      };

      const result = monitor.evaluateThresholds(metrics);

      expect(result.breached).toBe(true);
      expect(result.breaches).toHaveLength(1);
      expect(result.breaches[0].metric).toBe('cpu');
      expect(result.breaches[0].value).toBe(85);
      expect(result.breaches[0].threshold).toBe(RESOURCE_ALERT_THRESHOLD_PERCENT);
    });

    it('should detect multiple breaches simultaneously', () => {
      const monitor = new ResourceMonitor();
      const metrics: ResourceMetrics = {
        cpuPercent: 95,
        memoryPercent: 90,
        gpuPercent: 85,
        diskPercent: 82,
        timestamp: new Date(),
      };

      const result = monitor.evaluateThresholds(metrics);

      expect(result.breached).toBe(true);
      expect(result.breaches).toHaveLength(4);
      const metricNames = result.breaches.map((b) => b.metric);
      expect(metricNames).toContain('cpu');
      expect(metricNames).toContain('memory');
      expect(metricNames).toContain('gpu');
      expect(metricNames).toContain('disk');
    });

    it('should NOT emit a breach when all metrics are at or below 80%', () => {
      const monitor = new ResourceMonitor();
      const metrics: ResourceMetrics = {
        cpuPercent: 80,
        memoryPercent: 75,
        gpuPercent: 60,
        diskPercent: 50,
        timestamp: new Date(),
      };

      const result = monitor.evaluateThresholds(metrics);

      expect(result.breached).toBe(false);
      expect(result.breaches).toHaveLength(0);
    });

    it('should NOT breach at exactly 80% (threshold is strict >)', () => {
      const monitor = new ResourceMonitor();
      const metrics: ResourceMetrics = {
        cpuPercent: 80,
        memoryPercent: 80,
        gpuPercent: 80,
        diskPercent: 80,
        timestamp: new Date(),
      };

      const result = monitor.evaluateThresholds(metrics);

      expect(result.breached).toBe(false);
      expect(result.breaches).toHaveLength(0);
    });

    it('should breach at 80.1%', () => {
      const monitor = new ResourceMonitor();
      const metrics: ResourceMetrics = {
        cpuPercent: 80.1,
        memoryPercent: 50,
        gpuPercent: 50,
        diskPercent: 50,
        timestamp: new Date(),
      };

      const result = monitor.evaluateThresholds(metrics);

      expect(result.breached).toBe(true);
      expect(result.breaches).toHaveLength(1);
      expect(result.breaches[0].metric).toBe('cpu');
    });

    it('should respect custom thresholds from alert config', () => {
      const monitor = new ResourceMonitor({
        config: {
          cpuThreshold: 90,
          memoryThreshold: 70,
          gpuThreshold: 80,
          diskThreshold: 80,
        },
      });
      const metrics: ResourceMetrics = {
        cpuPercent: 85,
        memoryPercent: 75,
        gpuPercent: 50,
        diskPercent: 50,
        timestamp: new Date(),
      };

      const result = monitor.evaluateThresholds(metrics);

      // CPU at 85 is below custom 90 threshold — no breach
      // Memory at 75 exceeds custom 70 threshold — breach
      expect(result.breached).toBe(true);
      expect(result.breaches).toHaveLength(1);
      expect(result.breaches[0].metric).toBe('memory');
    });
  });

  describe('emitAlert', () => {
    it('should send webhook alert successfully', async () => {
      const webhookSender = vi.fn().mockResolvedValue(true);
      const monitor = new ResourceMonitor({
        config: {
          notificationChannel: 'webhook',
          notificationTarget: 'https://hooks.example.com/alert',
        },
        webhookSender,
      });

      const result = await monitor.emitAlert('cpu', 92);

      expect(result.success).toBe(true);
      expect(result.channel).toBe('webhook');
      expect(result.target).toBe('https://hooks.example.com/alert');
      expect(result.metric).toBe('cpu');
      expect(result.value).toBe(92);
      expect(webhookSender).toHaveBeenCalledTimes(1);
    });

    it('should send email alert successfully', async () => {
      const emailSender = vi.fn().mockResolvedValue(true);
      const monitor = new ResourceMonitor({
        config: {
          notificationChannel: 'email',
          notificationTarget: 'admin@example.com',
        },
        emailSender,
      });

      const result = await monitor.emitAlert('memory', 88);

      expect(result.success).toBe(true);
      expect(result.channel).toBe('email');
      expect(result.metric).toBe('memory');
      expect(emailSender).toHaveBeenCalledTimes(1);
    });

    it('should send SMS alert successfully', async () => {
      const smsSender = vi.fn().mockResolvedValue(true);
      const monitor = new ResourceMonitor({
        config: {
          notificationChannel: 'sms',
          notificationTarget: '+15551234567',
        },
        smsSender,
      });

      const result = await monitor.emitAlert('disk', 95);

      expect(result.success).toBe(true);
      expect(result.channel).toBe('sms');
      expect(result.metric).toBe('disk');
      expect(smsSender).toHaveBeenCalledTimes(1);
    });

    it('should retry on failure and succeed on subsequent attempt', async () => {
      const webhookSender = vi
        .fn()
        .mockRejectedValueOnce(new Error('Network error'))
        .mockResolvedValueOnce(true);

      const monitor = new ResourceMonitor({
        config: {
          notificationChannel: 'webhook',
          notificationTarget: 'https://hooks.example.com/alert',
        },
        webhookSender,
      });

      const result = await monitor.emitAlert('gpu', 85);

      expect(result.success).toBe(true);
      expect(result.retryAttempts).toBe(1);
      expect(webhookSender).toHaveBeenCalledTimes(2);
    });

    it('should fail after exhausting all retry attempts', async () => {
      const webhookSender = vi.fn().mockRejectedValue(new Error('Service down'));

      const monitor = new ResourceMonitor({
        config: {
          notificationChannel: 'webhook',
          notificationTarget: 'https://hooks.example.com/alert',
        },
        webhookSender,
      });

      const result = await monitor.emitAlert('cpu', 99);

      expect(result.success).toBe(false);
      expect(result.error).toBe('Service down');
      expect(result.retryAttempts).toBe(3);
      expect(webhookSender).toHaveBeenCalledTimes(3);
    });

    it('should allow overriding channel per alert call', async () => {
      const smsSender = vi.fn().mockResolvedValue(true);
      const monitor = new ResourceMonitor({
        config: {
          notificationChannel: 'webhook',
          notificationTarget: '+15559876543',
        },
        smsSender,
      });

      const result = await monitor.emitAlert('cpu', 85, 'sms');

      expect(result.success).toBe(true);
      expect(result.channel).toBe('sms');
      expect(smsSender).toHaveBeenCalledTimes(1);
    });

    it('should record alerts in history', async () => {
      const webhookSender = vi.fn().mockResolvedValue(true);
      const monitor = new ResourceMonitor({
        config: {
          notificationChannel: 'webhook',
          notificationTarget: 'https://hooks.example.com/alert',
        },
        webhookSender,
      });

      await monitor.emitAlert('cpu', 85);
      await monitor.emitAlert('memory', 90);

      const history = monitor.getAlertHistory();
      expect(history).toHaveLength(2);
      expect(history[0].metric).toBe('cpu');
      expect(history[1].metric).toBe('memory');
    });
  });

  describe('checkResources', () => {
    it('should collect metrics from all resource providers', async () => {
      const monitor = new ResourceMonitor({
        cpuMetricFn: async () => 55,
        memoryMetricFn: () => 70,
        gpuMetricFn: async () => 40,
        diskMetricFn: async () => 60,
      });

      const metrics = await monitor.checkResources();

      expect(metrics.cpuPercent).toBe(55);
      expect(metrics.memoryPercent).toBe(70);
      expect(metrics.gpuPercent).toBe(40);
      expect(metrics.diskPercent).toBe(60);
      expect(metrics.timestamp).toBeInstanceOf(Date);
    });
  });

  describe('monitorAndAlert', () => {
    it('should emit alerts for breached metrics', async () => {
      const webhookSender = vi.fn().mockResolvedValue(true);
      const monitor = new ResourceMonitor({
        cpuMetricFn: async () => 92,
        memoryMetricFn: () => 50,
        gpuMetricFn: async () => 30,
        diskMetricFn: async () => 85,
        config: {
          notificationChannel: 'webhook',
          notificationTarget: 'https://hooks.example.com/alert',
        },
        webhookSender,
      });

      const results = await monitor.monitorAndAlert();

      expect(results).toHaveLength(2);
      expect(results[0].metric).toBe('cpu');
      expect(results[1].metric).toBe('disk');
      expect(webhookSender).toHaveBeenCalledTimes(2);
    });

    it('should return empty array when no thresholds breached', async () => {
      const webhookSender = vi.fn().mockResolvedValue(true);
      const monitor = new ResourceMonitor({
        cpuMetricFn: async () => 50,
        memoryMetricFn: () => 60,
        gpuMetricFn: async () => 30,
        diskMetricFn: async () => 40,
        config: {
          notificationChannel: 'webhook',
          notificationTarget: 'https://hooks.example.com/alert',
        },
        webhookSender,
      });

      const results = await monitor.monitorAndAlert();

      expect(results).toHaveLength(0);
      expect(webhookSender).not.toHaveBeenCalled();
    });
  });

  describe('getAlertConfig / setAlertConfig', () => {
    it('should return default config when not customized', () => {
      const monitor = new ResourceMonitor();
      const config = monitor.getAlertConfig();

      expect(config.cpuThreshold).toBe(80);
      expect(config.memoryThreshold).toBe(80);
      expect(config.gpuThreshold).toBe(80);
      expect(config.diskThreshold).toBe(80);
      expect(config.notificationChannel).toBe('webhook');
    });

    it('should update config with setAlertConfig', () => {
      const monitor = new ResourceMonitor();

      monitor.setAlertConfig({
        cpuThreshold: 90,
        notificationChannel: 'email',
        notificationTarget: 'admin@example.com',
      });

      const config = monitor.getAlertConfig();
      expect(config.cpuThreshold).toBe(90);
      expect(config.memoryThreshold).toBe(80); // unchanged
      expect(config.notificationChannel).toBe('email');
      expect(config.notificationTarget).toBe('admin@example.com');
    });
  });
});
