/**
 * Encrypted Personal Data Store
 *
 * All personal data (conversations, memories, preferences) is encrypted
 * with AES-256-GCM before being written to disk. Only your password
 * can derive the decryption key.
 */

import { createCipheriv, createDecipheriv, randomBytes, scryptSync } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { DATA_DIR } from './auth';

const CONVERSATIONS_FILE = join(DATA_DIR, 'conversations.enc');
const MEMORIES_FILE = join(DATA_DIR, 'memories.enc');
const PREFS_FILE = join(DATA_DIR, 'preferences.enc');

// Derive encryption key from password using scrypt
let encryptionKey: Buffer | null = null;

function deriveKey(password: string): Buffer {
  const salt = 'jarvis-personal-salt-v1'; // Fixed salt for key derivation consistency
  return scryptSync(password, salt, 32);
}

function setEncryptionKey(password: string): void {
  encryptionKey = deriveKey(password);
}

function getKey(): Buffer {
  if (!encryptionKey) throw new Error('Encryption key not set. Please login first.');
  return encryptionKey;
}

function encrypt(data: string): string {
  const key = getKey();
  const iv = randomBytes(12);
  const cipher = createCipheriv('aes-256-gcm', key, iv);
  const encrypted = Buffer.concat([cipher.update(data, 'utf-8'), cipher.final()]);
  const authTag = cipher.getAuthTag();
  // Format: iv:authTag:ciphertext (all hex)
  return `${iv.toString('hex')}:${authTag.toString('hex')}:${encrypted.toString('hex')}`;
}

function decrypt(encryptedData: string): string {
  const key = getKey();
  const parts = encryptedData.split(':');
  if (parts.length !== 3) throw new Error('Invalid encrypted data format');
  const [ivHex, authTagHex, ciphertextHex] = parts;
  const iv = Buffer.from(ivHex!, 'hex');
  const authTag = Buffer.from(authTagHex!, 'hex');
  const ciphertext = Buffer.from(ciphertextHex!, 'hex');
  const decipher = createDecipheriv('aes-256-gcm', key, iv);
  decipher.setAuthTag(authTag);
  const decrypted = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
  return decrypted.toString('utf-8');
}

// --- Conversation History ---

interface StoredConversation {
  sessionId: string;
  messages: Array<{ role: string; content: string; timestamp: string }>;
}

function saveConversations(conversations: StoredConversation[]): void {
  const data = JSON.stringify(conversations);
  const encrypted = encrypt(data);
  writeFileSync(CONVERSATIONS_FILE, encrypted, 'utf-8');
}

function loadConversations(): StoredConversation[] {
  if (!existsSync(CONVERSATIONS_FILE)) return [];
  try {
    const encrypted = readFileSync(CONVERSATIONS_FILE, 'utf-8');
    const decrypted = decrypt(encrypted);
    return JSON.parse(decrypted);
  } catch {
    return [];
  }
}

// --- Personal Memories (things JARVIS remembers about you) ---

interface Memory {
  id: string;
  content: string;
  category: string;
  createdAt: string;
}

function saveMemories(memories: Memory[]): void {
  const data = JSON.stringify(memories);
  const encrypted = encrypt(data);
  writeFileSync(MEMORIES_FILE, encrypted, 'utf-8');
}

function loadMemories(): Memory[] {
  if (!existsSync(MEMORIES_FILE)) return [];
  try {
    const encrypted = readFileSync(MEMORIES_FILE, 'utf-8');
    const decrypted = decrypt(encrypted);
    return JSON.parse(decrypted);
  } catch {
    return [];
  }
}

function addMemory(content: string, category: string = 'general'): Memory {
  const memories = loadMemories();
  const memory: Memory = {
    id: randomBytes(8).toString('hex'),
    content,
    category,
    createdAt: new Date().toISOString(),
  };
  memories.push(memory);
  saveMemories(memories);
  return memory;
}

function getMemories(): Memory[] {
  return loadMemories();
}

function deleteMemory(id: string): boolean {
  const memories = loadMemories();
  const filtered = memories.filter(m => m.id !== id);
  if (filtered.length === memories.length) return false;
  saveMemories(filtered);
  return true;
}

// --- Preferences ---

interface Preferences {
  name: string;
  voiceSpeed: number;
  voicePitch: number;
  theme: string;
  [key: string]: unknown;
}

function savePreferences(prefs: Preferences): void {
  const data = JSON.stringify(prefs);
  const encrypted = encrypt(data);
  writeFileSync(PREFS_FILE, encrypted, 'utf-8');
}

function loadPreferences(): Preferences {
  if (!existsSync(PREFS_FILE)) {
    return { name: 'User', voiceSpeed: 1.0, voicePitch: 1.1, theme: 'dark' };
  }
  try {
    const encrypted = readFileSync(PREFS_FILE, 'utf-8');
    const decrypted = decrypt(encrypted);
    return JSON.parse(decrypted);
  } catch {
    return { name: 'User', voiceSpeed: 1.0, voicePitch: 1.1, theme: 'dark' };
  }
}

export {
  setEncryptionKey,
  encrypt,
  decrypt,
  saveConversations,
  loadConversations,
  addMemory,
  getMemories,
  deleteMemory,
  savePreferences,
  loadPreferences,
  StoredConversation,
  Memory,
  Preferences,
};
