"""
F.R.I.D.A.Y - Personal AI Assistant
Main application with proper security, rate limiting, and observability.
"""

from __future__ import annotations

import re
import time
import sys
import traceback

# Create Flask app FIRST before any other imports that might fail
from flask import Flask, request, jsonify, send_from_directory, Response
app = Flask(__name__, static_folder="public", static_url_path="")

# Store import errors for debugging
_import_errors = []

# Basic imports
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
except Exception as e:
    _import_errors.append(f"flask_limiter: {e}")
    Limiter = None
    get_remote_address = None

try:
    from loguru import logger
except Exception as e:
    _import_errors.append(f"loguru: {e}")
    import logging
    logger = logging.getLogger(__name__)

# Wrap all custom imports in try/except for debugging on Vercel
PORT = 7860
ISO_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
try:
    from friday.config import PORT, ISO_TIMESTAMP_FORMAT
except Exception as e:
    _import_errors.append(f"friday.config: {e}\n{traceback.format_exc()}")

try:
    from friday.system_prompt import get_system_prompt
except Exception as e:
    _import_errors.append(f"friday.system_prompt: {e}")
    def get_system_prompt():
        return "You are FRIDAY, a helpful AI assistant."

# Critical imports - these will cause app to fail if not available
llm = search = news = auth = music = memory = image = rag = mcp = video = agents = planner = long_memory = research = maps = None
try:
    from friday.modules import llm, search, news, auth, music, memory, image, rag, mcp, video, agents, planner, long_memory, research, maps
except Exception as e:
    _import_errors.append(f"friday.modules: {e}\n{traceback.format_exc()}")

require_auth = None
get_current_user_id = None
try:
    from friday.modules.auth import require_auth, get_current_user_id
except Exception as e:
    _import_errors.append(f"friday.modules.auth: {e}")

# Fallback decorators if auth module failed to load
if require_auth is None:
    def require_auth(f):
        """No-op decorator when auth is not available."""
        return f

if get_current_user_id is None:
    def get_current_user_id():
        """Return a default user ID when auth is not available."""
        return "anonymous"

# Try to import tool_calling module - make it optional for backward compatibility
_TOOL_CALLING_AVAILABLE = False
format_music_response = format_music_control_response = format_map_view_response = None
format_directions_response = format_image_response = format_video_response = format_research_response = None
ToolRegistry = FallbackRouter = IntentRouter = None
try:
    from friday.modules.tool_calling import (
        ToolRegistry,
        FallbackRouter,
        IntentRouter,
        format_music_response,
        format_music_control_response,
        format_map_view_response,
        format_directions_response,
        format_image_response,
        format_video_response,
        format_research_response,
    )
    _TOOL_CALLING_AVAILABLE = True
    logger.info("Tool calling module loaded successfully")
except Exception as e:
    _import_errors.append(f"friday.modules.tool_calling: {e}")


# ===== Diagnostic endpoint - MUST be first to debug issues =====
@app.route("/debug")
def debug_endpoint():
    """Simple diagnostic endpoint that doesn't depend on any imports."""
    return jsonify({
        "status": "ok",
        "python_version": sys.version,
        "tool_calling_available": _TOOL_CALLING_AVAILABLE,
        "import_errors": _import_errors,
        "modules_loaded": {
            "llm": llm is not None,
            "auth": auth is not None,
            "music": music is not None,
            "memory": memory is not None,
        }
    })


# ===== Intent Router Initialization (loaded once at startup per Requirement 9.4) =====

def _create_music_play_handler():
    """Create handler for music_play tool."""
    def handler(session_id: str, user_id: str, song_query: str, **kwargs) -> dict:
        """Search for and play music based on the song query."""
        results = music.search_tracks(song_query, max_results=10)
        if results:
            track = results[0]
            memory.save_message(user_id, session_id, "user", f"play {song_query}")
            memory.save_message(user_id, session_id, "assistant", f'Playing {track["title"]} by {track["artist"]}')
            return format_music_response(
                reply=f'Playing "{track["title"]}" by {track["artist"]}...',
                session_id=session_id,
                track=track,
            )
        else:
            memory.save_message(user_id, session_id, "user", f"play {song_query}")
            return {
                "reply": "Sorry, I couldn't find that song. Try a different search.",
                "sessionId": session_id,
            }
    return handler


