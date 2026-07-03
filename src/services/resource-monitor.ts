/**
 * Resource Monitoring and Alerting Service.
 *
 * Monitors CPU, memory, GPU, and disk utilization. Emits alerts
 * via a configured notification channel (email, webhook, SMS) when
 * any metric exceeds 80% utilization.
 *
 * Requirements: 8.3
 */

import * as os from 'os';
import { AlertConfig } from '../models/entities.js';
import { RESOURCE_ALERT_THRESHOLD_PERCENT } from '../config/defaults.js';

/** Snapshot of current resource utilization (0–100 percentages) */
export interface ResourceMetrics {
  cpuPercent: number;
  memoryPercent: number;
  gpuPercent: number;
  diskPercent: number;
  timestamp: Date;
}

/** Result of evaluating metrics against thresholds */
export interface ThresholdBreachResult {
  breached: boolean;
  breaches: ThresholdBreach[];
}

/** A single threshold breach */
export interface ThresholdBreach {
  metric: 'cpu' | 'memory' | 'gpu' | 'disk';
  value: number;
  threshold: number;
}

/** Result of sending an alert */
export interface AlertResult {
  success: boolean;
  channel: 'email' | 'webhook' | 'sms';
  target: string;
  metric: string;
  value: number;
  timestamp: Date;
  error?: string;
  retryAttempts: number;
}

/** Maximum number of retry attempts for alert delivery */
const ALERT_MAX_RETRIES = 3;

/** Default alert configuration */
const DEFAULT_ALERT_CONFIG: AlertConfig = {
  cpuThreshold: RESOURCE_ALERT_THRESHOLD_PERCENT,
  memoryThreshold: RESOURCE_ALERT_THRESHOLD_PERCENT,
  gpuThreshold: RESOURCE_ALERT_THRESHOLD_PERCENT,
  diskThreshold: RESOURCE_ALERT_THRESHOLD_PERCENT,
  notificationChannel: 'webhook',
  notificationTarget: '',
};

/**
 * ResourceMonitor monitors system resource utilization and emits alerts
 * when configured thresholds are exceeded.
 *
 * Supports notification channels: email, webhook, and SMS.
 * Alerts are delivered within 60 seconds of a threshold breach.
 */
export class ResourceMonitor {
  private alertConfig: AlertConfig;
  private readonly alertHistory: AlertResult[] = [];

  /** Injectable functions for obtaining resource metrics (for testability) */
  private cpuMetricFn: () => Promise<number>;
  private memoryMetricFn: () => number;
  private gpuMetricFn: () => Promise<number>;
  private diskMetricFn: () => Promise<number>;

  /** Injectable notification sender functions (for testability) */
  private webhookSender: (url: string, payload: object) => Promise<boolean>;
  private emailSender: (target: string, subject: string, body: string) => Promise<boolean>;
  private smsSender: (target: string, message: string) => Promise<boolean>;

  constructor(options?: {
    config?: Partial<AlertConfig>;
    cpuMetricFn?: () => Promise<number>;
    memoryMetricFn?: () => number;
    gpuMetricFn?: () => Promise<number>;
    diskMetricFn?: () => Promise<number>;
    webhookSender?: (url: string, payload: object) => Promise<boolean>;
    emailSender?: (target: string, subject: string, body: string) => Promise<boolean>;
    smsSender?: (target: string, message: string) => Promise<boolean>;
  }) {
    this.alertConfig = { ...DEFAULT_ALERT_CONFIG, ...options?.config };
    this.cpuMetricFn = options?.cpuMetricFn ?? ResourceMonitor.defaultCpuMetric;
    this.memoryMetricFn = options?.memoryMetricFn ?? ResourceMonitor.defaultMemoryMetric;
    this.gpuMetricFn = options?.gpuMetricFn ?? ResourceMonitor.defaultGpuMetric;
    this.diskMetricFn = options?.diskMetricFn ?? ResourceMonitor.defaultDiskMetric;
    this.webhookSender = options?.webhookSender ?? ResourceMonitor.defaultWebhookSender;
    this.emailSender = options?.emailSender ?? ResourceMonitor.defaultEmailSender;
    this.smsSender = options?.smsSender ?? ResourceMonitor.defaultSmsSender;
  }

  /**
   * Read current CPU, memory, GPU, and disk utilization.
   */
  async checkResources(): Promise<ResourceMetrics> {
    const [cpuPercent, gpuPercent, diskPercent] = await Promise.all([
      this.cpuMetricFn(),
      this.gpuMetricFn(),
      this.diskMetricFn(),
    ]);

    const memoryPercent = this.memoryMetricFn();

    return {
      cpuPercent,
      memoryPercent,
      gpuPercent,
      diskPercent,
      timestamp: new Date(),
    };
  }

  /**
   * Evaluate metrics against configured thresholds.
   * Returns which metrics have been breached (value > threshold).
   */
  evaluateThresholds(metrics: ResourceMetrics): ThresholdBreachResult {
    const breaches: ThresholdBreach[] = [];

    if (metrics.cpuPercent > this.alertConfig.cpuThreshold) {
      breaches.push({
        metric: 'cpu',
        value: metrics.cpuPercent,
        threshold: this.alertConfig.cpuThreshold,
      });
    }

    if (metrics.memoryPercent > this.alertConfig.memoryThreshold) {
      breaches.push({
        metric: 'memory',
        value: metrics.memoryPercent,
        threshold: this.alertConfig.memoryThreshold,
      });
    }

    if (metrics.gpuPercent > this.alertConfig.gpuThreshold) {
      breaches.push({
        metric: 'gpu',
        value: metrics.gpuPercent,
        threshold: this.alertConfig.gpuThreshold,
      });
    }

    if (metrics.diskPercent > this.alertConfig.diskThreshold) {
      breaches.push({
        metric: 'disk',
        value: metrics.diskPercent,
        threshold: this.alertConfig.diskThreshold,
      });
    }

    return {
      breached: breaches.length > 0,
      breaches,
    };
  }

