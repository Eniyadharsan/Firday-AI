import { describe, it, expect, beforeEach } from 'vitest';
import * as crypto from 'node:crypto';
import { SecurityService, EncryptedData } from '../../src/services/security.js';
import {
  ENCRYPTION_KEY_BYTES,
  ENCRYPTION_IV_BYTES,
  ENCRYPTION_AUTH_TAG_BYTES,
  TLS_MIN_VERSION,
  TLS_CIPHERS,
} from '../../src/config/encryption.js';
import type { UserProfile } from '../../src/models/entities.js';

function makeKey(): Buffer {
  return crypto.randomBytes(ENCRYPTION_KEY_BYTES);
}

function makeUserProfile(overrides: Partial<UserProfile> = {}): UserProfile {
  return {
    id: 'user-1',
    voiceConfig: { speed: 1.0, pitch: 1.0, voiceId: 'default' },
    confidenceThreshold: 0.7,
    ragTopK: 5,
    ragRelevanceThreshold: 0.7,
    dataRetentionDays: 30,
    trainingOptIn: false,
    createdAt: new Date(),
    updatedAt: new Date(),
    ...overrides,
  };
}

describe('SecurityService', () => {
  let service: SecurityService;

  beforeEach(() => {
    service = new SecurityService();
  });

  describe('encrypt / decrypt', () => {
    it('should encrypt and decrypt data correctly (round-trip)', () => {
      const key = makeKey();
      const plaintext = Buffer.from('Hello, private world!');

      const encrypted = service.encrypt(plaintext, key);
      const decrypted = service.decrypt(encrypted, key);

      expect(decrypted.toString()).toBe('Hello, private world!');
    });

    it('should produce different ciphertext each time (random IV)', () => {
      const key = makeKey();
      const plaintext = Buffer.from('same data');

      const enc1 = service.encrypt(plaintext, key);
      const enc2 = service.encrypt(plaintext, key);

      expect(enc1.iv.equals(enc2.iv)).toBe(false);
      expect(enc1.ciphertext.equals(enc2.ciphertext)).toBe(false);
    });

    it('should return EncryptedData with ciphertext, iv, and authTag', () => {
      const key = makeKey();
      const plaintext = Buffer.from('test');

      const encrypted = service.encrypt(plaintext, key);

      expect(encrypted.ciphertext).toBeInstanceOf(Buffer);
      expect(encrypted.iv).toBeInstanceOf(Buffer);
      expect(encrypted.authTag).toBeInstanceOf(Buffer);
      expect(encrypted.iv.length).toBe(ENCRYPTION_IV_BYTES);
      expect(encrypted.authTag.length).toBe(ENCRYPTION_AUTH_TAG_BYTES);
    });

    it('should throw on invalid key length for encrypt', () => {
      const shortKey = Buffer.alloc(16); // 128-bit, not 256-bit

      expect(() => service.encrypt(Buffer.from('data'), shortKey)).toThrow(
        /Invalid key length/
      );
    });

    it('should throw on invalid key length for decrypt', () => {
      const shortKey = Buffer.alloc(16);
      const fakeEncrypted: EncryptedData = {
        ciphertext: Buffer.from('x'),
        iv: Buffer.alloc(ENCRYPTION_IV_BYTES),
        authTag: Buffer.alloc(ENCRYPTION_AUTH_TAG_BYTES),
      };

      expect(() => service.decrypt(fakeEncrypted, shortKey)).toThrow(
        /Invalid key length/
      );
    });

    it('should fail decryption with wrong key', () => {
      const key1 = makeKey();
      const key2 = makeKey();
      const plaintext = Buffer.from('secret');

      const encrypted = service.encrypt(plaintext, key1);

      expect(() => service.decrypt(encrypted, key2)).toThrow();
    });

    it('should fail decryption if ciphertext is tampered', () => {
      const key = makeKey();
      const plaintext = Buffer.from('integrity check');

      const encrypted = service.encrypt(plaintext, key);
      // Tamper with the ciphertext
      const tampered = Buffer.from(encrypted.ciphertext);
      tampered[0] ^= 0xff;
      encrypted.ciphertext = tampered;

      expect(() => service.decrypt(encrypted, key)).toThrow();
    });

    it('should handle empty data', () => {
      const key = makeKey();
      const plaintext = Buffer.alloc(0);

      const encrypted = service.encrypt(plaintext, key);
      const decrypted = service.decrypt(encrypted, key);

      expect(decrypted.length).toBe(0);
    });

    it('should handle large data buffers', () => {
      const key = makeKey();
      const plaintext = crypto.randomBytes(1024 * 100); // 100KB

      const encrypted = service.encrypt(plaintext, key);
      const decrypted = service.decrypt(encrypted, key);

      expect(decrypted.equals(plaintext)).toBe(true);
    });
  });

  describe('checkDataAccess', () => {
    it('should allow access when requesting user matches data owner', () => {
      expect(service.checkDataAccess('user-123', 'user-123')).toBe(true);
    });

    it('should deny access when requesting user differs from data owner', () => {
      expect(service.checkDataAccess('user-123', 'user-456')).toBe(false);
    });

    it('should deny access for empty userId', () => {
      expect(service.checkDataAccess('', 'user-123')).toBe(false);
    });

    it('should deny access for empty sessionUserId', () => {
      expect(service.checkDataAccess('user-123', '')).toBe(false);
    });

    it('should deny access when both are empty', () => {
      expect(service.checkDataAccess('', '')).toBe(false);
    });
  });

  describe('deleteUserData', () => {
    it('should return confirmation with all specified items and success flag', async () => {
      service.registerUserData('user-1', ['item-a', 'item-b', 'item-c']);

      const result = await service.deleteUserData('user-1', ['item-a', 'item-b', 'item-c']);

      expect(result.deletedItems).toEqual(['item-a', 'item-b', 'item-c']);
      expect(result.success).toBe(true);
      expect(result.completionTimestamp).toBeInstanceOf(Date);
    });

    it('should return a completion timestamp within expected range', async () => {
      service.registerUserData('user-1', ['item-x']);

      const before = new Date();
      const result = await service.deleteUserData('user-1', ['item-x']);
      const after = new Date();

      expect(result.completionTimestamp.getTime()).toBeGreaterThanOrEqual(before.getTime());
      expect(result.completionTimestamp.getTime()).toBeLessThanOrEqual(after.getTime());
    });

    it('should handle empty item list', async () => {
      const result = await service.deleteUserData('user-1', []);

      expect(result.deletedItems).toEqual([]);
      expect(result.success).toBe(true);
    });

    it('should actually remove items from the data store', async () => {
      service.registerUserData('user-1', ['item-a', 'item-b']);

      expect(service.hasUserData('user-1', 'item-a')).toBe(true);

      await service.deleteUserData('user-1', ['item-a']);

      expect(service.hasUserData('user-1', 'item-a')).toBe(false);
      expect(service.hasUserData('user-1', 'item-b')).toBe(true);
    });

    it('should handle deletion of non-existent items gracefully', async () => {
      const result = await service.deleteUserData('user-1', ['non-existent-item']);

      expect(result.deletedItems).toContain('non-existent-item');
      expect(result.success).toBe(true);
    });
  });

  describe('isTrainingOptInEnabled', () => {
    it('should return true when trainingOptIn is true', () => {
      const profile = makeUserProfile({ id: 'user-1', trainingOptIn: true });
      service.registerUserProfile(profile);

      expect(service.isTrainingOptInEnabled('user-1')).toBe(true);
    });

    it('should return false when trainingOptIn is false', () => {
      const profile = makeUserProfile({ id: 'user-1', trainingOptIn: false });
      service.registerUserProfile(profile);

      expect(service.isTrainingOptInEnabled('user-1')).toBe(false);
    });

    it('should return false when trainingOptIn is default (false)', () => {
      const profile = makeUserProfile({ id: 'user-1' }); // default is false
      service.registerUserProfile(profile);

      expect(service.isTrainingOptInEnabled('user-1')).toBe(false);
    });

    it('should return false for unknown user', () => {
      expect(service.isTrainingOptInEnabled('unknown-user')).toBe(false);
    });
  });

  describe('getTlsConfig', () => {
    it('should return TLS 1.3 minimum version', () => {
      const config = service.getTlsConfig();

      expect(config.minVersion).toBe(TLS_MIN_VERSION);
      expect(config.minVersion).toBe('TLSv1.3');
    });

    it('should return cipher suites joined by colon', () => {
      const config = service.getTlsConfig();

      expect(config.ciphers).toBe(TLS_CIPHERS.join(':'));
      expect(config.ciphers).toContain('TLS_AES_256_GCM_SHA384');
    });

    it('should honor cipher order', () => {
      const config = service.getTlsConfig();

      expect(config.honorCipherOrder).toBe(true);
    });
  });
});