def _create_music_control_handler():
    """Create handler for music_control tool."""
    def handler(session_id: str, user_id: str, action: str, **kwargs) -> dict:
        """Handle music playback control commands."""
        control_replies = {
            "pause": "Music paused, Sir. Standing by.",
            "resume": "Resuming playback, Sir.",
            "stop": "Playback stopped, Sir.",
            "next": "Skipping to the next track, Sir.",
            "previous": "Going back to the previous track, Sir.",
        }
        memory.save_message(user_id, session_id, "user", action)
        return format_music_control_response(
            reply=control_replies.get(action, f"Executing {action} command."),
            session_id=session_id,
            control=action,
        )
    return handler


def _create_map_view_handler():
    """Create handler for map_view tool."""
    def handler(session_id: str, user_id: str, place: str, **kwargs) -> dict:
        """Display a map of the specified location."""
        memory.save_message(user_id, session_id, "user", f"map of {place}")
        reply = f"Here is the map of {place}, Sir." if place else "Here is the map, Sir."
        return format_map_view_response(
            reply=reply,
            session_id=session_id,
            place=place,
        )
    return handler


def _create_directions_handler():
    """Create handler for directions tool."""
    def handler(session_id: str, user_id: str, destination: str, origin: str = "", **kwargs) -> dict:
        """Get directions between two locations."""
        memory.save_message(user_id, session_id, "user", f"directions from {origin} to {destination}")
        if origin:
            reply = f"Plotting a route from {origin} to {destination}, Sir."
        else:
            reply = f"Getting directions to {destination}, Sir."
        return format_directions_response(
            reply=reply,
            session_id=session_id,
            origin=origin,
            destination=destination,
        )
    return handler


def _create_image_generate_handler():
    """Create handler for image_generate tool."""
    def handler(session_id: str, user_id: str, prompt: str, **kwargs) -> dict:
        """Generate an image from a text description."""
        url = image.generate_image_url(prompt)
        memory.save_message(user_id, session_id, "user", prompt)
        return format_image_response(
            reply="Here's your image, Sir.",
            session_id=session_id,
            image_url=url,
            image_prompt=prompt,
        )
    return handler


def _create_video_generate_handler():
    """Create handler for video_generate tool."""
    def handler(session_id: str, user_id: str, prompt: str, **kwargs) -> dict:
        """Generate a video from a text description."""
        resp = video.get_video_response(prompt)
        memory.save_message(user_id, session_id, "user", prompt)
        return format_video_response(
            reply=resp.get("reply", "Generating your video, Sir."),
            session_id=session_id,
            video_url=resp.get("videoUrl", ""),
            video_prompt=prompt,
        )
    return handler


def _create_research_handler():
    """Create handler for research tool."""
    def handler(session_id: str, user_id: str, topic: str, **kwargs) -> dict:
        """Conduct deep research on a topic."""
        result = research.generate_research_report(topic)
        memory.save_message(user_id, session_id, "user", topic)
        memory.save_message(user_id, session_id, "assistant", f"Research: {topic}")
        return format_research_response(
            reply=f"Research complete. {result['sources_count']} sources in {result['time_taken']}.",
            session_id=session_id,
            report=result["report"],
            topic=result["topic"],
            meta={
                "sources": result["sources_count"],
                "news": result["news_count"],
                "time": result["time_taken"],
            },
        )
    return handler


def _create_web_search_handler():
    """Create handler for web_search tool."""
    def handler(session_id: str, user_id: str, query: str, **kwargs) -> dict:
        """Search the web for information."""
        result = search.web_search(query)
        return {
            "reply": result or "No results found.",
            "sessionId": session_id,
            "action": "search_result",
            "query": query,
        }
    return handler


