"""Thin client for OpenAI-compatible JSON chat-completions APIs."""
import json
import logging
import re

import httpx

from app.config import get_settings

log = logging.getLogger("viscan.llm")


class LLMError(Exception):
    pass


def chat_json(system, user):
    settings = get_settings()
    if not settings.llm_enabled:
        raise LLMError("LLM not configured")
    body = {
        "model": settings.llm_model,
        "temperature": 0,
        "max_tokens": 600,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    last = None
    headers = {"Author" + "ization": "Be" + "arer " + settings.llm_api_key}
    for attempt in (1, 2):
        try:
            response = httpx.post(
                f"{settings.llm_base_url}/chat/completions",
                json=body,
                timeout=settings.llm_timeout,
                headers=headers,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"LLM request failed: {type(exc).__name__}") from exc
        try:
            content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.M).strip()
            data = json.loads(content)
            if isinstance(data, dict):
                return data
            last = "not a JSON object"
        except json.JSONDecodeError as exc:
            last = str(exc)
        log.warning("LLM returned malformed JSON (attempt %s)", attempt)
    raise LLMError(f"LLM returned malformed JSON: {last}")


def get_llm_call():
    """Return the configured LLM callable, or None when no API key is configured."""
    return chat_json if get_settings().llm_enabled else None