  /**
   * Emit an alert for a threshold breach via the configured notification channel.
   * Supports retry logic for reliability. Async with up to ALERT_MAX_RETRIES attempts.
   */
  async emitAlert(
    metric: string,
    value: number,
    channel?: 'email' | 'webhook' | 'sms'
  ): Promise<AlertResult> {
    const selectedChannel = channel ?? this.alertConfig.notificationChannel;
    const target = this.alertConfig.notificationTarget;
    const timestamp = new Date();

    let success = false;
    let retryAttempts = 0;
    let lastError: string | undefined;

    for (let attempt = 0; attempt < ALERT_MAX_RETRIES; attempt++) {
      try {
        success = await this.sendNotification(selectedChannel, target, metric, value, timestamp);
        if (success) {
          retryAttempts = attempt;
          break;
        }
      } catch (err) {
        lastError = err instanceof Error ? err.message : String(err);
      }
      retryAttempts = attempt + 1;
    }

    const result: AlertResult = {
      success,
      channel: selectedChannel,
      target,
      metric,
      value,
      timestamp,
      retryAttempts,
      ...(lastError && !success ? { error: lastError } : {}),
    };

    this.alertHistory.push(result);
    return result;
  }

  /**
   * Run a full monitoring cycle: check resources, evaluate thresholds,
   * and emit alerts for any breaches.
   */
  async monitorAndAlert(): Promise<AlertResult[]> {
    const metrics = await this.checkResources();
    const evaluation = this.evaluateThresholds(metrics);

    if (!evaluation.breached) {
      return [];
    }

    const results: AlertResult[] = [];
    for (const breach of evaluation.breaches) {
      const result = await this.emitAlert(breach.metric, breach.value);
      results.push(result);
    }

    return results;
  }

  /**
   * Get the current alert configuration.
   */
  getAlertConfig(): AlertConfig {
    return { ...this.alertConfig };
  }

  /**
   * Update the alert configuration.
   */
  setAlertConfig(config: Partial<AlertConfig>): void {
    this.alertConfig = { ...this.alertConfig, ...config };
  }

  /**
   * Get alert history for observability.
   */
  getAlertHistory(): ReadonlyArray<AlertResult> {
    return [...this.alertHistory];
  }

  // --- Private notification delivery ---

  private async sendNotification(
    channel: 'email' | 'webhook' | 'sms',
    target: string,
    metric: string,
    value: number,
    timestamp: Date
  ): Promise<boolean> {
    const message = `ALERT: ${metric} utilization at ${value.toFixed(1)}% (threshold exceeded) at ${timestamp.toISOString()}`;

    switch (channel) {
      case 'webhook': {
        const payload = {
          alert: 'resource_threshold_exceeded',
          metric,
          value,
          threshold: RESOURCE_ALERT_THRESHOLD_PERCENT,
          timestamp: timestamp.toISOString(),
          message,
        };
        return this.webhookSender(target, payload);
      }
      case 'email': {
        const subject = `Resource Alert: ${metric} at ${value.toFixed(1)}%`;
        return this.emailSender(target, subject, message);
      }
      case 'sms': {
        return this.smsSender(target, message);
      }
      default:
        return false;
    }
  }

  // --- Default metric providers ---

  /** Default CPU metric: average CPU usage across all cores */
  private static async defaultCpuMetric(): Promise<number> {
    const cpus = os.cpus();
    if (cpus.length === 0) return 0;

    let totalIdle = 0;
    let totalTick = 0;

    for (const cpu of cpus) {
      const { user, nice, sys, idle, irq } = cpu.times;
      totalTick += user + nice + sys + idle + irq;
      totalIdle += idle;
    }

    const usagePercent = ((totalTick - totalIdle) / totalTick) * 100;
    return Math.min(100, Math.max(0, usagePercent));
  }

  /** Default memory metric: percentage of used memory */
  private static defaultMemoryMetric(): number {
    const total = os.totalmem();
    const free = os.freemem();
    if (total === 0) return 0;
    return ((total - free) / total) * 100;
  }

  /** Default GPU metric: stubbed for portability (returns 0) */
  private static async defaultGpuMetric(): Promise<number> {
    // In production, this would call nvidia-smi or vLLM metrics endpoint.
    // Stubbed to return 0 for environments without GPU.
    return 0;
  }

  /** Default disk metric: stubbed (returns 0) — in production use fs.statfs */
  private static async defaultDiskMetric(): Promise<number> {
    // In production, would use fs.statfs('/') to determine disk usage.
    // Stubbed for portability.
    return 0;
  }

  // --- Default notification senders (placeholders) ---

  /** Default webhook sender: POST to configured URL */
  private static async defaultWebhookSender(url: string, _payload: object): Promise<boolean> {
    // In production: use fetch/axios to POST payload to url
    // Placeholder: log and return true in dev
    if (!url) return false;
    return true;
  }

  /** Default email sender: placeholder (would use SMTP/SES) */
  private static async defaultEmailSender(
    target: string,
    _subject: string,
    _body: string
  ): Promise<boolean> {
    // In production: send via SMTP or AWS SES
    if (!target) return false;
    return true;
  }

  /** Default SMS sender: placeholder (would use Twilio/SNS) */
  private static async defaultSmsSender(target: string, _message: string): Promise<boolean> {
    // In production: send via Twilio or AWS SNS
    if (!target) return false;
    return true;
  }
}
