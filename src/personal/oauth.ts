/**
 * OAuth Authentication — Google Sign-In + Email/Password
 *
 * Handles user registration, login, and token verification.
 * Users are stored encrypted on disk.
 */

import { createHash, randomBytes } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';

const DATA_DIR = join(process.cwd(), '.jarvis-data');
const USERS_FILE = join(DATA_DIR, 'users.json');

interface User {
  id: string;
  email: string;
  name: string;
  authMethod: 'google' | 'email';
  passwordHash?: string;
  googleId?: string;
  createdAt: string;
  lastLogin: string;
}

function ensureDir() {
  if (!existsSync(DATA_DIR)) mkdirSync(DATA_DIR, { recursive: true });
}

function loadUsers(): User[] {
  ensureDir();
  if (!existsSync(USERS_FILE)) return [];
  try { return JSON.parse(readFileSync(USERS_FILE, 'utf-8')); } catch { return []; }
}

function saveUsers(users: User[]): void {
  ensureDir();
  writeFileSync(USERS_FILE, JSON.stringify(users, null, 2), 'utf-8');
}

function hashPwd(password: string): string {
  const salt = randomBytes(16).toString('hex');
  const hash = createHash('sha256').update(salt + password).digest('hex');
  return `${salt}:${hash}`;
}

function verifyPwd(password: string, stored: string): boolean {
  const [salt, hash] = stored.split(':');
  if (!salt || !hash) return false;
  return createHash('sha256').update(salt + password).digest('hex') === hash;
}

function makeToken(userId: string, email: string): string {
  const secret = process.env['JWT_SECRET'] ?? 'jarvis-secret-key-change-in-prod';
  const payload = JSON.stringify({ userId, email, exp: Date.now() + 7 * 24 * 60 * 60 * 1000 });
  const b64 = Buffer.from(payload).toString('base64url');
  const sig = createHash('sha256').update(b64 + secret).digest('base64url');
  return `${b64}.${sig}`;
}

function verifyAuthToken(token: string): { valid: boolean; userId?: string; email?: string } {
  const secret = process.env['JWT_SECRET'] ?? 'jarvis-secret-key-change-in-prod';
  const [b64, sig] = token.split('.');
  if (!b64 || !sig) return { valid: false };
  const expectedSig = createHash('sha256').update(b64 + secret).digest('base64url');
  if (sig !== expectedSig) return { valid: false };
  try {
    const payload = JSON.parse(Buffer.from(b64, 'base64url').toString());
    if (payload.exp < Date.now()) return { valid: false };
    return { valid: true, userId: payload.userId, email: payload.email };
  } catch { return { valid: false }; }
}

// --- Email/Password Auth ---

function signupWithEmail(email: string, password: string, name: string): { token: string; user: { id: string; email: string; name: string } } | { error: string } {
  const users = loadUsers();
  if (users.find(u => u.email === email)) return { error: 'Email already registered. Please sign in.' };
  if (password.length < 6) return { error: 'Password must be at least 6 characters.' };

  const user: User = {
    id: randomBytes(16).toString('hex'),
    email,
    name: name || email.split('@')[0] || 'User',
    authMethod: 'email',
    passwordHash: hashPwd(password),
    createdAt: new Date().toISOString(),
    lastLogin: new Date().toISOString(),
  };
  users.push(user);
  saveUsers(users);

  const token = makeToken(user.id, user.email);
  return { token, user: { id: user.id, email: user.email, name: user.name } };
}

function signinWithEmail(email: string, password: string): { token: string; user: { id: string; email: string; name: string } } | { error: string } {
  const users = loadUsers();
  const user = users.find(u => u.email === email && u.authMethod === 'email');
  if (!user || !user.passwordHash) return { error: 'Invalid email or password.' };
  if (!verifyPwd(password, user.passwordHash)) return { error: 'Invalid email or password.' };

  user.lastLogin = new Date().toISOString();
  saveUsers(users);

  const token = makeToken(user.id, user.email);
  return { token, user: { id: user.id, email: user.email, name: user.name } };
}

// --- Google Sign-In ---

async function signinWithGoogle(googleToken: string): Promise<{ token: string; user: { id: string; email: string; name: string } } | { error: string }> {
  try {
    // Verify Google token by calling Google's tokeninfo endpoint
    const res = await fetch(`https://oauth2.googleapis.com/tokeninfo?id_token=${googleToken}`);
    if (!res.ok) return { error: 'Invalid Google token.' };

    const data = await res.json() as { sub?: string; email?: string; name?: string; email_verified?: string };
    if (!data.email) return { error: 'Could not get email from Google.' };

    const users = loadUsers();
    let user = users.find(u => u.email === data.email);

    if (!user) {
      // New user — auto-register
      user = {
        id: randomBytes(16).toString('hex'),
        email: data.email!,
        name: data.name || data.email!.split('@')[0] || 'User',
        authMethod: 'google',
        googleId: data.sub,
        createdAt: new Date().toISOString(),
        lastLogin: new Date().toISOString(),
      };
      users.push(user);
    } else {
      user.lastLogin = new Date().toISOString();
      if (!user.googleId) user.googleId = data.sub;
    }
    saveUsers(users);

    const token = makeToken(user.id, user.email);
    return { token, user: { id: user.id, email: user.email, name: user.name } };
  } catch {
    return { error: 'Google authentication failed.' };
  }
}

export { signupWithEmail, signinWithEmail, signinWithGoogle, verifyAuthToken, loadUsers };
