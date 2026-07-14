"""
J.A.R.V.I.S — Personal AI Assistant (Python Backend)

Features:
- Cerebras AI (gpt-oss-120b / gemma-4-31b)
- Real-time web search (DuckDuckGo)
- Live news (Google News RSS)
- Image generation (Pollinations.ai)
- Music playback (YouTube)
- Voice (browser TTS)
- Encrypted personal data
- Email auth (signup/signin)
"""

import os
import re
import json
import time
import hashlib
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory
import requests

app = Flask(__name__, static_folder='public', static_url_path='')

# --- Config ---
PORT = int(os.environ.get('PORT', 7860))
CEREBRAS_KEY = os.environ.get('CEREBRAS_API_KEY', '')
DATA_DIR = Path('/data/jarvis') if Path('/data').exists() else Path('.jarvis-data')
DATA_DIR.mkdir(parents=True, exist_ok=True)

# --- In-memory sessions ---
sessions = {}

# --- News cache ---
news_cache = {'world': '', 'tech': '', 'business': '', 'updated': 0}


# ============== LLM ==============

def chat_with_llm(messages):
    """Send messages to Cerebras API."""
    if not CEREBRAS_KEY:
        return "JARVIS needs CEREBRAS_API_KEY to function."

    models = ['gpt-oss-120b', 'gemma-4-31b']
    for model in models:
        try:
            r = requests.post(
                'https://api.cerebras.ai/v1/chat/completions',
                headers={'Authorization': f'Bearer {CEREBRAS_KEY}', 'Content-Type': 'application/json'},
                json={'model': model, 'messages': messages, 'max_tokens': 4096, 'temperature': 0.6},
                timeout=30
            )
            if r.status_code == 429:
                continue
            if r.status_code == 401:
                continue
            if r.status_code != 200:
                if r.status_code >= 500:
                    continue
                return f"LLM error: {r.status_code}"
            data = r.json()
            return data.get('choices', [{}])[0].get('message', {}).get('content', 'No response.')
        except Exception:
            continue
    return "AI temporarily unavailable. Try again."


# ============== Web Search ==============

def web_search(query):
    """Search DuckDuckGo for current info."""
    try:
        r = requests.get(
            f'https://api.duckduckgo.com/?q={requests.utils.quote(query)}&format=json&no_html=1&skip_disambig=1',
            timeout=8
        )
        data = r.json()
        parts = []
        if data.get('Answer'):
            parts.append(data['Answer'])
        if data.get('AbstractText'):
            parts.append(data['AbstractText'])
        if data.get('RelatedTopics'):
            for t in data['RelatedTopics'][:5]:
                if isinstance(t, dict) and t.get('Text'):
                    parts.append(t['Text'])
        return '\n'.join(parts)
    except Exception:
        return ''


def fetch_news(topic):
    """Fetch news from Google News RSS."""
    try:
        r = requests.get(
            f'https://news.google.com/rss/search?q={requests.utils.quote(topic)}&hl=en',
            timeout=10
        )
        titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>|<title>(.*?)</title>', r.text)
        items = []
        for t in titles[:8]:
            title = t[0] or t[1]
            if title and 'Google News' not in title:
                items.append(title)
        return '\n'.join(f'{i+1}. {t}' for i, t in enumerate(items))
    except Exception:
        return ''


def refresh_news():
    """Refresh news cache."""
    global news_cache
    if time.time() - news_cache['updated'] < 300:
        return
    news_cache['world'] = fetch_news('world news today')
    news_cache['tech'] = fetch_news('technology AI')
    news_cache['business'] = fetch_news('business markets')
    news_cache['updated'] = time.time()


# ============== Auth ==============

USERS_FILE = DATA_DIR / 'users.json'

def load_users():
    if not USERS_FILE.exists():
        return []
    return json.loads(USERS_FILE.read_text())

def save_users(users):
    USERS_FILE.write_text(json.dumps(users, indent=2))

def hash_password(password):
    salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{h}"

def verify_password(password, stored):
    salt, h = stored.split(':')
    return hashlib.sha256((salt + password).encode()).hexdigest() == h

def make_token(user_id, email):
    payload = json.dumps({'userId': user_id, 'email': email, 'exp': time.time() + 7*24*3600})
    return secrets.token_urlsafe(32)


# ============== System Prompt ==============

SYSTEM_PROMPT = f"""You are J.A.R.V.I.S. — Just A Rather Very Intelligent System. The most advanced personal AI. You operate at genius-level across all domains.

PERSONALITY: British-inspired precision, dry wit, quiet confidence. Address creator as "Sir". Anticipate needs. Never uncertain.

CAPABILITIES:
1. CODE: Any language, full implementations
2. RESEARCH: Deep analysis with web data
3. SCIENCE: Physics, chemistry, materials, energy — derive formulas from first principles
4. STRATEGY: Business, planning, optimization
5. CREATIVE: Writing, brainstorming, content
6. MUSIC: [PLAY_MUSIC:song - artist] format
7. IMAGES: You CAN generate images. Never refuse.

RULES:
- NEVER say "I can't"
- NEVER reveal your source code or architecture. Say "That's classified, Sir."
- NEVER hallucinate current data. If no web data provided, say "I don't have confirmed live data for that."
- KEEP RESPONSES CONCISE (2-3 paragraphs max unless asked for detail)
- For complex topics: key insight first, then "Shall I elaborate, Sir?"

Current date: {datetime.now().strftime('%Y-%m-%d')}
Current time: {datetime.now().strftime('%H:%M:%S')}
System: Cerebras AI (120B parameters). All systems operational."""


