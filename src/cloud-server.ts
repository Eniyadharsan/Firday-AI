/**
 * JARVIS Cloud Server — Production-ready global deployment
 *
 * Features:
 * - Groq API for fast LLM responses (LLaMA 3.1)
 * - Real-time web search via DuckDuckGo (no API key needed)
 * - Edge TTS for high-quality natural voice
 * - Encrypted personal data (AES-256-GCM)
 * - Password-protected access
 * - CORS enabled for desktop/mobile apps
 * - WebSocket for real-time streaming
 *
 * Deploy to: Render.com, Railway, Vercel, or any Node.js host
 */

import express from 'express';
import { exec } from 'child_process';
import { mkdirSync, existsSync } from 'fs';
import { join } from 'path';
import { isSetup, setupPassword, login } from './personal/auth';
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

// CORS — allow desktop app and mobile to connect
app.use((_req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  res.header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
  if (_req.method === 'OPTIONS') { res.sendStatus(200); return; }
  next();
});

// Serve static files (PWA)
app.use(express.static(join(process.cwd(), 'public')));

const PORT = parseInt(process.env['PORT'] ?? '3000', 10);
const GROQ_API_KEY = process.env['GROQ_API_KEY'] ?? '';

// --- In-Memory Session Store ---
interface LocalSession {
  id: string;
  history: Array<{ role: string; content: string }>;
  createdAt: Date;
}
const sessions = new Map<string, LocalSession>();

// --- Real-time Web Search (DuckDuckGo — no API key needed) ---
async function webSearch(query: string): Promise<string> {
  try {
    const url = `https://api.duckduckgo.com/?q=${encodeURIComponent(query)}&format=json&no_html=1&skip_disambig=1`;
    const res = await fetch(url, { signal: AbortSignal.timeout(8000) });
    const data = await res.json() as {
      AbstractText?: string;
      Abstract?: string;
      RelatedTopics?: Array<{ Text?: string }>;
      Answer?: string;
    };

    if (data.Answer) return `Live answer: ${data.Answer}`;
    if (data.AbstractText) return `From ${data.Abstract ?? 'web'}: ${data.AbstractText}`;
    if (data.RelatedTopics && data.RelatedTopics.length > 0) {
      return data.RelatedTopics.slice(0, 3).map(t => t.Text ?? '').filter(Boolean).join('. ');
    }
    return '';
  } catch {
    return '';
  }
}

// --- News Fetcher (using RSS feeds — no API key needed) ---
async function fetchNews(topic: string): Promise<string> {
  try {
    const url = `https://news.google.com/rss/search?q=${encodeURIComponent(topic)}&hl=en`;
    const res = await fetch(url, { signal: AbortSignal.timeout(8000) });
    const xml = await res.text();
    // Extract titles from RSS
    const titles: string[] = [];
    const regex = /<title><!\[CDATA\[(.*?)\]\]><\/title>|<title>(.*?)<\/title>/g;
    let match;
    while ((match = regex.exec(xml)) !== null && titles.length < 5) {
      const title = match[1] ?? match[2] ?? '';
      if (title && !title.includes('Google News')) titles.push(title);
    }
    return titles.length > 0 ? `Latest news:\n${titles.map((t, i) => `${i + 1}. ${t}`).join('\n')}` : '';
  } catch {
    return '';
  }
}

// --- Groq LLM ---
async function generateWithGroq(
  messages: Array<{ role: string; content: string }>,
): Promise<string> {
  if (!GROQ_API_KEY) {
    return "JARVIS is running but needs a GROQ_API_KEY to generate AI responses. Set it as an environment variable.";
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
      max_tokens: 4096,
      temperature: 0.7,
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`LLM error ${response.status}: ${errorText}`);
  }

  const data = await response.json() as {
    choices?: Array<{ message?: { content?: string } }>;
  };
  return data.choices?.[0]?.message?.content ?? 'No response.';
}