def _create_news_handler():
    """Create handler for news tool."""
    def handler(session_id: str, user_id: str, topic: str = "", **kwargs) -> dict:
        """Get latest news on a topic."""
        news.refresh_cache()
        if topic:
            result = news.fetch_news(topic) or news.get_cached_news("world")
        else:
            result = news.get_cached_news("world")
        return {
            "reply": result or "No news available.",
            "sessionId": session_id,
            "action": "news_result",
            "topic": topic or "world",
        }
    return handler


def _create_weather_handler():
    """Create handler for weather tool."""
    def handler(session_id: str, user_id: str, location: str, **kwargs) -> dict:
        """Get weather for a location."""
        result = search.web_search(f"{location} weather today")
        return {
            "reply": result or f"Could not get weather for {location}.",
            "sessionId": session_id,
            "action": "weather_result",
            "location": location,
        }
    return handler


def _create_stock_handler():
    """Create handler for stock tool."""
    def handler(session_id: str, user_id: str, symbol: str, **kwargs) -> dict:
        """Get stock or crypto price information."""
        result = search.web_search(f"{symbol} current price")
        return {
            "reply": result or f"Could not get price for {symbol}.",
            "sessionId": session_id,
            "action": "stock_result",
            "symbol": symbol,
        }
    return handler


def _initialize_intent_router() -> IntentRouter:
    """Initialize the IntentRouter with all capability handlers.
    
    This is called once at application startup per Requirement 9.4.
    """
    tool_registry = ToolRegistry.get_instance()
    fallback_router = FallbackRouter()
    intent_router = IntentRouter(tool_registry, llm, fallback_router)
    
    # Register all capability handlers
    intent_router.register_handler("music_play", _create_music_play_handler())
    intent_router.register_handler("music_control", _create_music_control_handler())
    intent_router.register_handler("map_view", _create_map_view_handler())
    intent_router.register_handler("directions", _create_directions_handler())
    intent_router.register_handler("image_generate", _create_image_generate_handler())
    intent_router.register_handler("video_generate", _create_video_generate_handler())
    intent_router.register_handler("research", _create_research_handler())
    intent_router.register_handler("web_search", _create_web_search_handler())
    intent_router.register_handler("news", _create_news_handler())
    intent_router.register_handler("weather", _create_weather_handler())
    intent_router.register_handler("stock", _create_stock_handler())
    
    logger.info("IntentRouter initialized with all capability handlers")
    return intent_router


# Initialize the IntentRouter lazily at first request to avoid import-time failures on Vercel
_intent_router = None


def _get_intent_router():
    """Get or create the IntentRouter singleton.
    
    Uses lazy initialization to avoid import-time failures in serverless environments.
    Thread-safe via Python's GIL for simple assignment.
    Returns None if tool_calling module is not available.
    """
    global _intent_router
    if not _TOOL_CALLING_AVAILABLE:
        return None
    if _intent_router is None:
        _intent_router = _initialize_intent_router()
    return _intent_router


# --- Music Search Engine (lazy singleton) ---
_search_engine = None


def _get_search_engine():
    """Lazy-initialize and return the SearchEngine singleton."""
    global _search_engine
    if _search_engine is None:
        from friday.modules.music_language import LanguageProcessor
        from friday.modules.music_fuzzy import FuzzyMatcher
        from friday.modules.music_catalog import CatalogCache
        from friday.modules.music_aggregator import MusicAggregator
        from friday.modules.music_autocomplete import AutocompleteService
        from friday.modules.music_search_engine import SearchEngine
        from friday.modules.music_youtube_adapter import YouTubeAdapter
        from friday.modules.music_jiosaavn_adapter import JioSaavnAdapter
        from friday.modules.music_gaana_adapter import GaanaAdapter

        catalog_cache = CatalogCache()
        language_processor = LanguageProcessor()
        fuzzy_matcher = FuzzyMatcher(catalog_cache)
        adapters = [YouTubeAdapter(), JioSaavnAdapter(), GaanaAdapter()]
        aggregator = MusicAggregator(adapters)
        autocomplete_service = AutocompleteService(aggregator)
        _search_engine = SearchEngine(language_processor, fuzzy_matcher, aggregator, autocomplete_service)
    return _search_engine