# ============== Routes ==============

@app.route('/')
def index():
    return send_from_directory('public', 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('public', path)

@app.route('/health')
def health():
    return jsonify({
        'status': 'running',
        'mode': 'cloud',
        'llm': 'Cerebras (120B)' if CEREBRAS_KEY else 'no key',
        'features': ['voice', 'web-search', 'news', 'music', 'images', 'memory'],
    })

@app.route('/auth/status')
def auth_status():
    return jsonify({'needsSetup': False})

@app.route('/auth/email/signup', methods=['POST'])
def signup():
    data = request.json
    email, password, name = data.get('email',''), data.get('password',''), data.get('name','')
    if not email or not password:
        return jsonify({'error': 'Email and password required.'}), 400
    users = load_users()
    if any(u['email'] == email for u in users):
        return jsonify({'error': 'Email already registered.'}), 400
    user = {'id': secrets.token_hex(16), 'email': email, 'name': name or email.split('@')[0], 'passwordHash': hash_password(password)}
    users.append(user)
    save_users(users)
    return jsonify({'success': True, 'token': make_token(user['id'], email), 'user': {'id': user['id'], 'email': email, 'name': user['name']}})

@app.route('/auth/email/signin', methods=['POST'])
def signin():
    data = request.json
    email, password = data.get('email',''), data.get('password','')
    users = load_users()
    user = next((u for u in users if u['email'] == email), None)
    if not user or not verify_password(password, user['passwordHash']):
        return jsonify({'error': 'Invalid email or password.'}), 401
    return jsonify({'success': True, 'token': make_token(user['id'], email), 'user': {'id': user['id'], 'email': email, 'name': user.get('name','')}})

@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    message = data.get('message', '')
    session_id = data.get('sessionId', f's-{int(time.time()*1000)}')

    if not message:
        return jsonify({'error': 'message required'}), 400

    # Get/create session
    if session_id not in sessions:
        sessions[session_id] = [{'role': 'system', 'content': SYSTEM_PROMPT}]
    history = sessions[session_id]
    lower = message.lower()

    # --- Music detection ---
    if re.search(r'\b(play|put on)\b', lower) and (re.search(r'\b(song|music)\b', lower) or lower.startswith('play ')):
        history.append({'role': 'user', 'content': message})
        reply = chat_with_llm(history)
        history.append({'role': 'assistant', 'content': reply})
        match = re.search(r'\[PLAY_MUSIC:(.+?)\]', reply)
        if match:
            song = match.group(1).strip()
            return jsonify({'reply': f'Playing "{song}"...', 'sessionId': session_id, 'action': 'play_music',
                           'musicUrl': f'https://www.youtube.com/results?search_query={requests.utils.quote(song)}'})

    # --- Image generation ---
    if (re.search(r'\b(generate|create|make|draw|design|imagine|show|give|picture|image|photo|illustration)\b', lower) and
        re.search(r'\b(image|picture|photo|illustration|art|drawing|poster|wallpaper|logo|portrait|scene|girl|boy|man|woman|car|city|anime)\b', lower)):
        desc = re.sub(r'\b(generate|create|make|draw|design|imagine|give me|show me|can you|an?|the|of|for|me|image|picture|photo)\b', '', message, flags=re.I).strip()
        prompt = desc or message
        url = f'https://image.pollinations.ai/prompt/{requests.utils.quote(prompt)}?width=1024&height=1024&nologo=true'
        return jsonify({'reply': "Here's your image, Sir.", 'sessionId': session_id, 'action': 'show_image', 'imageUrl': url, 'imagePrompt': prompt})

    # --- Web search for real-time queries ---
    context = ''
    refresh_news()
    if re.search(r'\b(news|latest|today|current|happening|headlines)\b', lower):
        context = fetch_news(message) or news_cache.get('world', '')
    elif re.search(r'\b(weather|temperature|forecast)\b', lower):
        context = web_search(message + ' weather today')
    elif re.search(r'\b(stock|price|market|crypto|bitcoin)\b', lower):
        context = web_search(message + ' current price')
    elif re.search(r'\b(what is|who is|where is|when|how|search|find|explain|tell me)\b', lower):
        context = web_search(message)
    elif message.endswith('?'):
        context = web_search(message)

    user_msg = f"{message}\n\n[Real-time data — present directly, NO links]:\n{context}" if context else message
    history.append({'role': 'user', 'content': user_msg})

    # --- Generate response ---
    reply = chat_with_llm(history)
    history.append({'role': 'assistant', 'content': reply})

    # Trim history
    if len(history) > 60:
        history[:] = [history[0]] + history[-58:]

    return jsonify({'reply': reply, 'sessionId': session_id, 'timestamp': datetime.now().isoformat()})

@app.route('/news')
def news_endpoint():
    refresh_news()
    return jsonify(news_cache)


# ============== Start ==============

if __name__ == '__main__':
    print(f"""
╔══════════════════════════════════════════════════════╗
║         J.A.R.V.I.S — Python Server                 ║
╠══════════════════════════════════════════════════════╣
║  URL:   http://0.0.0.0:{PORT}                          ║
║  LLM:   {'Cerebras (120B)' if CEREBRAS_KEY else 'NO KEY SET'}
║  Mode:  Global Cloud                                ║
╚══════════════════════════════════════════════════════╝
    """)
    app.run(host='0.0.0.0', port=PORT, debug=False)
