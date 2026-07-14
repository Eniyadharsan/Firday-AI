"""
J.A.R.V.I.S - Personal AI Assistant
Main application with proper security, rate limiting, and observability.
"""

import re
import time
import threading
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from loguru import logger

from jarvis.config import PORT
from jarvis.system_prompt import get_system_prompt
from jarvis.modules import llm, search, news, auth, music, memory, image, rag, mcp, video, agents, planner, long_memory, research
from jarvis.modules.auth import require_auth, get_current_user_id

app = Flask(__name__, static_folder="public", static_url_path="")

# Rate limiting
limiter = Limiter(get_remote_address, app=app, default_limits=["60 per minute"], storage_uri="memory://")

# Compression
try:
    from flask_compress import Compress
    Compress(app)
except ImportError:
    pass

# Pre-compiled regex patterns for chat routing (avoids recompilation per request)
_RE_NEWS = re.compile(r"\b(news|latest|today|current|happening|headlines)\b")
_RE_WEATHER = re.compile(r"\b(weather|temperature|forecast)\b")
_RE_STOCK = re.compile(r"\b(stock|price|market|crypto)\b")
_RE_FACTUAL = re.compile(r"\b(who is|where is|when did)\b")


def _background_save(user_id: str, session_id: str, message: str, reply: str):
    """Save messages and extract memories in background thread."""
    try:
        memory.save_message(user_id, session_id, "user", message)
        memory.save_message(user_id, session_id, "assistant", reply)
        long_memory.auto_extract(user_id, message)
    except Exception as e:
        logger.error(f"Background save error: {e}")

# Request logging
@app.before_request
def log_request():
    request.start_time = time.time()

@app.after_request
def log_response(response):
    duration = round((time.time() - getattr(request, "start_time", time.time())) * 1000, 1)
    if request.path not in ("/", "/health"):
        logger.info(f"{request.method} {request.path} -> {response.status_code} ({duration}ms)")
    return response

# Session cache (backed by SQLite via memory module)
sessions: dict[str, list[dict[str, str]]] = {}

# Prompt cache
_prompt_cache: tuple[str, float] = ("", 0)

def get_cached_prompt() -> str:
    global _prompt_cache
    now = time.time()
    if now - _prompt_cache[1] < 60:
        return _prompt_cache[0]
    p = get_system_prompt()
    _prompt_cache = (p, now)
    return p


# ===== Static =====

@app.route("/")
def index():
    return send_from_directory("public", "index.html")

@app.route("/<path:path>")
def static_files(path: str):
    return send_from_directory("public", path)

@app.route("/health")
def health():
    from jarvis.db import USE_TURSO
    return jsonify({"status": "running", "version": "2.1", "auth": "JWT", "rateLimit": "30/min on chat", "database": "turso" if USE_TURSO else "local_sqlite"})


# ===== Auth =====

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
    return signin()


# ===== Chat (rate limited) =====

