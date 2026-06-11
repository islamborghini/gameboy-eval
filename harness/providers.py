"""Model provider layer: local Ollama by default; OpenRouter or any OpenAI-compatible API.

Swappable so a free/capable API tier drops in unchanged (pick one; checked in this order):
  - set $OPENROUTER_API_KEY to use OpenRouter (openrouter.ai) — OpenAI-compatible, with
    namespaced model ids like `qwen/qwen-2.5-coder-32b-instruct` (base $OPENROUTER_URL)
  - set $OPENAI_BASE_URL (+ $OPENAI_API_KEY) for any other OpenAI-compatible endpoint
  - default: Ollama at $OLLAMA_URL (http://127.0.0.1:11434)
"""
from __future__ import annotations

import json
import os
import urllib.request

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OPENROUTER_URL = os.environ.get("OPENROUTER_URL", "https://openrouter.ai/api/v1")

# Optional attribution OpenRouter surfaces on its public app-ranking leaderboard.
_OPENROUTER_HEADERS = {"X-Title": "gameboy-eval"}


def chat(messages: list[dict], model: str, temperature: float = 0.2,
         num_ctx: int = 16384, timeout: int = 900) -> str:
    if os.environ.get("OPENROUTER_API_KEY"):
        return _openai_chat(messages, model, temperature, OPENROUTER_URL,
                            os.environ["OPENROUTER_API_KEY"], timeout, _OPENROUTER_HEADERS)
    base = os.environ.get("OPENAI_BASE_URL")
    if base:
        return _openai_chat(messages, model, temperature, base,
                            os.environ.get("OPENAI_API_KEY", ""), timeout)
    return _ollama_chat(messages, model, temperature, num_ctx, timeout)


def _post(url: str, payload: dict, headers: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _ollama_chat(messages, model, temperature, num_ctx, timeout) -> str:
    res = _post(
        OLLAMA_URL + "/api/chat",
        {"model": model, "messages": messages, "stream": False,
         "options": {"temperature": temperature, "num_ctx": num_ctx}},
        {}, timeout,
    )
    return res["message"]["content"]


def _openai_chat(messages, model, temperature, base, key, timeout, extra=None) -> str:
    res = _post(
        base.rstrip("/") + "/chat/completions",
        {"model": model, "messages": messages, "temperature": temperature},
        {"Authorization": f"Bearer {key}", **(extra or {})}, timeout,
    )
    return res["choices"][0]["message"]["content"]
