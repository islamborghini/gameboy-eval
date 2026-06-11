"""Model provider layer: local Ollama by default, OpenAI-compatible if configured.

Swappable so a free/capable API tier drops in unchanged:
  - default: Ollama at $OLLAMA_URL (http://127.0.0.1:11434)
  - set $OPENAI_BASE_URL (+ $OPENAI_API_KEY) to use any OpenAI-compatible endpoint
"""
from __future__ import annotations

import json
import os
import urllib.request

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")


def chat(messages: list[dict], model: str, temperature: float = 0.2,
         num_ctx: int = 16384, timeout: int = 900) -> str:
    base = os.environ.get("OPENAI_BASE_URL")
    if base:
        return _openai_chat(messages, model, temperature, base, timeout)
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


def _openai_chat(messages, model, temperature, base, timeout) -> str:
    key = os.environ.get("OPENAI_API_KEY", "")
    res = _post(
        base.rstrip("/") + "/chat/completions",
        {"model": model, "messages": messages, "temperature": temperature},
        {"Authorization": f"Bearer {key}"}, timeout,
    )
    return res["choices"][0]["message"]["content"]
