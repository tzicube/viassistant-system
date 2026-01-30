# vitranslation/virecord/memory.py
from __future__ import annotations

from dataclasses import dataclass, field
import time


@dataclass
class SessionMemory:
    # =========================
    # Session identity
    # =========================
    title_id: str | None = None
    title_name: str | None = None

    # =========================
    # Languages (only en/vi/zh)
    # =========================
    stt_language: str = "en"
    translate_source: str = "en"
    translate_target: str = "vi"

    # =========================
    # Persisted history (loaded at init)
    # =========================
    committed_source: str = ""         # full source history (persisted)
    committed_target: str = ""         # full target history (persisted)
    title_context_tail: str = ""       # context tail built from persisted files

    # =========================
    # Runtime STT (current recording session)
    # =========================
    stt_cumulative: str = ""           # full STT of current recording session
    _stt_last_emit: str = ""           # for legacy delta compatibility
    _stt_committed_len: int = 0        # cursor into stt_cumulative (chars) that have been committed
    last_stt_update_ts: float = field(default_factory=lambda: time.time())

    # =========================
    # Runtime committed segments (Method A)
    # =========================
    session_src_segments: list[str] = field(default_factory=list)
    session_tgt_segments: list[str] = field(default_factory=list)

    # Avoid duplicate commits (whisper may repeat)
    _last_commit_hash: int = 0

    # =========================
    # Summary (Line 3) - RAM only
    # =========================
    summary_context: str = ""

    # =========================
    # Audio timing
    # =========================
    last_audio_ts: float = field(default_factory=lambda: time.time())

    # =========================
    # Translation state
    # =========================
    _translating: bool = False

    # =========================
    # Lifecycle
    # =========================
    stopping: bool = False
    stopped: bool = False
