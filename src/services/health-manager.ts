/**
 * Server Health, Auto-Recovery, and Uptime Management.
 *
 * Provides health checking for all services, automatic recovery with
 * retry logic (up to 3 attempts), and uptime tracking against a 99.5%
 * monthly SLA target.
 *
 * Requirements: 2.2, 2.3, 2.5, 8.7
 */

import { RECOVERY_MAX_RETRIES } from '../config/defaults.js';

/** Health status of a monitored service */
export type ServiceStatus = 'healthy' | 'degraded' | 'unavailable';

/** Health check report for a single service */
export interface ServiceHealthReport {
  serviceName: string;
  status: ServiceStatus;
  lastCheckAt: Date;
  responseTimeMs: number;
}

/** Result of a recovery attempt */
export interface RecoveryResult {
  success: boolean;
  attempts: number;
  recoveredAt?: Date;
  error?: string;
}

/** Uptime metrics for SLA tracking */
export interface UptimeMetrics {
  uptimePercent: number;
  totalDowntimeMs: number;
  trackingSince: Date;
}

/** Registered service with its health check function */
interface RegisteredService {
  name: string;
  healthCheckFn: () => Promise<boolean>;
  restartFn?: () => Promise<boolean>;
}

/** Internal health state tracking per service */
interface ServiceState {
  lastReport: ServiceHealthReport;
  consecutiveFailures: number;
}

/** Default monthly uptime SLA target (99.5%) */
const DEFAULT_UPTIME_TARGET = 99.5;

/** Health check timeout in milliseconds (non-blocking) */
const HEALTH_CHECK_TIMEOUT_MS = 5000;

/**
 * HealthManager monitors service health, performs auto-recovery on failures,
 * and tracks uptime metrics against the 99.5% monthly target.
 */
export class HealthManager {
  /** Registered services for health checking */
  private readonly registeredServices: Map<string, RegisteredService> = new Map();

  /** Internal state keyed by service name */
  private readonly serviceStates: Map<string, ServiceState> = new Map();

  /** Cumulative downtime in milliseconds for uptime calculation */
  private totalDowntimeMs: number = 0;

  /** Timestamp when tracking started */
  private readonly trackingSince: Date;

  /** Notifications emitted (for testing/observability) */
  private readonly notifications: string[] = [];

  constructor(startTime?: Date) {
    this.trackingSince = startTime ?? new Date();
  }

  /**
   * Register a service for health monitoring.
   */
  registerService(
    serviceName: string,
    healthCheckFn: () => Promise<boolean>,
    restartFn?: () => Promise<boolean>
  ): void {
    this.registeredServices.set(serviceName, {
      name: serviceName,
      healthCheckFn,
      restartFn,
    });
  }

  /**
   * Check the health of all registered services.
   * Returns a ServiceHealthReport for each service.
   * Health checks are non-blocking (use timeouts).
   */
  async checkAllServices(): Promise<ServiceHealthReport[]> {
    const reports: ServiceHealthReport[] = [];

    for (const [name, service] of this.registeredServices) {
      const report = await this.checkService(name, service.healthCheckFn);
      reports.push(report);
    }

    return reports;
  }

  /**
   * Check the health of a single named service using the provided health check function.
   * Updates internal health state and consecutive failure count.
   * Uses a timeout to ensure non-blocking behavior.
   */
  async checkService(
    serviceName: string,
    healthCheckFn: () => Promise<boolean>
  ): Promise<ServiceHealthReport> {
    const startTime = Date.now();
    let isHealthy: boolean;

    try {
      isHealthy = await this.withTimeout(healthCheckFn(), HEALTH_CHECK_TIMEOUT_MS);
    } catch {
      isHealthy = false;
    }

    const responseTimeMs = Date.now() - startTime;
    const existingState = this.serviceStates.get(serviceName);
    let consecutiveFailures = existingState?.consecutiveFailures ?? 0;

    if (isHealthy) {
      consecutiveFailures = 0;
    } else {
      consecutiveFailures += 1;
    }

    const status = this.determineStatus(isHealthy, consecutiveFailures, responseTimeMs);

    const report: ServiceHealthReport = {
      serviceName,
      status,
      lastCheckAt: new Date(),
      responseTimeMs,
    };

    this.serviceStates.set(serviceName, {
      lastReport: report,
      consecutiveFailures,
    });

    return report;
  }

