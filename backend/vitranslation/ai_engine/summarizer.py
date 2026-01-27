# vitranslation/ai_engine/summarizer.py
from __future__ import annotations

from .ollama_client import generate
from .prompts import summary_prompt

def make_summary(source_lang: str, full_source: str) -> str:
    prompt = summary_prompt(source_lang, full_source)
    return generate(prompt)