# Rate limiting
if Limiter is not None and get_remote_address is not None:
    limiter = Limiter(get_remote_address, app=app, default_limits=["60 per minute"], storage_uri="memory://")
else:
    limiter = None


def rate_limit(limit_string):
    """Decorator that applies rate limiting if limiter is available, otherwise no-op."""
    def decorator(f):
        if limiter is not None:
            return limiter.limit(limit_string)(f)
        return f
    return decorator

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
    from friday.db import USE_TURSO
    
    health_data = {
        "status": "running",
        "version": "2.1",
        "auth": "JWT",
        "rateLimit": "30/min on chat",
        "database": "turso" if USE_TURSO else "local_sqlite",
        "tool_calling_available": _TOOL_CALLING_AVAILABLE,
    }
    
    # Get routing metrics from MetricsCollector if tool_calling is available
    if _TOOL_CALLING_AVAILABLE:
        try:
            from friday.modules.tool_calling.metrics import MetricsCollector
            metrics_collector = MetricsCollector.get_instance()
            routing_metrics = metrics_collector.get_metrics()
            health_data.update({
                "tool_selection_success_rate": round(routing_metrics.success_rate, 2),
                "fallback_rate": round(routing_metrics.fallback_rate, 2),
                "average_latency_ms": round(routing_metrics.average_latency_ms, 2),
            })
        except Exception as e:
            logger.warning(f"Could not get routing metrics: {e}")
    
    return jsonify(health_data)


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

@app.route("/auth/email/verify-otp", methods=["POST"])
def verify_otp():
    data = request.json or {}
    result = auth.verify_otp(data.get("email", ""), data.get("code", ""))
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

@app.route("/auth/dev-login", methods=["POST"])
def dev_login():
    result = auth.dev_login()
    if "error" in result:
        return jsonify(result), 403
    return jsonify({"success": True, **result})

@app.route("/login", methods=["POST"])
def login_alias():
    return signin()


# ===== Chat (rate limited) =====

@app.route("/chat", methods=["POST"])
@rate_limit("30 per minute")
@require_auth
def chat():
    data = request.json or {}
    message: str = data.get("message", "")
    session_id: str = data.get("sessionId", f"s-{int(time.time()*1000)}")
    user_id: str = get_current_user_id()
    # Developer-mode overrides (validated inside llm.generate; invalid -> ignored)
    req_model = data.get("model")
    req_temp = data.get("temperature")

    if not message:
        return jsonify({"error": "message required"}), 400

    # Get/create session
    if session_id not in sessions:
        sessions[session_id] = [{"role": "system", "content": get_cached_prompt()}]
    history = sessions[session_id]
    lower = message.lower()

    # --- Use IntentRouter for tool-based routing (if available) ---
    # This replaces the regex-based routing cascade (Requirements 3.1, 4.1-4.8)
    if _TOOL_CALLING_AVAILABLE:
        try:
            routing_result = _get_intent_router().route(message, session_id, user_id)
            
            # If a capability handler processed the request, return its response
            if routing_result.handler_used != "default_chat":
                # For non-chat handlers, the response is already formatted
                # Log routing metrics
                logger.debug(
                    f"IntentRouter: handler={routing_result.handler_used} "
                    f"fallback={routing_result.is_fallback} "
                    f"latency_ms={routing_result.latency_ms:.2f}"
                )
                return jsonify(routing_result.response)
        except Exception as e:
            logger.warning(f"IntentRouter error, falling back to default chat: {e}")

    # --- Default chat flow (when no tool was selected) ---
    # Context enrichment for general chat
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
        reply = llm.generate(history, model=req_model, temperature=req_temp)

    history.append({"role": "assistant", "content": reply})

    # Trim history
    if len(history) > 60:
        history[:] = [history[0]] + history[-58:]

    # Persist synchronously — background threads don't survive on serverless (Vercel)
    _background_save(user_id, session_id, message, reply)

    return jsonify({"reply": reply, "sessionId": session_id, "timestamp": time.strftime(ISO_TIMESTAMP_FORMAT)})


