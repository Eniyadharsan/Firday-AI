/**
 * Local Runner — runs the Personal AI Assistant on your machine
 * without Docker, GPU, or external infrastructure.
 *
 * Uses:
 * - Groq API (free tier) for LLM inference (Mistral/LLaMA)
 * - Edge TTS (Microsoft) for text-to-speech (no GPU needed)
 * - Encrypted personal data store (AES-256-GCM)
 * - Password-protected access (only you can use it)
 *
 * Start: npx ts-node src/local-runner.ts
 */

import express from 'express';
import { exec } from 'child_process';
import { mkdirSync, existsSync } from 'fs';
import { join } from 'path';
import { isSetup, setupPassword, login, verifyToken } from './personal/auth';
import {
  setEncryptionKey,
  saveConversations,
  loadConversations,
  addMemory,
  getMemories,
  deleteMemory,
  savePreferences,
  loadPreferences,
} from './personal/encrypted-store';

const app = express();
app.use(express.json());

// Serve static files (PWA assets, icons, manifest, service worker)
app.use(express.static(join(process.cwd(), 'public')));

const PORT = 3000;
const GROQ_API_KEY = process.env['GROQ_API_KEY'] ?? '';

// --- In-Memory Session Store ---
interface LocalSession {
  id: string;
  history: Array<{ role: string; content: string }>;
  createdAt: Date;
}

const sessions = new Map<string, LocalSession>();

// --- In-Memory Knowledge Store (reserved for future use) ---
// const knowledgeItems: Array<{ content: string; metadata: Record<string, string> }> = [];

