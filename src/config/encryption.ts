/**
 * Encryption configuration constants for the Personal AI Assistant.
 *
 * Defines encryption standards for data at rest and data in transit
 * as specified in Requirement 8.4 (Cloud Deployment) and Requirement 9 (Privacy).
 */

// --- Encryption at Rest ---

/** Encryption algorithm used for data at rest */
export const ENCRYPTION_ALGORITHM: string = 'aes-256-gcm';

/** Encryption key length in bits */
export const ENCRYPTION_KEY_BITS: number = 256;

/** Encryption key length in bytes */
export const ENCRYPTION_KEY_BYTES: number = 32;

/** AES-GCM initialization vector length in bytes */
export const ENCRYPTION_IV_BYTES: number = 12;

/** AES-GCM authentication tag length in bytes */
export const ENCRYPTION_AUTH_TAG_BYTES: number = 16;

// --- Encryption in Transit ---

/** Minimum TLS protocol version for all communications */
export const TLS_MIN_VERSION: string = 'TLSv1.3';

/** Preferred TLS cipher suites for TLS 1.3 */
export const TLS_CIPHERS: readonly string[] = [
  'TLS_AES_256_GCM_SHA384',
  'TLS_CHACHA20_POLY1305_SHA256',
  'TLS_AES_128_GCM_SHA256',
] as const;

// --- General Encryption Settings ---

/** Whether to enforce encryption for all stored data */
export const ENFORCE_ENCRYPTION_AT_REST: boolean = true;

/** Whether to enforce TLS for all network communication */
export const ENFORCE_TLS_IN_TRANSIT: boolean = true;

/** PBKDF2 iteration count for key derivation */
export const KEY_DERIVATION_ITERATIONS: number = 100_000;

/** Hash algorithm used for key derivation */
export const KEY_DERIVATION_HASH: string = 'sha512';

/** Salt length in bytes for key derivation */
export const KEY_DERIVATION_SALT_BYTES: number = 32;