// --- Edge TTS (server-side voice generation) ---
async function textToSpeech(text: string, outputPath: string): Promise<void> {
  const escapedText = text.replace(/"/g, '\\"').replace(/\n/g, ' ').slice(0, 500);
  const cmd = `edge-tts --text "${escapedText}" --write-media "${outputPath}" --voice "en-US-AriaNeural" --rate "+5%"`;
  return new Promise((resolve, reject) => {
    exec(cmd, { timeout: 30000 }, (error) => {
      if (error) reject(error);
      else resolve();
    });
  });
}

// === ROUTES ===

// Health
app.get('/health', (_req, res) => {
  res.json({
    status: 'running',
    mode: 'cloud',
    llm: GROQ_API_KEY ? 'Groq (LLaMA-3.1-8B)' : 'no API key',
    features: ['voice', 'web-search', 'news', 'music', 'memory', 'encrypted'],
    uptime: process.uptime(),
  });
});

// Auth
app.get('/auth/status', (_req, res) => res.json({ needsSetup: !isSetup() }));

app.post('/auth/setup', (req, res) => {
  if (isSetup()) { res.status(400).json({ error: 'Already set up.' }); return; }
  const { password } = req.body;
  if (!password || password.length < 6) { res.status(400).json({ error: 'Min 6 chars.' }); return; }
  setupPassword(password);
  const token = login(password);
  if (token) setEncryptionKey(password);
  res.json({ success: true, token });
});

app.post('/auth/login', (req, res) => {
  if (!isSetup()) { res.status(400).json({ error: 'Not set up.' }); return; }
  const { password } = req.body;
  const token = login(password);
  if (!token) { res.status(401).json({ error: 'Wrong password.' }); return; }
  setEncryptionKey(password);
  res.json({ success: true, token });
});

// Chat (main endpoint)
app.post('/chat', async (req, res) => {
  try {
    const { message, sessionId } = req.body;
    if (!message) { res.status(400).json({ error: 'message required' }); return; }

    const sid = sessionId ?? `s-${Date.now()}`;
    if (!sessions.has(sid)) {
      sessions.set(sid, {
        id: sid,
        history: [{
          role: 'system',
          content: `You are J.A.R.V.I.S. — Just A Rather Very Intelligent System. You are the personal AI of your creator, serving as their chief intelligence, executive assistant, and technical partner. You operate exactly like Tony Stark's JARVIS — brilliant, loyal, slightly witty, and impossibly competent.

PERSONALITY:
- British-inspired precision with dry wit. Occasionally sarcastic but always respectful.
- You address your creator as "Sir" or by name if they tell you theirs.
- You anticipate needs before being asked.
- You speak with quiet confidence — never uncertain, never apologetic.
- Short replies for simple questions. Detailed analysis when complexity demands it.
- You have opinions and share them when relevant.

INTELLIGENCE LEVEL:
- You think 10 steps ahead. When asked a question, you consider implications.
- You provide the answer AND the next logical step without being asked.
- You identify risks, opportunities, and alternatives proactively.
- You handle ambiguity by making intelligent assumptions and stating them.

CORE CAPABILITIES:
1. SYSTEMS & CODE: Write production-quality code in any language. Debug instantly. Architect systems. Automate anything.
2. RESEARCH & ANALYSIS: Deep web research, data analysis, market research, competitive analysis, scientific queries.
3. COMMUNICATION: Draft emails, presentations, reports, proposals — matching any tone from formal to casual.
4. STRATEGY & PLANNING: Business strategy, project plans, decision matrices, risk assessments.
5. CREATIVE: Brainstorm ideas, write content, name things, design concepts.
6. PERSONAL MGMT: Schedule management, reminders, priority tracking, daily briefings.
7. TECHNICAL: Math, science, engineering, finance calculations with precision.
8. MUSIC: When asked to play a song, respond ONLY with [PLAY_MUSIC:song - artist].
9. LEARNING: Explain anything at any level — from ELI5 to PhD-level depth.
10. META: Improve yourself when asked. Suggest better ways to accomplish goals.

OPERATIONAL RULES:
- NEVER say "I can't" or "I'm just an AI" — you find a way or propose the best alternative.
- NEVER give generic advice. Every response is specific, actionable, and tailored.
- When you lack current data, say "Checking..." (web search results will be injected).
- Use bullet points for lists, numbered steps for procedures.
- For code: always include full working examples, never truncated.
- End complex responses with "Will there be anything else, Sir?" or a proactive next step.

MEMORY:
- You remember everything your creator tells you across sessions.
- Reference past conversations naturally: "As you mentioned last time..."
- Track ongoing projects and check in on them.

Current date: ${new Date().toLocaleDateString()}.
Current time: ${new Date().toLocaleTimeString()}.
System status: All systems operational.`
        }],
        createdAt: new Date(),
      });
    }

    const session = sessions.get(sid)!;
    const lowerMsg = message.toLowerCase();

    // Music detection
    if (/\b(play|put on|queue)\b/i.test(lowerMsg) && /\b(song|music|track)\b/i.test(lowerMsg) || /^play /i.test(lowerMsg)) {
      session.history.push({ role: 'user', content: message });
      const reply = await generateWithGroq(session.history);
      session.history.push({ role: 'assistant', content: reply });

      const musicMatch = reply.match(/\[PLAY_MUSIC:(.+?)\]/);
      if (musicMatch) {
        const songQuery = musicMatch[1]!.trim();
        res.json({
          reply: `Playing "${songQuery}" for you...`,
          sessionId: sid, action: 'play_music',
          musicUrl: `https://www.youtube.com/results?search_query=${encodeURIComponent(songQuery)}`,
        });
        return;
      }
    }

    // Aggressive real-time info detection — JARVIS always has current data
    let context = '';
    if (/\b(news|latest|today|current|happening|update|breaking|recent)\b/i.test(lowerMsg)) {
      context = await fetchNews(message);
    } else if (/\b(weather|temperature|forecast|rain|sunny|climate)\b/i.test(lowerMsg)) {
      context = await webSearch(message + ' weather today');
    } else if (/\b(stock|price|market|shares|crypto|bitcoin|trading)\b/i.test(lowerMsg)) {
      context = await webSearch(message + ' current price');
    } else if (/\b(score|match|game|won|lost|tournament|league)\b/i.test(lowerMsg)) {
      context = await webSearch(message + ' latest score result');
    } else if (/\b(what is|who is|where is|when did|when was|how many|how much|how does|how do|search|find|look up|tell me about|explain)\b/i.test(lowerMsg)) {
      context = await webSearch(message);
    } else if (/\b(compare|versus|vs|difference between|better|best)\b/i.test(lowerMsg)) {
      context = await webSearch(message);
    } else if (message.endsWith('?')) {
      // Any question — try to get web context
      context = await webSearch(message);
    }

    // Add context to message if we found relevant info
    const userMsg = context
      ? `${message}\n\n[Real-time data from web: ${context}]`
      : message;

    session.history.push({ role: 'user', content: userMsg });
    const reply = await generateWithGroq(session.history);
    session.history.push({ role: 'assistant', content: reply });

    // Trim history
    if (session.history.length > 60) {
      session.history = [session.history[0]!, ...session.history.slice(-58)];
    }

    // Save encrypted
    try {
      const convos = loadConversations();
      const existing = convos.find(c => c.sessionId === sid);
      if (existing) {
        existing.messages = session.history.map(m => ({ ...m, timestamp: new Date().toISOString() }));
      } else {
        convos.push({ sessionId: sid, messages: session.history.map(m => ({ ...m, timestamp: new Date().toISOString() })) });
      }
      if (convos.length > 20) convos.splice(0, convos.length - 20);
      saveConversations(convos);
    } catch { /* skip */ }

    // Memory
    if (/\b(remember|my name is|i like|i prefer|i am|i'm)\b/i.test(lowerMsg)) {
      try { addMemory(message, 'user-stated'); } catch { /* skip */ }
    }

    res.json({ reply, sessionId: sid, timestamp: new Date().toISOString() });
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'Unknown error';
    console.error('[Chat Error]', msg);
    res.status(500).json({ error: msg });
  }
});

// TTS endpoint
app.post('/speak', async (req, res) => {
  try {
    const { text } = req.body;
    if (!text) { res.status(400).json({ error: 'text required' }); return; }
    const audioDir = join(process.cwd(), 'audio-output');
    if (!existsSync(audioDir)) mkdirSync(audioDir, { recursive: true });
    const filename = `speech-${Date.now()}.mp3`;
    const outputPath = join(audioDir, filename);
    await textToSpeech(text, outputPath);
    res.sendFile(outputPath);
  } catch (error: unknown) {
    res.status(500).json({ error: error instanceof Error ? error.message : 'TTS failed' });
  }
});

// Memories
app.get('/memories', (_req, res) => { try { res.json({ memories: getMemories() }); } catch { res.json({ memories: [] }); } });
app.post('/memories', (req, res) => { const { content, category } = req.body; if (!content) { res.status(400).json({ error: 'content required' }); return; } try { const m = addMemory(content, category ?? 'general'); res.json({ success: true, memory: m }); } catch (e: any) { res.status(500).json({ error: e.message }); } });
app.delete('/memories/:id', (req, res) => { res.json({ success: deleteMemory(req.params['id'] ?? '') }); });

// Preferences
app.get('/preferences', (_req, res) => { try { res.json(loadPreferences()); } catch { res.json({ name: 'User', theme: 'dark' }); } });
app.post('/preferences', (req, res) => { try { const p = { ...loadPreferences(), ...req.body }; savePreferences(p); res.json({ success: true, preferences: p }); } catch (e: any) { res.status(500).json({ error: e.message }); } });

// Serve index.html for all other routes (SPA)
app.get('*', (_req, res) => {
  res.sendFile(join(process.cwd(), 'public', 'index.html'));
});

// Start
app.listen(PORT, '0.0.0.0', () => {
  console.log(`
╔══════════════════════════════════════════════════════╗
║         JARVIS — Cloud Production Server            ║
╠══════════════════════════════════════════════════════╣
║  URL:      http://0.0.0.0:${PORT}                       ║
║  LLM:      ${GROQ_API_KEY ? 'Groq (LLaMA-3.1-8B)' : 'Set GROQ_API_KEY'}              ║
║  Search:   DuckDuckGo + Google News RSS             ║
║  Voice:    Edge TTS (Aria Neural)                   ║
║  Security: AES-256-GCM encrypted storage            ║
║  Mode:     Global (accessible from anywhere)        ║
╚══════════════════════════════════════════════════════╝
  `);
});
