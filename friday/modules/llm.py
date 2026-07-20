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
from friday.config import CEREBRAS_API_KEY, LLM_MODELS, LLM_MAX_TOKENS, LLM_TEMPERATURE

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


def _resolve_temperature(temperature) -> float:
    """Clamp a requested temperature to a safe range, falling back to default."""
    if temperature is None:
        return LLM_TEMPERATURE
    try:
        return max(0.0, min(1.5, float(temperature)))
    except (TypeError, ValueError):
        return LLM_TEMPERATURE


def _resolve_models(model) -> list[str]:
    """Build the model fallback order, honoring a valid requested model first.

    Only models present in the configured LLM_MODELS allowlist are accepted;
    unknown/invalid requests are ignored and the default order is used.
    """
    if model and isinstance(model, str) and model in LLM_MODELS:
        return [model] + [m for m in LLM_MODELS if m != model]
    return list(LLM_MODELS)


def generate(messages: list[dict[str, str]], max_tokens: int = None,
             model: str = None, temperature: float = None) -> str:
    """Generate a response from the LLM with model fallback.

    Args:
        messages: Chat messages in OpenAI format
        max_tokens: Override default max_tokens (useful for short replies)
        model: Preferred model id (must be in LLM_MODELS, else ignored)
        temperature: Sampling temperature 0-1.5 (clamped; None uses default)
    """
    if not CEREBRAS_API_KEY:
        return "FRIDAY needs CEREBRAS_API_KEY to function."
    if CEREBRAS_API_KEY == "your-cerebras-api-key":
        return "FRIDAY needs a valid CEREBRAS_API_KEY. Get one from cloud.cerebras.ai"

    tokens = max_tokens or LLM_MAX_TOKENS
    temp = _resolve_temperature(temperature)

    for model in _resolve_models(model):
        try:
            response = _session.post(
                API_URL,
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": tokens,
                    "temperature": temp,
                },
                timeout=8,
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


def stream_generate(messages: list[dict[str, str]], model: str = None, temperature: float = None):
    """Stream tokens from LLM (generator). Lower perceived latency."""
    if not CEREBRAS_API_KEY:
        yield "FRIDAY needs CEREBRAS_API_KEY."
        return

    model = _resolve_models(model)[0]
    temp = _resolve_temperature(temperature)
    try:
        response = _session.post(
            API_URL,
            json={
                "model": model,
                "messages": messages,
                "max_tokens": LLM_MAX_TOKENS,
                "temperature": temp,
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
