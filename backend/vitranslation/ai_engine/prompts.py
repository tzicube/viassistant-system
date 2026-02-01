# vitranslation/ai_engine/prompts.py
from __future__ import annotations

VALID_LANGS = {"en", "vi", "zh"}

_LANG_NAME = {
    "en": "English",
    "vi": "Vietnamese",
    "zh": "Chinese (Traditional if possible)",
}


def _lang_name(code: str) -> str:
    return _LANG_NAME.get(code, code)


def translate_segment_prompt(
    source_lang: str,
    target_lang: str,
    title_name: str,
    title_context_tail: str,
    segment: str,
) -> str:
    """
        Realtime: dịch MỘT đoạn mới (segment), nhưng phải bám theo:
            - title_name: tên của hội thoại/chủ đề
            - title_context_tail: lịch sử source/target của topic để giữ thuật ngữ
    """
    src_name = _lang_name(source_lang)
    tgt_name = _lang_name(target_lang)

    title = (title_name or "").strip()
    tail = (title_context_tail or "").strip()
    seg = (segment or "").strip()

    return f"""You are a professional real-time translator.

CONVERSATION TITLE: {title if title else "(untitled)"}

RULES:
- Translate from {src_name} to {tgt_name}.
- Output ONLY the translated text. No explanation.
- Keep technical terms consistent with the conversation title and topic memory.
- Preserve numbers, names, abbreviations, and units exactly.
- If {tgt_name} is Vietnamese, use natural Vietnamese.
- If {tgt_name} is Chinese, prefer Traditional Chinese if possible.

TOPIC MEMORY (recent tail, bilingual):
{tail if tail else "(none)"}

NEW SEGMENT (translate this):
{seg}
"""


def final_translate_prompt(
    source_lang: str,
    target_lang: str,
    title_name: str,
    title_context_tail: str,
    full_source: str,
) -> str:
    """
    Stop: dịch lại toàn bộ full_source cho mượt + nhất quán.
    """
    src_name = _lang_name(source_lang)
    tgt_name = _lang_name(target_lang)

    title = (title_name or "").strip()
    tail = (title_context_tail or "").strip()
    src = (full_source or "").strip()

    return f"""You are a professional translator.

CONVERSATION TITLE: {title if title else "(untitled)"}

TASK:
- Translate the FULL TEXT from {src_name} to {tgt_name}.
- Output ONLY the final translated text (no commentary).
- Make it coherent, fluent, and consistent.
- Keep technical terminology consistent with the conversation title and topic memory.
- Preserve line breaks as much as possible.

TOPIC MEMORY (recent tail, bilingual):
{tail if tail else "(none)"}

FULL TEXT:
{src}
"""


def refine_source_prompt(
    source_lang: str,
    title_name: str,
    full_source: str,
) -> str:
    """
    Refine STT output before translation:
    - Fix speech-to-text errors
    - Correct grammar, punctuation
    - Fill gaps based on conversation title context
    - Make it coherent and logically complete
    - Output ONLY the refined text (no commentary)
    """
    src_name = _lang_name(source_lang)
    title = (title_name or "").strip()
    src = (full_source or "").strip()

    return f"""You are a professional editor specializing in correcting speech-to-text (STT) output.

CONVERSATION TITLE: {title if title else "(untitled)"}
SOURCE LANGUAGE: {src_name}

TASK:
- Review the raw STT text below
- Fix speech recognition errors (homophones, missing words, mishearing)
- Add proper punctuation and capitalization
- Correct grammar while preserving original intent
- Fill logical gaps or missing context based on the conversation title
- Ensure coherence and logical flow
- Output ONLY the refined text (no explanation or commentary)
- Preserve line breaks structure

RAW STT TEXT (may contain errors):
{src}
"""
