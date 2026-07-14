---
title: JARVIS AI
emoji: 🤖
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# J.A.R.V.I.S — Personal AI Assistant

A Tony Stark-inspired personal AI assistant powered by Cerebras AI (120B parameters). Voice-enabled, real-time data, image generation, and more.

## Features

- **AI Chat** — Powered by Cerebras (gpt-oss-120b), genius-level reasoning
- **Voice Interaction** — Tap to talk, JARVIS speaks back
- **Real-time Data** — Live web search via DuckDuckGo, Google News RSS
- **Image Generation** — Create images from descriptions (Pollinations.ai)
- **Music Playback** — Say "play [song]" to open YouTube
- **Iron Man HUD UI** — Molecular orb, grid lines, scan effects, watery mouse interaction
- **Encrypted Storage** — Personal data secured with AES-256
- **Email Auth** — Signup/signin for multi-user access

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python (Flask) |
| AI Model | Cerebras (gpt-oss-120b / gemma-4-31b) |
| Search | DuckDuckGo API |
| News | Google News RSS |
| Images | Pollinations.ai |
| Voice | Browser Web Speech API |
| Frontend | Vanilla HTML/CSS/JS |
| Deploy | Docker on Hugging Face Spaces |

## Run Locally

```bash
pip install -r requirements.txt
export CEREBRAS_API_KEY=your-key-here
python app.py
```

Open http://localhost:7860

## Deploy

Already deployed on Hugging Face Spaces. Push to this repo and it auto-deploys.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `CEREBRAS_API_KEY` | Yes | Cerebras AI API key |
| `PORT` | No | Server port (default: 7860) |
| `RESEND_API_KEY` | No | For email OTP verification |

## Project Structure

```
├── app.py              # Python backend (Flask)
├── requirements.txt    # Python dependencies
├── Dockerfile          # Docker deployment
├── public/
│   ├── index.html      # Frontend UI (Iron Man HUD)
│   ├── manifest.json   # PWA manifest
│   ├── sw.js           # Service worker
│   └── icons/          # App icons
└── README.md
```

## License

Private — Personal use only.
