# JARVIS — Global Deployment Guide

## Deploy to Cloud (Free — Render.com)

### Step 1: Install Git
Download from: https://git-scm.com/download/win
Install with default options.

### Step 2: Create GitHub repo
1. Go to https://github.com → Sign in → New Repository
2. Name it "jarvis-ai" → Private → Create
3. In your project folder, run:
```bash
cd "C:\Users\eniyannn\Documents\New Project unnamed"
git init
git add .
git commit -m "JARVIS personal AI"
git remote add origin https://github.com/YOUR-USERNAME/jarvis-ai.git
git push -u origin main
```

### Step 3: Deploy on Render.com
1. Go to https://render.com → Sign up (free) with GitHub
2. Click "New" → "Web Service"
3. Connect your "jarvis-ai" GitHub repo
4. Settings:
   - Name: `jarvis-ai`
   - Runtime: `Node`
   - Build Command: `npm install && npx tsc`
   - Start Command: `node dist/cloud-server.js`
5. Add Environment Variable:
   - Key: `GROQ_API_KEY`
   - Value: `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`
6. Click "Create Web Service"
7. Wait 2-3 minutes — you'll get a URL like `https://jarvis-ai-xxxx.onrender.com`

### Step 4: Access JARVIS Globally
- **Browser (anywhere):** Open your Render URL
- **iPhone:** Open Render URL in Safari → Share → Add to Home Screen
- **Android:** Open in Chrome → Install app prompt
- **Desktop app:** Update SERVER_URL in desktop-app/main.js with your Render URL

---

## Desktop App (Windows .exe)

### Build the desktop app:
```bash
cd desktop-app
npm install
npm run build-win
```
This creates `desktop-app/dist/JARVIS Setup.exe` — install it like any Windows app.

### Features:
- **Ctrl+Shift+J** — Global hotkey to show/hide JARVIS
- **System tray** — Right-click for options
- **Always on top** — Optional floating mode
- Launches instantly, connects to your cloud server

---

## Run Locally (without cloud)
```powershell
cd "C:\Users\eniyannn\Documents\New Project unnamed"
$env:GROQ_API_KEY="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"
npx ts-node src/cloud-server.ts
```
Open: http://localhost:3000

---

## What JARVIS Can Do

| Feature | How |
|---------|-----|
| Chat | Type or speak to JARVIS |
| Voice | Speaks back naturally (Aria Neural voice) |
| Web Search | Automatically searches DuckDuckGo for current info |
| News | Fetches live news from Google News RSS |
| Music | Say "play [song]" → opens YouTube |
| Memory | Say "remember..." → JARVIS remembers (encrypted) |
| Private | All data AES-256 encrypted, password protected |
| Global | Accessible from any device, anywhere |
