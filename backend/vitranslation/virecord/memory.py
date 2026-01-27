# vitranslation/virecord/memory.py
from __future__ import annotations
from dataclasses import dataclass, field
import time

@dataclass
class SessionMemory:
    # session
    title_id: str | None = None
    title_name: str | None = None

    # langs (only en/vi/zh)
    stt_language: str = "en"
    translate_source: str = "en"
    translate_target: str = "vi"

    # STT
    stt_full: str = ""
    committed_source: str = ""         # lines separated by \n
    committed_marker: str = ""         # used to extract new segment
    last_audio_ts: float = field(default_factory=lambda: time.time())

    # translation
    committed_target: str = ""         # lines separated by \n

    # title context tail (from history files + new)
    title_context_tail: str = ""

    # summary (Line 3) - RAM only
    summary_context: str = ""

    # lifecycle
    stopping: bool = False
    stopped: bool = False
