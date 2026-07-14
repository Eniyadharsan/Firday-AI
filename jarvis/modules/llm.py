"""LLM module — communicates with Cerebras AI."""

import requests
from loguru import logger
from jarvis.config import CEREBRAS_API_KEY, LLM_MODELS, LLM_MAX_TOKENS, LLM_TEMPERATURE


def generate(messages: list[dict[str, str]]) -> str:
    """Generate a response from the LLM with model fallback."""
    if not CEREBRAS_API_KEY:
        return "JARVIS needs CEREBRAS_API_KEY to function."

    for model in LLM_MODELS:
        try:
            response = requests.post(
                "https://api.cerebras.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {CEREBRAS_API_KEY}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "max_tokens": LLM_MAX_TOKENS, "temperature": LLM_TEMPERATURE},
                timeout=20,
            )
            if response.status_code == 429:
                logger.warning(f"Rate limited on {model}, trying fallback...")
                continue
            if response.status_code == 401:
                logger.error("Invalid API key")
                continue
            if response.status_code >= 500:
                logger.error(f"Server error on {model}: {response.status_code}")
                continue
            response.raise_for_status()
            data = response.json()
            return data.get("choices", [{}])[0].get("message", {}).get("content", "No response.")
        except requests.Timeout:
            logger.warning(f"Timeout on {model}")
            continue
        except requests.HTTPError as e:
            logger.error(f"HTTP error: {e}")
            continue
        except Exception as e:
            logger.error(f"LLM error: {e}")
            continue

    return "AI temporarily unavailable. Try again in a moment."


def stream_generate(messages: list[dict[str, str]]):
    """Stream tokens from LLM (generator)."""
    if not CEREBRAS_API_KEY:
        yield "JARVIS needs CEREBRAS_API_KEY."
        return

    model = LLM_MODELS[0]
    try:
        response = requests.post(
            "https://api.cerebras.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {CEREBRAS_API_KEY}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "max_tokens": LLM_MAX_TOKENS, "temperature": LLM_TEMPERATURE, "stream": True},
            timeout=60,
            stream=True,
        )
        response.raise_for_status()
        for line in response.iter_lines():
            if line:
                text = line.decode("utf-8")
                if text.startswith("data: ") and text != "data: [DONE]":
                    import json
                    chunk = json.loads(text[6:])
                    delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if delta:
                        yield delta
    except Exception as e:
        logger.error(f"Stream error: {e}")
        yield "Error generating response."