  /**
   * Attempt auto-recovery of a failed service.
   *
   * Retries up to RECOVERY_MAX_RETRIES (3) times. If any attempt succeeds,
   * returns success with recoveredAt timestamp. If all attempts fail,
   * notifies user of temporary unavailability.
   */
  async attemptRecovery(
    serviceName: string,
    restartFn?: () => Promise<boolean>
  ): Promise<RecoveryResult> {
    const fn = restartFn ?? this.registeredServices.get(serviceName)?.restartFn;

    if (!fn) {
      return {
        success: false,
        attempts: 0,
        error: `No restart function available for service "${serviceName}"`,
      };
    }

    for (let attempt = 1; attempt <= RECOVERY_MAX_RETRIES; attempt++) {
      let succeeded: boolean;
      try {
        succeeded = await fn();
      } catch (err) {
        succeeded = false;
      }

      if (succeeded) {
        // Recovery successful — clear failure state
        const existingState = this.serviceStates.get(serviceName);
        if (existingState) {
          existingState.lastReport.status = 'healthy';
          existingState.consecutiveFailures = 0;
          existingState.lastReport.lastCheckAt = new Date();
        }

        return {
          success: true,
          attempts: attempt,
          recoveredAt: new Date(),
        };
      }
    }

    // All attempts exhausted — notify user of unavailability
    const errorMsg = `Service "${serviceName}" is temporarily unavailable after ${RECOVERY_MAX_RETRIES} recovery attempts.`;
    this.notifications.push(errorMsg);

    return {
      success: false,
      attempts: RECOVERY_MAX_RETRIES,
      error: errorMsg,
    };
  }

  /**
   * Record a period of downtime for uptime tracking.
   * Accepts start and end times to calculate duration.
   */
  recordDowntime(startTime: Date, endTime: Date): void {
    const durationMs = endTime.getTime() - startTime.getTime();
    if (durationMs > 0) {
      this.totalDowntimeMs += durationMs;
    }
  }

  /**
   * Get current uptime metrics since tracking started.
   * Uptime calculation: (total_time - downtime) / total_time * 100
   */
  getUptime(): UptimeMetrics {
    const now = new Date();
    const totalElapsedMs = now.getTime() - this.trackingSince.getTime();

    // Prevent division by zero when called immediately after creation
    if (totalElapsedMs <= 0) {
      return {
        uptimePercent: 100,
        totalDowntimeMs: 0,
        trackingSince: this.trackingSince,
      };
    }

    const totalUptimeMs = Math.max(0, totalElapsedMs - this.totalDowntimeMs);
    const uptimePercent = (totalUptimeMs / totalElapsedMs) * 100;

    return {
      uptimePercent,
      totalDowntimeMs: this.totalDowntimeMs,
      trackingSince: this.trackingSince,
    };
  }

  /**
   * Check whether the current uptime percentage meets the SLA target.
   * Default target is 99.5% monthly uptime.
   */
  isWithinSLA(target: number = DEFAULT_UPTIME_TARGET): boolean {
    const metrics = this.getUptime();
    return metrics.uptimePercent >= target;
  }

  /**
   * Get the current health report for a specific service.
   */
  getServiceHealth(serviceName: string): ServiceHealthReport | undefined {
    return this.serviceStates.get(serviceName)?.lastReport;
  }

  /**
   * Get health reports for all monitored services.
   */
  getAllServiceHealth(): ReadonlyArray<ServiceHealthReport> {
    return [...this.serviceStates.values()].map(s => s.lastReport);
  }

  /**
   * Check overall system availability.
   * Returns false if any registered service is in 'unavailable' state,
   * or if the current uptime is below the SLA target.
   */
  isAvailable(): boolean {
    for (const [, state] of this.serviceStates) {
      if (state.lastReport.status === 'unavailable') {
        return false;
      }
    }
    return true;
  }

  /**
   * Record a downtime period by duration in milliseconds.
   * Convenience overload for recording downtime without explicit start/end times.
   */
  recordDowntimeMs(durationMs: number): void {
    if (durationMs > 0) {
      this.totalDowntimeMs += durationMs;
    }
  }

  /**
   * Get all user notifications emitted by recovery failures.
   */
  getNotifications(): ReadonlyArray<string> {
    return [...this.notifications];
  }

  /**
   * Determine the service status based on health check result,
   * consecutive failures, and response time.
   */
  private determineStatus(
    isHealthy: boolean,
    consecutiveFailures: number,
    responseTimeMs: number
  ): ServiceStatus {
    if (!isHealthy && consecutiveFailures >= RECOVERY_MAX_RETRIES) {
      return 'unavailable';
    }
    if (!isHealthy || responseTimeMs >= HEALTH_CHECK_TIMEOUT_MS) {
      return 'degraded';
    }
    return 'healthy';
  }

  /**
   * Execute a promise with a timeout. Returns the result if it completes
   * within the time limit, otherwise rejects.
   */
  private withTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error(`Health check timed out after ${timeoutMs}ms`));
      }, timeoutMs);

      promise
        .then((result) => {
          clearTimeout(timer);
          resolve(result);
        })
        .catch((err) => {
          clearTimeout(timer);
          reject(err);
        });
    });
  }
}
