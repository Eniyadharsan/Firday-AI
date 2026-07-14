"""
J.A.R.V.I.S — Personal AI Assistant
Main application entry point.
"""

import re
import time
from flask import Flask, request, jsonify, send_from_directory, Response
from loguru import logger

from jarvis.config import PORT
from jarvis.system_prompt import get_system_prompt
from jarvis.modules import llm, search, news, auth, music, memory, image

app = Flask(__name__, static_folder="public", static_url_path="")

# --- In-memory session store (for quick access; persisted to SQLite) ---
sessions: dict[str, list[dict[str, str]]] = {}


# ============== Static / Health ==============

@app.route("/")
def index():
    return send_from_directory("public", "index.html")

@app.route("/<path:path>")
def static_files(path: str):
    return send_from_directory("public", path)

@app.route("/health")
def health():
    return jsonify({"status": "running", "version": "2.0", "llm": "Cerebras 120B"})


# ============== Auth Routes ==============

@app.route("/auth/status")
def auth_status():
    return jsonify({"needsSetup": False})

@app.route("/auth/email/signup", methods=["POST"])
def signup():
    data = request.json or {}
    result = auth.signup(data.get("email", ""), data.get("password", ""), data.get("name", ""))
    if "error" in result:
        return jsonify(result), 400
    return jsonify({"success": True, **result})

@app.route("/auth/email/signin", methods=["POST"])
def signin():
    data = request.json or {}
    result = auth.signin(data.get("email", ""), data.get("password", ""))
    if "error" in result:
        return jsonify(result), 401
    return jsonify({"success": True, **result})

@app.route("/login", methods=["POST"])
def login_alias():
    """Alias for signin."""
    return signin()


# ============== Chat ==============

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json or {}
    message: str = data.get("message", "")
    session_id: str = data.get("sessionId", f"s-{int(time.time()*1000)}")
    user_id: str = data.get("userId", "default")

    if not message:
        return jsonify({"error": "message required"}), 400

    # Get/create session
    if session_id not in sessions:
        sessions[session_id] = [{"role": "system", "content": get_system_prompt()}]
    history = sessions[session_id]
    lower = message.lower()

    # --- Music ---
    if music.is_music_request(message):
        history.append({"role": "user", "content": message})
        reply = llm.generate(history)
        history.append({"role": "assistant", "content": reply})
        song = music.extract_song_from_reply(reply)
        if song:
            memory.save_message(user_id, session_id, "user", message)
            memory.save_message(user_id, session_id, "assistant", f"Playing {song}")
            return jsonify({"reply": f'Playing "{song}"...', "sessionId": session_id, "action": "play_music", "musicUrl": music.get_youtube_url(song)})

    # --- Image ---
    if image.is_image_request(message):
        url = image.generate_image_url(message)
        memory.save_message(user_id, session_id, "user", message)
        memory.save_message(user_id, session_id, "assistant", f"Generated image: {message}")
        return jsonify({"reply": "Here's your image, Sir.", "sessionId": session_id, "action": "show_image", "imageUrl": url, "imagePrompt": message})

    # --- Context enrichment (only for clear real-time needs) ---
    context = ""
    if re.search(r"\b(news|latest|today|current|happening|headlines|breaking)\b", lower):
        news.refresh_cache()
        context = news.fetch_news(message) or news.get_cached_news("world")
    elif re.search(r"\b(weather|temperature|forecast)\b", lower):
        context = search.web_search(message + " weather today")
    elif re.search(r"\b(stock|price|market|crypto|bitcoin)\b", lower):
        context = search.web_search(message + " current price")
    elif re.search(r"\b(who is|where is|when did|when was)\b", lower) and len(message) < 80:
        context = search.web_search(message)

    user_msg = f"{message}\n\n[Real-time data — present directly, NO links]:\n{context}" if context else message
    history.append({"role": "user", "content": user_msg})

    # --- Generate ---
    reply = llm.generate(history)
    history.append({"role": "assistant", "content": reply})

    # Trim history
    if len(history) > 60:
        history[:] = [history[0]] + history[-58:]

    # Persist to SQLite
    memory.save_message(user_id, session_id, "user", message)
    memory.save_message(user_id, session_id, "assistant", reply)

    return jsonify({"reply": reply, "sessionId": session_id, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")})


# ============== Streaming Chat ==============

@app.route("/chat/stream", methods=["POST"])
def chat_stream():
    """Stream LLM response token by token."""
    data = request.json or {}
    message: str = data.get("message", "")
    session_id: str = data.get("sessionId", f"s-{int(time.time()*1000)}")

    if not message:
        return jsonify({"error": "message required"}), 400

    if session_id not in sessions:
        sessions[session_id] = [{"role": "system", "content": get_system_prompt()}]
    history = sessions[session_id]
    history.append({"role": "user", "content": message})

    def generate():
        full_reply = ""
        for token in llm.stream_generate(history):
            full_reply += token
            yield f"data: {token}\n\n"
        history.append({"role": "assistant", "content": full_reply})
        yield "data: [DONE]\n\n"

    return Response(generate(), mimetype="text/event-stream")


# ============== Search ==============

@app.route("/search", methods=["POST"])
def search_endpoint():
    data = request.json or {}
    query: str = data.get("query", "")
    if not query:
        return jsonify({"error": "query required"}), 400
    result = search.web_search(query)
    return jsonify({"result": result, "query": query})


# ============== News ==============

@app.route("/news")
def news_endpoint():
    news.refresh_cache()
    return jsonify({"world": news.get_cached_news("world"), "tech": news.get_cached_news("tech"), "business": news.get_cached_news("business")})


# ============== Image ==============

@app.route("/image", methods=["POST"])
def image_endpoint():
    data = request.json or {}
    prompt: str = data.get("prompt", "")
    if not prompt:
        return jsonify({"error": "prompt required"}), 400
    url = image.generate_image_url(prompt)
    return jsonify({"imageUrl": url, "prompt": prompt})


# ============== Music ==============

@app.route("/music", methods=["POST"])
def music_endpoint():
    data = request.json or {}
    song: str = data.get("song", "")
    if not song:
        return jsonify({"error": "song required"}), 400
    return jsonify({"musicUrl": music.get_youtube_url(song), "song": song})


# ============== Memory ==============

@app.route("/memory", methods=["GET"])
def get_memories():
    user_id = request.args.get("userId", "default")
    return jsonify({"memories": memory.get_memories(user_id)})

@app.route("/memory", methods=["POST"])
def add_mem():
    data = request.json or {}
    return jsonify(memory.add_memory(data.get("userId", "default"), data.get("content", ""), data.get("category", "general")))


# ============== Start ==============

if __name__ == "__main__":
    logger.info(f"JARVIS starting on port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
