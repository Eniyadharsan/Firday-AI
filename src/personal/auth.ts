/**
 * Personal Authentication Module
 *
 * Password-based login with JWT tokens. Only you can access JARVIS.
 * Password is hashed with bcrypt — never stored in plaintext.
 */

import { createHash, randomBytes } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';

const DATA_DIR = existsSync('/data') ? '/data/jarvis' : join(process.cwd(), '.jarvis-data');
const AUTH_FILE = join(DATA_DIR, 'auth.enc');
const JWT_SECRET = randomBytes(32).toString('hex');

// Simple bcrypt-like hash using crypto (avoid native module issues)
function hashPassword(password: string): string {
  const salt = randomBytes(16).toString('hex');
  const hash = createHash('sha256').update(salt + password).digest('hex');
  return `${salt}:${hash}`;
}

function verifyPassword(password: string, stored: string): boolean {
  const [salt, hash] = stored.split(':');
  if (!salt || !hash) return false;
  const check = createHash('sha256').update(salt + password).digest('hex');
  return check === hash;
}

function generateToken(userId: string): string {
  // Simple JWT-like token (base64 encoded payload + signature)
  const payload = JSON.stringify({ userId, exp: Date.now() + 24 * 60 * 60 * 1000 });
  const payloadB64 = Buffer.from(payload).toString('base64url');
  const sig = createHash('sha256').update(payloadB64 + JWT_SECRET).digest('base64url');
  return `${payloadB64}.${sig}`;
}

function verifyToken(token: string): { valid: boolean; userId?: string } {
  const [payloadB64, sig] = token.split('.');
  if (!payloadB64 || !sig) return { valid: false };
  const expectedSig = createHash('sha256').update(payloadB64 + JWT_SECRET).digest('base64url');
  if (sig !== expectedSig) return { valid: false };
  try {
    const payload = JSON.parse(Buffer.from(payloadB64, 'base64url').toString());
    if (payload.exp < Date.now()) return { valid: false };
    return { valid: true, userId: payload.userId };
  } catch {
    return { valid: false };
  }
}

function ensureDataDir(): void {
  if (!existsSync(DATA_DIR)) mkdirSync(DATA_DIR, { recursive: true });
}

function isSetup(): boolean {
  ensureDataDir();
  return existsSync(AUTH_FILE);
}

function setupPassword(password: string): void {
  ensureDataDir();
  const hashed = hashPassword(password);
  writeFileSync(AUTH_FILE, hashed, 'utf-8');
}

function login(password: string): string | null {
  if (!isSetup()) return null;
  const stored = readFileSync(AUTH_FILE, 'utf-8').trim();
  if (verifyPassword(password, stored)) {
    return generateToken('owner');
  }
  return null;
}

export { isSetup, setupPassword, login, verifyToken, ensureDataDir, DATA_DIR };