@app.route("/chat", methods=["POST"])
@limiter.limit("30 per minute")
@require_auth
def chat():
    data = request.json or {}
    message: str = data.get("message", "")
    session_id: str = data.get("sessionId", f"s-{int(time.time()*1000)}")
    user_id: str = get_current_user_id()

    if not message:
        return jsonify({"error": "message required"}), 400

    # Get/create session
    if session_id not in sessions:
        sessions[session_id] = [{"role": "system", "content": get_cached_prompt()}]
    history = sessions[session_id]
    lower = message.lower()

    # --- Research mode ---
    if research.is_research_request(message):
        result = research.generate_research_report(message)
        memory.save_message(user_id, session_id, "user", message)
        memory.save_message(user_id, session_id, "assistant", f"Research: {message}")
        return jsonify({"reply": f"Research complete. {result['sources_count']} sources in {result['time_taken']}.", "sessionId": session_id, "action": "show_report", "report": result["report"], "topic": result["topic"], "meta": {"sources": result["sources_count"], "news": result["news_count"], "time": result["time_taken"]}})

    # --- Video ---
    if video.is_video_request(message):
        resp = video.get_video_response(message)
        resp["sessionId"] = session_id
        memory.save_message(user_id, session_id, "user", message)
        return jsonify(resp)

    # --- Music ---
    if music.is_music_request(message):
        history.append({"role": "user", "content": message})
        reply = llm.generate(history)
        history.append({"role": "assistant", "content": reply})
        song = music.extract_song_from_reply(reply) or message.lower().replace("play ", "").replace("put on ", "").replace("queue ", "").strip()

        results = music.search_tracks(song, max_results=10)
        if results:
            track = results[0]
            memory.save_message(user_id, session_id, "user", message)
            memory.save_message(user_id, session_id, "assistant", f'Playing {track["title"]} by {track["artist"]}')
            return jsonify({
                "reply": f'Playing "{track["title"]}" by {track["artist"]}...',
                "sessionId": session_id,
                "action": "play_music_embed",
                "track": track
            })
        else:
            memory.save_message(user_id, session_id, "user", message)
            return jsonify({
                "reply": "Sorry, I couldn't find that song. Try a different search.",
                "sessionId": session_id
            })

    # --- Image ---
    if image.is_image_request(message):
        url = image.generate_image_url(message)
        memory.save_message(user_id, session_id, "user", message)
        return jsonify({"reply": "Here's your image, Sir.", "sessionId": session_id, "action": "show_image", "imageUrl": url, "imagePrompt": message})

    # --- Context enrichment ---
    context = ""
    if _RE_NEWS.search(lower):
        news.refresh_cache()
        context = news.fetch_news(message) or news.get_cached_news("world")
    elif _RE_WEATHER.search(lower):
        context = search.web_search(message + " weather today")
    elif _RE_STOCK.search(lower):
        context = search.web_search(message + " current price")
    elif _RE_FACTUAL.search(lower) and len(message) < 80:
        context = search.web_search(message)

    # RAG context
    rag_context = rag.get_rag_context(user_id, message)
    if rag_context:
        context = f"{context}\n\n{rag_context}" if context else rag_context

    user_msg = f"{message}\n\n[Data — present directly, NO links]:\n{context}" if context else message
    history.append({"role": "user", "content": user_msg})

    # Long-term memory injection
    user_context = long_memory.get_user_context(user_id)
    if user_context:
        history[0]["content"] = get_cached_prompt() + "\n\n" + user_context

    # Multi-agent routing
    agent_id = agents.detect_agent(message)
    if agent_id and len(message) > 20:
        reply = agents.orchestrate(message, history)
    else:
        reply = llm.generate(history)

    history.append({"role": "assistant", "content": reply})

    # Trim history
    if len(history) > 60:
        history[:] = [history[0]] + history[-58:]

    # Persist in background (don't block the response)
    threading.Thread(
        target=_background_save,
        args=(user_id, session_id, message, reply),
        daemon=True,
    ).start()

    return jsonify({"reply": reply, "sessionId": session_id, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")})


# ===== Streaming Chat =====

@app.route("/chat/stream", methods=["POST"])
@limiter.limit("30 per minute")
@require_auth
def chat_stream():
    data = request.json or {}
    message: str = data.get("message", "")
    session_id: str = data.get("sessionId", f"s-{int(time.time()*1000)}")

    if not message:
        return jsonify({"error": "message required"}), 400

    if session_id not in sessions:
        sessions[session_id] = [{"role": "system", "content": get_cached_prompt()}]
    history = sessions[session_id]
    history.append({"role": "user", "content": message})

    def generate():
        full = ""
        for token in llm.stream_generate(history):
            full += token
            yield f"data: {token}\n\n"
        history.append({"role": "assistant", "content": full})
        yield "data: [DONE]\n\n"

    return Response(generate(), mimetype="text/event-stream")


# ===== Search / News / Image / Music / Memory =====

@app.route("/search", methods=["POST"])
@require_auth
def search_endpoint():
    data = request.json or {}
    return jsonify({"result": search.web_search(data.get("query", "")), "query": data.get("query", "")})

@app.route("/news")
def news_endpoint():
    news.refresh_cache()
    return jsonify({"world": news.get_cached_news("world"), "tech": news.get_cached_news("tech"), "business": news.get_cached_news("business")})

@app.route("/image", methods=["POST"])
@require_auth
def image_endpoint():
    data = request.json or {}
    prompt = data.get("prompt", "")
    return jsonify({"imageUrl": image.generate_image_url(prompt), "prompt": prompt})

@app.route("/music", methods=["POST"])
@require_auth
def music_endpoint():
    data = request.json or {}
    return jsonify({"musicUrl": music.get_youtube_url(data.get("song", "")), "song": data.get("song", "")})

@app.route("/music/search", methods=["GET"])
@require_auth
def music_search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "Query parameter 'q' is required"}), 400
    results = music.search_tracks(query, max_results=10)
    return jsonify({"results": results, "query": query})

