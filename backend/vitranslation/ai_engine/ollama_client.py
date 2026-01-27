# vitranslation/ai_engine/ollama_client.py
from __future__ import annotations

import json
import requests
from typing import Generator, Optional

from .config import OLLAMA_URL, OLLAMA_TIMEOUT, OLLAMA_MODEL

_http = requests.Session()
_cached_model: Optional[str] = None

def pick_model() -> str:
    """
    If env OLLAMA_MODEL set -> use it.
    Else -> query /api/tags and pick best available by priority.
    """
    global _cached_model
    if OLLAMA_MODEL:
        return OLLAMA_MODEL
    if _cached_model:
        return _cached_model

    url = f"{OLLAMA_URL}/api/tags"
    r = _http.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    names = [m.get("name", "") for m in data.get("models", []) if m.get("name")]

    priority = [
        "qwen2.5:32b", "qwen2.5:14b", "qwen2.5:7b",
        "llama3.1:70b", "llama3.1:8b", "llama3:8b",
        "gemma2:27b", "gemma2:9b",
        "mistral:7b",
    ]
    for p in priority:
        if p in names:
            _cached_model = p
            return p

    _cached_model = names[0] if names else "qwen2.5:14b"
    return _cached_model

def generate(prompt: str, model: str | None = None) -> str:
    url = f"{OLLAMA_URL}/api/generate"
    payload = {
        "model": model or pick_model(),
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2},
    }
    r = _http.post(url, json=payload, timeout=OLLAMA_TIMEOUT)
    r.raise_for_status()
    return (r.json().get("response") or "").strip()

def generate_stream(prompt: str, model: str | None = None) -> Generator[str, None, None]:
    url = f"{OLLAMA_URL}/api/generate"
    payload = {
        "model": model or pick_model(),
        "prompt": prompt,
        "stream": True,
        "options": {"temperature": 0.2},
    }
    with _http.post(url, json=payload, stream=True, timeout=OLLAMA_TIMEOUT) as r:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            obj = json.loads(line)
            chunk = obj.get("response") or ""
            if chunk:
                yield chunk
            if obj.get("done") is True:
                break
