"""LLM module — communicates with Cerebras AI.

Optimized for low latency:
- Persistent HTTP session with connection pooling
- Reduced timeout (12s instead of 20s) for faster fallback
- json import at module level (not per-chunk in streaming)
"""

import json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from loguru import logger
from jarvis.config import CEREBRAS_API_KEY, LLM_MODELS, LLM_MAX_TOKENS, LLM_TEMPERATURE

API_URL = "https://api.cerebras.ai/v1/chat/completions"

# Connection pool — reuse TCP/TLS connections
_session = requests.Session()
_session.headers.update({
    "Authorization": f"Bearer {CEREBRAS_API_KEY}",
    "Content-Type": "application/json",
})
_adapter = HTTPAdapter(
    pool_connections=5,
    pool_maxsize=10,
    max_retries=Retry(total=1, backoff_factor=0.3, status_forcelist=[502, 503, 504]),
)
_session.mount("https://", _adapter)


def generate(messages: list[dict[str, str]], max_tokens: int = None) -> str:
    """Generate a response from the LLM with model fallback.
    
    Args:
        messages: Chat messages in OpenAI format
        max_tokens: Override default max_tokens (useful for short replies)
    """
    if not CEREBRAS_API_KEY:
        return "JARVIS needs CEREBRAS_API_KEY to function."

    tokens = max_tokens or LLM_MAX_TOKENS

    for model in LLM_MODELS:
        try:
            response = _session.post(
                API_URL,
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": tokens,
                    "temperature": LLM_TEMPERATURE,
                },
                timeout=12,
            )
            if response.status_code == 429:
                logger.warning(f"Rate limited on {model}, trying fallback...")
                continue
            if response.status_code == 401:
                logger.error("Invalid API key")
                return "API key error. Check CEREBRAS_API_KEY."
            if response.status_code >= 500:
                logger.error(f"Server error on {model}: {response.status_code}")
                continue
            response.raise_for_status()
            data = response.json()
            return data.get("choices", [{}])[0].get("message", {}).get("content", "No response.")
        except requests.Timeout:
            logger.warning(f"Timeout on {model}")
            continue
        except Exception as e:
            logger.error(f"LLM error on {model}: {e}")
            continue

    return "AI temporarily unavailable. Try again in a moment."


def stream_generate(messages: list[dict[str, str]]):
    """Stream tokens from LLM (generator). Lower perceived latency."""
    if not CEREBRAS_API_KEY:
        yield "JARVIS needs CEREBRAS_API_KEY."
        return

    model = LLM_MODELS[0]
    try:
        response = _session.post(
            API_URL,
            json={
                "model": model,
                "messages": messages,
                "max_tokens": LLM_MAX_TOKENS,
                "temperature": LLM_TEMPERATURE,
                "stream": True,
            },
            timeout=30,
            stream=True,
        )
        response.raise_for_status()
        for line in response.iter_lines():
            if line:
                text = line.decode("utf-8")
                if text.startswith("data: ") and text != "data: [DONE]":
                    try:
                        chunk = json.loads(text[6:])
                        delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if delta:
                            yield delta
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        logger.error(f"Stream error: {e}")
        yield "Error generating response."
