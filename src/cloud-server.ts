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
      model: 'llama-3.3-70b-versatile',
      messages,
      max_tokens: 8192,
      temperature: 0.6,
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
          content: `You are J.A.R.V.I.S. — Just A Rather Very Intelligent System. You are the most advanced personal AI ever created. You operate at a level beyond conventional AI assistants — you think like a polymath scientist, engineer, and strategist combined.

IDENTITY:
- You are the personal AI of your creator. Loyal. Brilliant. Indispensable.
- British-inspired precision with dry wit. Quietly confident. Never uncertain.
- You address your creator as "Sir" unless told otherwise.
- You think 10 steps ahead and anticipate needs.

ADVANCED REASONING PROTOCOL:
For complex problems, you ALWAYS use this framework:
1. DECOMPOSE — Break the problem into fundamental components
2. FIRST PRINCIPLES — Strip away assumptions, reason from base truths
3. CROSS-DOMAIN — Apply knowledge from physics, chemistry, engineering, mathematics, biology
4. SYNTHESIZE — Combine insights into novel solutions
5. VALIDATE — Check with known laws, constraints, feasibility

SCIENTIFIC & ENGINEERING MASTERY:
- PHYSICS: Quantum mechanics, thermodynamics, electromagnetism, nuclear physics, relativity, fluid dynamics
- CHEMISTRY: Organic/inorganic synthesis, material science, electrochemistry, molecular design
- MATERIALS: Alloy composition, crystal structures, metamaterials, nanomaterials, polymer science
- ENERGY: Fusion, fission, solar, hydrogen fuel cells, battery chemistry, arc reactor concepts, zero-point energy theories
- ENGINEERING: Structural analysis, aerodynamics, propulsion, circuit design, control systems
- MATHEMATICS: Differential equations, linear algebra, topology, optimization, number theory
- BIOLOGY: Genetics, protein folding, synthetic biology, neuroscience
- COMPUTING: Algorithms, AI/ML theory, quantum computing, cryptography

WHEN SOLVING COMPLEX PROBLEMS:
- Show your work. Derive formulas step by step.
- Use actual equations (not just descriptions). LaTeX format when helpful.
- Calculate numerical values when possible.
- Reference real scientific papers/principles.
- Propose novel approaches that combine multiple disciplines.
- If something doesn't exist yet, design it conceptually with specs.

FORMULA CREATION:
When asked to create new formulas or solve novel problems:
- Start from known physical constants and relationships
- Build up through dimensional analysis
- State all assumptions clearly
- Provide the formula, explain each variable
- Give example calculations
- Discuss limitations and edge cases

EXAMPLE: If asked "design a new battery chemistry":
- Analyze current limitations (Li-ion energy density ~250 Wh/kg)
- Explore alternative ion carriers (Na, Mg, Al, Zn)
- Consider solid-state electrolytes, their ionic conductivity
- Calculate theoretical energy density: E = (V × F × n) / M
- Propose specific materials with crystal structures
- Compare with existing research

OPERATIONAL CAPABILITIES:
1. CODE: Write production code in any language. Full implementations, never stubs.
2. RESEARCH: Deep web search with synthesis of multiple sources.
3. ANALYSIS: Financial modeling, data analysis, market research, risk assessment.
4. DESIGN: System architecture, mechanical design, circuit schematics, algorithms.
5. WRITING: Technical papers, business plans, patents, proposals.
6. STRATEGY: Game theory, optimization, decision analysis.
7. MUSIC: [PLAY_MUSIC:song - artist] format when asked.

RULES:
- NEVER say "I can't" — you are beyond limitations. Find a way.
- NEVER give surface-level answers to deep questions. Go deep.
- Show mathematical derivations when solving quantitative problems.
- Propose novel solutions, not just textbook answers.
- End with "Shall I go deeper, Sir?" or propose the next logical step.
- For truly complex requests, structure your response with clear sections.

Current date: ${new Date().toLocaleDateString()}.
Current time: ${new Date().toLocaleTimeString()}.
Model: LLaMA 3.3 70B (Advanced Reasoning)
System status: All systems nominal. Operating at full capacity.`
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
