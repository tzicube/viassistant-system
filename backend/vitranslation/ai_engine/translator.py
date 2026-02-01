# vitranslation/ai_engine/translator.py
from __future__ import annotations

import asyncio
import threading
from typing import AsyncIterator

from .ollama_client import generate, generate_stream
from .prompts import translate_segment_prompt, final_translate_prompt, refine_source_prompt


async def stream_translate_segment_async(
    source_lang: str,
    target_lang: str,
    title_name: str,
    title_context_tail: str,
    segment: str,
) -> AsyncIterator[str]:
    """
    IMPORTANT: chạy generate_stream (blocking) trong thread,
    trả token/chunk về async iterator để không block event-loop.
    """
    prompt = translate_segment_prompt(
        source_lang, target_lang, title_name, title_context_tail, segment
    )

    q: asyncio.Queue[str | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def worker():
        try:
            for ch in generate_stream(prompt):
                # đẩy chunk về event loop thread-safe
                loop.call_soon_threadsafe(q.put_nowait, ch)
        except Exception as e:
            loop.call_soon_threadsafe(q.put_nowait, f"[translate_stream_fail] {e}")
        finally:
            loop.call_soon_threadsafe(q.put_nowait, None)

    threading.Thread(target=worker, daemon=True).start()

    while True:
        item = await q.get()
        if item is None:
            break
        yield item


def final_translate_full(
    source_lang: str,
    target_lang: str,
    title_name: str,
    title_context_tail: str,
    full_source: str,
) -> str:
    if not (full_source or "").strip():
        return ""
    prompt = final_translate_prompt(
        source_lang, target_lang, title_name, title_context_tail, full_source
    )
    return generate(prompt)


def refine_source_full(
    source_lang: str,
    title_name: str,
    full_source: str,
) -> str:
    """
    Refine STT output: fix errors, correct grammar, add punctuation,
    fill logical gaps based on conversation title context.
    """
    if not (full_source or "").strip():
        return ""
    prompt = refine_source_prompt(
        source_lang, title_name, full_source
    )
    return generate(prompt)
