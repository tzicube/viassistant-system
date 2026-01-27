# vitranslation/ai_engine/translator.py
from __future__ import annotations

import asyncio
import threading
from typing import AsyncIterator

from .ollama_client import generate, generate_stream
from .prompts import translate_segment_prompt, final_translate_prompt


async def stream_translate_segment_async(
    source_lang: str,
    target_lang: str,
    title_context_tail: str,
    summary_context: str,
    segment: str,
) -> AsyncIterator[str]:
    """
    IMPORTANT: chạy generate_stream (blocking) trong thread,
    trả token/chunk về async iterator để không block event-loop.
    """
    prompt = translate_segment_prompt(
        source_lang, target_lang, title_context_tail, summary_context, segment
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
    title_context_tail: str,
    summary_context: str,
    full_source: str,
) -> str:
    if not (full_source or "").strip():
        return ""
    prompt = final_translate_prompt(
        source_lang, target_lang, title_context_tail, summary_context, full_source
    )
    return generate(prompt)
