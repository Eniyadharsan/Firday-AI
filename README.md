# J.A.R.V.I.S — Personal AI Assistant

A personal AI assistant inspired by Tony Stark's JARVIS. Voice-enabled with real-time web data, music streaming, image/video generation, document intelligence, research reports, and multi-agent orchestration — all wrapped in a cosmic universe interface with a Canvas-rendered particle sphere orb.

## Features

### Core AI
- **Conversational AI** — Powered by Cerebras (gemma-4-31b / gpt-oss-120b), context-aware multi-turn chat
- **Multi-Agent System** — Automatic routing to specialized agents for complex tasks
- **Long-Term Memory** — Learns your preferences, facts, and context over time
- **Task Planner** — Break goals into actionable steps with progress tracking

### Voice & Interface
- **Voice Interaction** — Tap-to-talk with speech recognition, JARVIS speaks back via TTS
- **Speech-Rate Pulsation** — The orb reacts in real-time to speech cadence (word boundary events)
- **Cosmic Universe UI** — Pure black space background, twinkling starfield, canvas particle sphere
- **Canvas Orb** — 1800-point organic particle sphere with flowing energy, fiery rays, dust cloud
- **State Feedback** — Blue (idle), pulsating blue (speaking), green shift (listening)

### Data & Search
- **Real-Time Search** — Live web search via DuckDuckGo
- **News Feed** — Google News RSS (world, tech, business)
- **Research Reports** — Multi-source deep research with formatted output

### Media
- **Music Player** — Multi-source search (YouTube, JioSaavn, Gaana), embedded playback with autocomplete
- **Image Generation** — Text-to-image via Pollinations.ai
- **Video Generation** — Create videos from descriptions

### Document Intelligence
- **RAG (Retrieval Augmented Generation)** — Upload PDF/TXT/CSV/MD files, ask questions about them
- **Chunked Indexing** — Documents split into searchable chunks for contextual answers

### Infrastructure
- **JWT Authentication** — Email signup/signin with optional OTP verification
- **Rate Limiting** — 30 req/min on chat, 60 req/min global
- **Turso Cloud Database** — SQLite on the edge (with local fallback)
- **MCP Protocol** — Model Context Protocol for tool integration
- **Streaming Chat** — Server-Sent Events for real-time token streaming

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.11+ (Flask 3.1) |
| AI Model | Cerebras (gemma-4-31b, gpt-oss-120b) |
| Database | Turso (libsql) / SQLite local fallback |
| Search | DuckDuckGo API |
| News | Google News RSS |
| Images | Pollinations.ai |
| Music | YouTube + JioSaavn + Gaana (aggregated) |
| Voice | Web Speech API (recognition + synthesis) |
| Frontend | Vanilla HTML/CSS/JS + Canvas 2D |
| Auth | JWT + email OTP (Resend) |
| Rate Limit | Flask-Limiter (in-memory) |
| Deploy | Vercel / Docker |

## Run Locally