// --- Groq LLM Client ---
async function generateWithGroq(
  messages: Array<{ role: string; content: string }>,
): Promise<string> {
  if (!GROQ_API_KEY) {
    return "I'm running in demo mode without an LLM. Set GROQ_API_KEY environment variable with a free key from https://console.groq.com to enable AI responses.";
  }

  const response = await fetch('https://api.groq.com/openai/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${GROQ_API_KEY}`,
    },
    body: JSON.stringify({
      model: 'llama-3.1-8b-instant',
      messages,
      max_tokens: 1024,
      temperature: 0.7,
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Groq API error ${response.status}: ${errorText}`);
  }

  const data = await response.json() as {
    choices?: Array<{ message?: { content?: string } }>;
  };

  return data.choices?.[0]?.message?.content ?? 'No response generated.';
}

// --- Edge TTS ---
async function textToSpeech(text: string, outputPath: string): Promise<void> {
  const escapedText = text.replace(/"/g, '\\"').replace(/\n/g, ' ');
  const cmd = `edge-tts --text "${escapedText}" --write-media "${outputPath}" --voice "en-US-GuyNeural"`;

  return new Promise((resolve, reject) => {
    exec(cmd, { timeout: 30000 }, (error) => {
      if (error) reject(error);
      else resolve();
    });
  });
}

// --- Routes ---

// Health check
app.get('/health', (_req, res) => {
  res.json({
    status: 'running',
    mode: 'local (CPU)',
    llm: GROQ_API_KEY ? 'Groq API (LLaMA-3.1-8B)' : 'Demo mode (no API key)',
    tts: 'Browser Speech Synthesis',
    encryption: 'AES-256-GCM',
    auth: isSetup() ? 'protected' : 'needs setup',
    sessions: sessions.size,
    timestamp: new Date().toISOString(),
  });
});

// --- Auth Endpoints ---

// Setup password (first time only)
app.post('/auth/setup', (req, res) => {
  if (isSetup()) {
    res.status(400).json({ error: 'Already set up. Use /auth/login instead.' });
    return;
  }
  const { password } = req.body;
  if (!password || password.length < 6) {
    res.status(400).json({ error: 'Password must be at least 6 characters.' });
    return;
  }
  setupPassword(password);
  const token = login(password);
  if (token) setEncryptionKey(password);
  res.json({ success: true, token, message: 'JARVIS is now protected. Only you can access it.' });
});

// Login
app.post('/auth/login', (req, res) => {
  if (!isSetup()) {
    res.status(400).json({ error: 'Not set up yet. Use /auth/setup first.' });
    return;
  }
  const { password } = req.body;
  const token = login(password);
  if (!token) {
    res.status(401).json({ error: 'Invalid password.' });
    return;
  }
  setEncryptionKey(password);
  res.json({ success: true, token });
});

// Check if setup is needed
app.get('/auth/status', (_req, res) => {
  res.json({ needsSetup: !isSetup() });
});

// Auth middleware for protected routes
function requireAuth(req: express.Request, res: express.Response, next: express.NextFunction): void {
  const authHeader = req.headers['authorization'];
  const token = authHeader?.replace('Bearer ', '');
  if (!token) {
    res.status(401).json({ error: 'Authentication required.' });
    return;
  }
  const result = verifyToken(token);
  if (!result.valid) {
    res.status(401).json({ error: 'Invalid or expired token.' });
    return;
  }
  next();
}

// --- Personal Memory Endpoints (protected) ---

app.get('/memories', requireAuth, (_req, res) => {
  const memories = getMemories();
  res.json({ memories });
});

app.post('/memories', requireAuth, (req, res) => {
  const { content, category } = req.body;
  if (!content) { res.status(400).json({ error: 'content is required' }); return; }
  const memory = addMemory(content, category ?? 'general');
  res.json({ success: true, memory });
});

app.delete('/memories/:id', requireAuth, (req, res) => {
  const deleted = deleteMemory(req.params['id'] ?? '');
  res.json({ success: deleted });
});

// --- Preferences Endpoints (protected) ---

app.get('/preferences', requireAuth, (_req, res) => {
  const prefs = loadPreferences();
  res.json(prefs);
});

app.post('/preferences', requireAuth, (req, res) => {
  const current = loadPreferences();
  const updated = { ...current, ...req.body };
  savePreferences(updated);
  res.json({ success: true, preferences: updated });
});

// Chat endpoint
app.post('/chat', async (req, res) => {
  try {
    const { message, sessionId } = req.body;

    if (!message) {
      res.status(400).json({ error: 'message is required' });
      return;
    }

    // Get or create session
    const sid = sessionId ?? `session-${Date.now()}`;
    if (!sessions.has(sid)) {
      sessions.set(sid, {
        id: sid,
        history: [{
          role: 'system',
          content: `You are JARVIS, a personal AI assistant. You are helpful, knowledgeable, and speak concisely. You were built by your owner as a personal AI system. Current date: ${new Date().toLocaleDateString()}. When the user asks you to play a song or music, respond ONLY with: [PLAY_MUSIC:song name - artist] and nothing else. For example if they say "play talking to the moon" respond with [PLAY_MUSIC:Talking to the Moon - Bruno Mars]. Do not read lyrics or describe songs.`
        }],
        createdAt: new Date(),
      });
    }

    const session = sessions.get(sid)!;

    // Add user message to history
    session.history.push({ role: 'user', content: message });

    // Generate response
    const reply = await generateWithGroq(session.history);

    // Add assistant reply to history
    session.history.push({ role: 'assistant', content: reply });

    // Check if response is a music play command
    const musicMatch = reply.match(/\[PLAY_MUSIC:(.+?)\]/);
    if (musicMatch) {
      const songQuery = musicMatch[1]!.trim();
      const youtubeSearchUrl = `https://www.youtube.com/results?search_query=${encodeURIComponent(songQuery)}`;

      res.json({
        reply: `Playing "${songQuery}" for you...`,
        sessionId: sid,
        timestamp: new Date().toISOString(),
        action: 'play_music',
        musicUrl: youtubeSearchUrl,
        songQuery,
      });
      return;
    }

    // Keep history manageable (last 50 exchanges)
    if (session.history.length > 102) {
      session.history = [session.history[0]!, ...session.history.slice(-100)];
    }

    // Save conversation encrypted to disk
    try {
      const convos = loadConversations();
      const existing = convos.find(c => c.sessionId === sid);
      if (existing) {
        existing.messages = session.history.map(m => ({ ...m, timestamp: new Date().toISOString() }));
      } else {
        convos.push({ sessionId: sid, messages: session.history.map(m => ({ ...m, timestamp: new Date().toISOString() })) });
      }
      // Keep only last 20 conversations
      if (convos.length > 20) convos.splice(0, convos.length - 20);
      saveConversations(convos);
    } catch { /* encryption key not set — skip save */ }

    // Check if user asked JARVIS to remember something
    const lowerMsg = message.toLowerCase();
    if (lowerMsg.includes('remember') || lowerMsg.includes('my name is') || lowerMsg.includes('i like') || lowerMsg.includes('i prefer')) {
      try { addMemory(message, 'user-stated'); } catch { /* skip if not logged in */ }
    }

    res.json({
      reply,
      sessionId: sid,
      timestamp: new Date().toISOString(),
    });
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'Unknown error';
    console.error('[Chat Error]', msg);
    res.status(500).json({ error: msg });
  }
});

