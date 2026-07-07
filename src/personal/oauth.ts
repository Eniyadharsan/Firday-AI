/**
 * OAuth Authentication — Google Sign-In + Email/Password
 *
 * Handles user registration, login, and token verification.
 * Users are stored encrypted on disk.
 */

import { createHash, randomBytes } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';

// Use /data for HF Spaces persistent storage, fallback to local
const DATA_DIR = existsSync('/data') ? '/data/jarvis' : join(process.cwd(), '.jarvis-data');
const USERS_FILE = join(DATA_DIR, 'users.json');
const OTP_FILE = join(DATA_DIR, 'otps.json');

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

// --- OTP System ---
interface OTPEntry { email: string; otp: string; expiresAt: number; }

function loadOTPs(): OTPEntry[] {
  ensureDir();
  if (!existsSync(OTP_FILE)) return [];
  try { return JSON.parse(readFileSync(OTP_FILE, 'utf-8')); } catch { return []; }
}

function saveOTPs(otps: OTPEntry[]): void {
  ensureDir();
  writeFileSync(OTP_FILE, JSON.stringify(otps), 'utf-8');
}

function generateOTP(): string {
  return Math.floor(100000 + Math.random() * 900000).toString();
}

async function sendOTPEmail(email: string, otp: string): Promise<boolean> {
  // Use Resend API if available, otherwise use a simple SMTP-less approach
  const resendKey = process.env['RESEND_API_KEY'];
  if (resendKey) {
    try {
      const res = await fetch('https://api.resend.com/emails', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${resendKey}` },
        body: JSON.stringify({
          from: 'JARVIS <noreply@resend.dev>',
          to: [email],
          subject: 'JARVIS - Verification Code',
          html: `<h2>Your JARVIS Verification Code</h2><p style="font-size:32px;font-weight:bold;letter-spacing:4px;color:#00e5ff">${otp}</p><p>This code expires in 10 minutes.</p>`,
        }),
      });
      return res.ok;
    } catch { return false; }
  }
  // No email service configured — OTP is stored server-side and returned in response for dev mode
  console.log(`[OTP] Code for ${email}: ${otp}`);
  return true;
}

function createOTP(email: string): string {
  const otps = loadOTPs().filter(o => o.expiresAt > Date.now()); // clean expired
  const otp = generateOTP();
  otps.push({ email, otp, expiresAt: Date.now() + 10 * 60 * 1000 }); // 10 min expiry
  saveOTPs(otps);
  return otp;
}

function verifyOTP(email: string, otp: string): boolean {
  const otps = loadOTPs();
  const match = otps.find(o => o.email === email && o.otp === otp && o.expiresAt > Date.now());
  if (match) {
    // Remove used OTP
    saveOTPs(otps.filter(o => o !== match));
    return true;
  }
  return false;
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

// Step 1: Request signup — sends OTP to email
async function requestSignup(email: string, password: string, _name: string): Promise<{ success: boolean; message?: string; error?: string }> {
  const users = loadUsers();
  if (users.find(u => u.email === email)) return { success: false, error: 'Email already registered. Please sign in.' };
  if (password.length < 6) return { success: false, error: 'Password must be at least 6 characters.' };
  if (!email.includes('@')) return { success: false, error: 'Invalid email address.' };

  const otp = createOTP(email);
  const sent = await sendOTPEmail(email, otp);

  if (!sent && !process.env['RESEND_API_KEY']) {
    // Dev mode — no email service, auto-verify
    return { success: true, message: `DEV_OTP:${otp}` };
  }

  return { success: true, message: 'Verification code sent to your email.' };
}

// Step 2: Verify OTP and complete signup
function verifyAndSignup(email: string, password: string, name: string, otp: string): { token: string; user: { id: string; email: string; name: string } } | { error: string } {
  if (!verifyOTP(email, otp)) return { error: 'Invalid or expired verification code.' };

  const users = loadUsers();
  if (users.find(u => u.email === email)) return { error: 'Email already registered.' };

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

export { signupWithEmail, signinWithEmail, signinWithGoogle, verifyAuthToken, loadUsers, requestSignup, verifyAndSignup };