### Prerequisites
- Python 3.11+
- A Cerebras API key ([get one here](https://cerebras.ai))

### Setup

```bash
# Clone the repository
git clone https://github.com/Eniyadharsan/Jarvis-AI.git
cd Jarvis-AI

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your CEREBRAS_API_KEY
```

### Run

```bash
python app.py
```

Open **http://localhost:7860** in your browser.

### Docker

```bash
docker build -t jarvis .
docker run -p 7860:7860 --env-file .env jarvis
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CEREBRAS_API_KEY` | Yes | — | Cerebras AI API key |
| `PORT` | No | `7860` | Server port |
| `JWT_SECRET` | No | `jarvis-secret-change-in-prod` | JWT signing secret (change in production) |
| `TURSO_DATABASE_URL` | No | — | Turso database URL (falls back to local SQLite) |
| `TURSO_AUTH_TOKEN` | No | — | Turso auth token |
| `RESEND_API_KEY` | No | — | Resend API key for email OTP verification |
| `YOUTUBE_API_KEY` | No | — | YouTube Data API v3 key for music search |
| `DEBUG` | No | `false` | Enable debug logging |

## API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/` | No | Serves the frontend UI |
| GET | `/health` | No | Health check + version info |
| POST | `/chat` | Yes | Main chat endpoint (30/min rate limit) |
| POST | `/chat/stream` | Yes | Streaming chat via SSE |
| POST | `/auth/email/signup` | No | Create account |
| POST | `/auth/email/signin` | No | Sign in |
| POST | `/search` | Yes | Web search |
| GET | `/news` | No | Latest news (world/tech/business) |
| POST | `/image` | Yes | Generate image from prompt |
| POST | `/music` | Yes | Get music URL |
| GET | `/music/search?q=` | Yes | Search tracks across sources |
| GET | `/music/autocomplete?q=` | Yes | Search suggestions |
| POST | `/rag/upload` | Yes | Upload document for RAG |
| GET | `/rag/documents` | Yes | List uploaded documents |
| DELETE | `/rag/documents/:id` | Yes | Delete a document |
| GET | `/memory` | Yes | Get user memories |
| POST | `/memory` | Yes | Add a memory |
| GET | `/history` | Yes | List chat sessions |
| GET | `/history/:sessionId` | Yes | Get session messages |
| GET | `/profile` | Yes | Get learned user facts |
| POST | `/research` | Yes | Generate research report |
| GET | `/plans` | Yes | Get task plans |
| POST | `/plans` | Yes | Create a plan from goal |
| POST | `/mcp` | No | MCP protocol handler |
| GET | `/mcp/tools` | No | List available MCP tools |
| GET | `/agents` | No | List available agents |

## Project Structure

```
├── app.py                    # Flask application (routes, middleware)
├── requirements.txt          # Python dependencies
├── Dockerfile                # Docker deployment config
├── .env.example              # Environment variable template
├── jarvis/
│   ├── config.py             # Configuration (env vars, paths)
│   ├── db.py                 # Database layer (Turso/SQLite)
│   ├── system_prompt.py      # AI system prompt
│   └── modules/
│       ├── llm.py            # Cerebras AI integration
│       ├── auth.py           # JWT authentication + email OTP
│       ├── search.py         # DuckDuckGo web search
│       ├── news.py           # Google News RSS
│       ├── image.py          # Image generation (Pollinations)
│       ├── video.py          # Video generation
│       ├── music.py          # Music request detection + URL
│       ├── music_search_engine.py  # Multi-source music search
│       ├── music_aggregator.py     # Source aggregation
│       ├── music_youtube_adapter.py
│       ├── music_jiosaavn_adapter.py
│       ├── music_gaana_adapter.py
│       ├── music_autocomplete.py   # Search suggestions
│       ├── music_fuzzy.py    # Fuzzy matching
│       ├── music_language.py # Language processing
│       ├── music_catalog.py  # Catalog cache
│       ├── music_models.py   # Data models
│       ├── memory.py         # Chat history + session memory
│       ├── long_memory.py    # Long-term fact extraction
│       ├── rag.py            # Document upload + retrieval
│       ├── research.py       # Deep research reports
│       ├── agents.py         # Multi-agent orchestration
│       ├── planner.py        # Task planning
│       └── mcp.py            # Model Context Protocol
├── public/
│   ├── index.html            # Frontend (Canvas orb + cosmic UI)
│   ├── manifest.json         # PWA manifest
│   ├── sw.js                 # Service worker (offline)
│   └── icons/                # App icons
└── .github/
    └── workflows/
        └── ci.yml            # CI pipeline
```

## Deployment

### Vercel
Push to `main` branch — auto-deploys via GitHub integration.

### Docker
```bash
docker build -t jarvis .
docker run -p 7860:7860 --env-file .env jarvis
```

### Manual (any server)
```bash
pip install -r requirements.txt
python app.py
# Listens on 0.0.0.0:7860
```

## License

Private — Personal use only.