// Text-to-Speech endpoint
app.post('/speak', async (req, res) => {
  try {
    const { text } = req.body;
    if (!text) {
      res.status(400).json({ error: 'text is required' });
      return;
    }

    const audioDir = join(process.cwd(), 'audio-output');
    if (!existsSync(audioDir)) mkdirSync(audioDir, { recursive: true });

    const filename = `speech-${Date.now()}.mp3`;
    const outputPath = join(audioDir, filename);

    await textToSpeech(text, outputPath);

    // Send the audio file directly for browser playback
    res.sendFile(outputPath);
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'TTS failed';
    res.status(500).json({ error: msg });
  }
});

// Chat + Speak (combined)
app.post('/ask', async (req, res) => {
  try {
    const { message, sessionId, speak } = req.body;

    if (!message) {
      res.status(400).json({ error: 'message is required' });
      return;
    }

    // Get or create session
    const sid = sessionId ?? `session-${Date.now()}`;
    if (!sessions.has(sid)) {
      sessions.set(sid, {
        id: sid,
        history: [{
          role: 'system',
          content: `You are JARVIS, a personal AI assistant. You are helpful, knowledgeable, and speak concisely. You were built by your owner as a personal AI system. Current date: ${new Date().toLocaleDateString()}.`
        }],
        createdAt: new Date(),
      });
    }

    const session = sessions.get(sid)!;
    session.history.push({ role: 'user', content: message });

    const reply = await generateWithGroq(session.history);
    session.history.push({ role: 'assistant', content: reply });

    // Keep history manageable
    if (session.history.length > 102) {
      session.history = [session.history[0]!, ...session.history.slice(-100)];
    }

    let audioFile: string | null = null;
    if (speak) {
      try {
        const audioDir = join(process.cwd(), 'audio-output');
        if (!existsSync(audioDir)) mkdirSync(audioDir, { recursive: true });
        const filename = `speech-${Date.now()}.mp3`;
        audioFile = join(audioDir, filename);
        await textToSpeech(reply, audioFile);
      } catch {
        audioFile = null;
      }
    }

    res.json({
      reply,
      sessionId: sid,
      audioFile,
      timestamp: new Date().toISOString(),
    });
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'Unknown error';
    console.error('[Ask Error]', msg);
    res.status(500).json({ error: msg });
  }
});

// Simple web UI
app.get('/', (_req, res) => {
  res.sendFile(join(process.cwd(), 'public', 'index.html'));
});

// --- Start Server ---
app.listen(PORT, () => {
  console.log('');
  console.log('╔══════════════════════════════════════════════════════╗');
  console.log('║         JARVIS - Personal AI Assistant              ║');
  console.log('║         Running locally on your machine             ║');
  console.log('╠══════════════════════════════════════════════════════╣');
  console.log(`║  Web UI:  http://localhost:${PORT}                      ║`);
  console.log(`║  API:     http://localhost:${PORT}/chat                  ║`);
  console.log(`║  Health:  http://localhost:${PORT}/health                ║`);
  console.log('╠══════════════════════════════════════════════════════╣');
  console.log(`║  LLM:    ${GROQ_API_KEY ? 'Groq API (Mixtral-8x7B)' : 'Demo mode (set GROQ_API_KEY)'}      ║`);
  console.log('║  TTS:    Edge TTS (Microsoft)                       ║');
  console.log('║  Mode:   CPU-only, no Docker needed                 ║');
  console.log('╚══════════════════════════════════════════════════════╝');
  console.log('');
  if (!GROQ_API_KEY) {
    console.log('⚠️  No GROQ_API_KEY set. Get a free key at: https://console.groq.com');
    console.log('   Then run: set GROQ_API_KEY=your-key-here');
    console.log('');
  }
});