# ===== Streaming Chat =====

@app.route("/chat/stream", methods=["POST"])
@rate_limit("30 per minute")
@require_auth
def chat_stream():
    data = request.json or {}
    message: str = data.get("message", "")
    session_id: str = data.get("sessionId", f"s-{int(time.time()*1000)}")

    if not message:
        return jsonify({"error": "message required"}), 400

    req_model = data.get("model")
    req_temp = data.get("temperature")

    if session_id not in sessions:
        sessions[session_id] = [{"role": "system", "content": get_cached_prompt()}]
    history = sessions[session_id]
    history.append({"role": "user", "content": message})

    def generate():
        full = ""
        for token in llm.stream_generate(history, model=req_model, temperature=req_temp):
            full += token
            yield f"data: {token}\n\n"
        history.append({"role": "assistant", "content": full})
        yield "data: [DONE]\n\n"

    return Response(generate(), mimetype="text/event-stream")


@app.route("/models", methods=["GET"])
@require_auth
def list_models():
    """Expose the available model allowlist + defaults for the dev context panel."""
    from friday.config import LLM_MODELS, LLM_TEMPERATURE
    return jsonify({
        "models": LLM_MODELS,
        "default": LLM_MODELS[0] if LLM_MODELS else None,
        "temperature": LLM_TEMPERATURE,
    })


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

@app.route("/music/autocomplete", methods=["GET"])
@require_auth
def music_autocomplete():
    query = request.args.get("q", "")
    engine = _get_search_engine()
    suggestions = engine.autocomplete(query)
    return jsonify({
        "suggestions": [
            {"title": s.title, "artist": s.artist, "thumbnail_url": s.thumbnail_url, "video_id": s.video_id, "source": s.source}
            for s in suggestions
        ]
    })

@app.route("/music/search", methods=["GET"])
@require_auth
def music_search():
    query = request.args.get("q", "").strip()
    engine = _get_search_engine()

    error = engine.validate_query(query)
    if error:
        return jsonify({"error": error}), 400

    try:
        result = engine.search(query)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error("Music search error for query '{}': {}", query, e)
        return jsonify({"error": "Search temporarily unavailable. Please try again."}), 503

    # If all sources failed and no results, return 503
    if not result.results and result.sources_failed and len(result.sources_failed) == len(result.sources_queried):
        return jsonify({"error": "All music sources are temporarily unavailable. Please try again."}), 503

    # Convert to backward-compatible format (list of dicts with video_id, title, artist, thumbnail_url) + new fields
    results_list = [
        {
            "video_id": t.id,
            "title": t.title,
            "artist": t.artist,
            "thumbnail_url": t.thumbnail_url,
            "source": t.source,
            "source_url": t.source_url,
            "duration_seconds": t.duration_seconds,
            "is_devotional": t.is_devotional,
            "tradition": t.tradition,
            "match_score": t.match_score,
        }
        for t in result.results
    ]

    response = {
        "results": results_list,
        "query": query,
    }
    if result.correction:
        response["correction"] = result.correction
    if result.devotional_context:
        response["devotional_context"] = result.devotional_context

    return jsonify(response)

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
    import os
    # Bind to 0.0.0.0 only in container/cloud environments (Vercel, Docker, Railway)
    # Default to localhost for local development (avoids exposing to all interfaces)
    host = os.getenv("HOST", "127.0.0.1")
    logger.info(f"FRIDAY v2.1 starting on {host}:{PORT}")
    app.run(host=host, port=PORT, debug=False)
