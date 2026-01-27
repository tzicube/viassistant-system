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
    title_context_tail: str,
    summary_context: str,
    segment: str,
) -> str:
    """
    Realtime: dịch MỘT đoạn mới (segment), nhưng phải bám theo:
      - title_context_tail: lịch sử source/target của topic để giữ thuật ngữ
      - summary_context: tóm tắt định kỳ 10s để giữ ngữ cảnh
    """
    src_name = _lang_name(source_lang)
    tgt_name = _lang_name(target_lang)

    tail = (title_context_tail or "").strip()
    summ = (summary_context or "").strip()
    seg = (segment or "").strip()

    return f"""You are a professional real-time translator.

RULES:
- Translate from {src_name} to {tgt_name}.
- Output ONLY the translated text. No explanation.
- Keep technical terms consistent with the topic memory and summary.
- Preserve numbers, names, abbreviations, and units exactly.
- If {tgt_name} is Vietnamese, use natural Vietnamese.
- If {tgt_name} is Chinese, prefer Traditional Chinese if possible.

TOPIC MEMORY (recent tail, bilingual):
{tail if tail else "(none)"}

RUNNING SUMMARY (updated periodically):
{summ if summ else "(none)"}

NEW SEGMENT (translate this):
{seg}
"""


def final_translate_prompt(
    source_lang: str,
    target_lang: str,
    title_context_tail: str,
    summary_context: str,
    full_source: str,
) -> str:
    """
    Stop: dịch lại toàn bộ full_source cho mượt + nhất quán.
    """
    src_name = _lang_name(source_lang)
    tgt_name = _lang_name(target_lang)

    tail = (title_context_tail or "").strip()
    summ = (summary_context or "").strip()
    src = (full_source or "").strip()

    return f"""You are a professional translator.

TASK:
- Translate the FULL TEXT from {src_name} to {tgt_name}.
- Output ONLY the final translated text (no commentary).
- Make it coherent, fluent, and consistent.
- Keep technical terminology consistent with the topic memory and the summary.
- Preserve line breaks as much as possible.

TOPIC MEMORY (recent tail, bilingual):
{tail if tail else "(none)"}

RUNNING SUMMARY:
{summ if summ else "(none)"}

FULL TEXT:
{src}
"""


def summary_prompt(source_lang: str, full_source: str) -> str:
    """
    Summary worker: tóm tắt để giữ ngữ cảnh (10s/lần).
    """
    src_name = _lang_name(source_lang)
    text = (full_source or "").strip()

    return f"""You are a concise summarizer.

INPUT LANGUAGE: {src_name}

Summarize the text in 3-6 bullet points.
Keep key entities, names, numbers, and domain terms.
Be short and information-dense.

TEXT:
{text}
"""