@app.route("/memory", methods=["GET"])
@require_auth
def get_memories():
    return jsonify({"memories": memory.get_memories(get_current_user_id())})

@app.route("/memory", methods=["POST"])
@require_auth
def add_mem():
    data = request.json or {}
    return jsonify(memory.add_memory(get_current_user_id(), data.get("content", ""), data.get("category", "general")))


# ===== RAG =====

@app.route("/rag/upload", methods=["POST"])
@require_auth
def rag_upload():
    user_id = get_current_user_id()
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No filename"}), 400
    result = rag.upload_document(user_id, file.filename, file.read())
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)

@app.route("/rag/documents", methods=["GET"])
@require_auth
def rag_list():
    return jsonify({"documents": rag.list_documents(get_current_user_id())})

@app.route("/rag/documents/<doc_id>", methods=["DELETE"])
@require_auth
def rag_delete(doc_id: str):
    return jsonify({"success": rag.delete_document(get_current_user_id(), doc_id)})


# ===== MCP =====

@app.route("/mcp", methods=["POST"])
def mcp_endpoint():
    return jsonify(mcp.handle_mcp_request(request.json or {}))

@app.route("/mcp/tools", methods=["GET"])
def mcp_tools():
    return jsonify({"tools": mcp.list_tools()})


# ===== Agents / Planner / History / Profile =====

@app.route("/agents", methods=["GET"])
def list_agents():
    return jsonify({"agents": agents.list_agents()})

@app.route("/plans", methods=["GET"])
@require_auth
def get_plans():
    return jsonify({"plans": planner.get_plans(get_current_user_id())})

@app.route("/plans", methods=["POST"])
@require_auth
def create_plan():
    data = request.json or {}
    return jsonify(planner.generate_plan(get_current_user_id(), data.get("goal", "")))

@app.route("/history", methods=["GET"])
@require_auth
def get_chat_history():
    return jsonify({"sessions": memory.get_all_sessions(get_current_user_id())})

@app.route("/history/<session_id>", methods=["GET"])
@require_auth
def get_session_history(session_id: str):
    return jsonify({"messages": memory.get_history(get_current_user_id(), session_id, limit=100), "sessionId": session_id})

@app.route("/profile", methods=["GET"])
@require_auth
def get_profile():
    return jsonify({"facts": long_memory.get_all_facts(get_current_user_id())})

@app.route("/profile/<int:fact_id>", methods=["DELETE"])
@require_auth
def delete_profile_fact(fact_id: int):
    return jsonify({"success": long_memory.delete_fact(get_current_user_id(), fact_id)})

@app.route("/research", methods=["POST"])
@require_auth
def research_endpoint():
    data = request.json or {}
    return jsonify(research.generate_research_report(data.get("topic", "")))


# ===== Start =====

if __name__ == "__main__":
    logger.info(f"JARVIS v2.1 starting on port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
