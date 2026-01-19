# backend/customer.py
import os
import requests

from opencc import OpenCC

SUPPORTED_LANGS = {"vi", "en", "zh"}

# Groq OpenAI-compatible base
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_STT_URL = f"{GROQ_BASE_URL}/audio/transcriptions"

# STT model on Groq (per Groq STT docs)
GROQ_STT_MODEL = "whisper-large-v3"

# Always Traditional Chinese (Taiwan phrasing)
_OPENCC_TW = OpenCC("s2twp")


def _get_groq_key() -> str:
    k = (os.getenv("GROQ_API_KEY") or "").strip()
    if not k:
        raise RuntimeError("Missing GROQ_API_KEY environment variable")
    return k


def _ensure_traditional_zh(text: str) -> str:
    if not text:
        return ""
    return _OPENCC_TW.convert(text)


def stt_from_audio_file(audio_path: str, language: str) -> str:
    """
    audio_path: path to audio file (wav/mp3/m4a/webm...)
    language: "vi" | "en" | "zh"  (app already chooses; we DO NOT auto-detect)
    Return: transcript text; if zh -> guaranteed Traditional Chinese
    """
    language = (language or "").strip().lower()
    if language not in SUPPORTED_LANGS:
        raise ValueError(f"Invalid language: {language}. Must be one of {sorted(SUPPORTED_LANGS)}")

    api_key = _get_groq_key()

    headers = {"Authorization": f"Bearer {api_key}"}

    # OpenAI-compatible multipart form:
    # - file: binary
    # - model: whisper-large-v3
    # - language: en/vi/zh
    # - temperature: 0
    # - response_format: json (or verbose_json)
    with open(audio_path, "rb") as f:
        files = {
            "file": (os.path.basename(audio_path), f),
        }
        data = {
            "model": GROQ_STT_MODEL,
            "language": language,
            "temperature": "0",
            "response_format": "json",
        }

        r = requests.post(GROQ_STT_URL, headers=headers, files=files, data=data, timeout=120)
        r.raise_for_status()
        resp = r.json()

    text = (resp.get("text") or "").strip()

    # Hard guarantee: if input is Chinese, always return Traditional
    if language == "zh":
        text = _ensure_traditional_zh(text)

    return text
