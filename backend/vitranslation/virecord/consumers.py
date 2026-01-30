# vitranslation/virecord/consumers.py
from __future__ import annotations

import asyncio
import base64
import time
import logging
import re
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from stt_engine.config import WhisperConfig
from stt_engine.stream import RealtimeWhisperStreamer

from vitranslation.ai_engine.prompts import VALID_LANGS
from vitranslation.ai_engine.summarizer import make_summary
from vitranslation.ai_engine.translator import (
    stream_translate_segment_async,
    final_translate_full,
)

from .memory import SessionMemory
from .history_fs import (
    ensure_session,
    read_source_target,
    write_source,
    write_target,
    build_title_context_tail,
)

logger = logging.getLogger("virecord")

# punctuation triggers immediate commit
_PUNCT_RE = re.compile(r"[.!?。！？]")

# =========================
# TUNING
# =========================
MIN_COMMIT_CHARS = 10      # 12-16 nếu còn vụn
PAUSE_SEC = 0.5           # 1.4-1.8 nếu commit quá sớm
TICK = 0.18                # loop tick


def _safe_lang(x: str) -> str:
    return (x or "").strip().lower()


def _b64_to_bytes(b64: str) -> bytes:
    return base64.b64decode((b64 or "").encode("utf-8"))


def _norm_space(s: str) -> str:
    # normalize for COMMIT only
    return " ".join((s or "").split())


def _split_commit_by_punct(draft_raw: str) -> tuple[int, str, str]:
    """
    Return (cut_idx, commit_raw, remain_raw)
    cut_idx: index in draft_raw (raw, not normalized)
    """
    if not draft_raw:
        return 0, "", ""
    matches = list(_PUNCT_RE.finditer(draft_raw))
    if not matches:
        return 0, "", draft_raw

    cut_idx = matches[-1].end()
    commit_raw = draft_raw[:cut_idx]
    remain_raw = draft_raw[cut_idx:]  # DO NOT strip here (cursor safety)
    # UI can lstrip later
    return cut_idx, commit_raw, remain_raw


def _avoid_cut_mid_word(full_raw: str, cur: int) -> int:
    """
    If cur falls between alnum characters (mid-word), move cur left to a boundary.
    This prevents commit slicing inside a token when STT rewrites slightly.
    """
    n = len(full_raw)
    cur = max(0, min(cur, n))
    if cur <= 0 or cur >= n:
        return cur

    def is_word(ch: str) -> bool:
        return ch.isalnum() or ch in ("_",)

    # If boundary is safe, keep
    if not (is_word(full_raw[cur - 1]) and is_word(full_raw[cur])):
        return cur

    # Move left until boundary
    i = cur
    while i > 0 and i < n and (is_word(full_raw[i - 1]) and is_word(full_raw[i])):
        i -= 1
    return i


class ViRecordConsumer(AsyncJsonWebsocketConsumer):
    """
    FE -> BE:
      - {type:"init", title_id, title_name, stt_language, translate_source, translate_target}
      - {type:"audio.chunk", pcm16_b64}
      - {type:"stop"} or {type:"utt.commit"}

    BE -> FE:
      - {"type":"stt.delta","text":"..."}                 # live draft (REPLACE on UI)
      - {"type":"stt.commit","text":"..."}               # committed source segment (APPEND)
      - {"type":"translation.delta","delta":"..."}       # streaming translation delta (append to live)
      - {"type":"translation.commit","text":"..."}       # committed translation segment (APPEND)
      - {"type":"summary.update","summary":"..."}
      - {"type":"final.result","source":"...","target":"...","summary":"..."}
      - {"type":"error","error":"..."}
    """

    async def connect(self):
        await self.accept()
        self.mem = SessionMemory()

        self.audio_q: asyncio.Queue[bytes] = asyncio.Queue()
        self.commit_q: asyncio.Queue[str] = asyncio.Queue()

        self._tasks: list[asyncio.Task] = []
        self._inited = False
        self._stop_event = asyncio.Event()

        logger.warning("[connect] client connected")

    async def disconnect(self, code):
        await self._shutdown()

    async def receive_json(self, content, **kwargs):
        t = (content.get("type") or "").strip()

        if t == "init":
            await self._on_init(content)
            return

        if not self._inited:
            await self.send_json({"type": "error", "error": "not inited. send type=init first"})
            return

        if t == "audio.chunk":
            if self.mem.stopping or self.mem.stopped:
                return

            try:
                pcm = _b64_to_bytes(content.get("pcm16_b64") or "")
            except Exception:
                await self.send_json({"type": "error", "error": "bad audio base64"})
                return

            self.mem.last_audio_ts = time.time()
            await self.audio_q.put(pcm)
            return

        if t in ("stop", "utt.commit"):
            await self._on_stop()
            return

        await self.send_json({"type": "error", "error": f"unknown type: {t}"})

    async def _on_init(self, content: dict):
        title_id = (content.get("title_id") or "").strip()
        title_name = (content.get("title_name") or "").strip() or None

        stt_lang = _safe_lang(content.get("stt_language") or "")
        tr_src = _safe_lang(content.get("translate_source") or "")
        tr_tgt = _safe_lang(content.get("translate_target") or "")

        if not title_id:
            await self.send_json({"type": "error", "error": "missing title_id"})
            return

        if stt_lang not in VALID_LANGS or tr_src not in VALID_LANGS or tr_tgt not in VALID_LANGS:
            await self.send_json({"type": "error", "error": "Only languages allowed: en / vi / zh"})
            return

        # session memory
        self.mem.title_id = title_id
        self.mem.title_name = title_name or title_id
        self.mem.stt_language = stt_lang
        self.mem.translate_source = tr_src
        self.mem.translate_target = tr_tgt

        ensure_session(self.mem.title_id, self.mem.title_name)

        # persisted history for context
        prev_src, prev_tgt = read_source_target(self.mem.title_id)
        self.mem.committed_source = (prev_src or "").strip()
        self.mem.committed_target = (prev_tgt or "").strip()
        self.mem.title_context_tail = build_title_context_tail(prev_src, prev_tgt)

        # runtime buffers
        self.mem.stt_cumulative = ""          # RAW full STT current recording (NO strip)
        self.mem.summary_context = ""
        self.mem.last_audio_ts = time.time()

        # cursor into stt_cumulative (RAW chars)
        self.mem._stt_committed_len = 0
        self.mem._last_commit_hash = 0
        self.mem.last_stt_update_ts = time.time()

        self.mem.session_src_segments = []
        self.mem.session_tgt_segments = []
        self.mem._translating = False

        self._tasks = [
            asyncio.create_task(self._line1_stt(), name="line1_stt"),
            asyncio.create_task(self._pause_commit_loop(), name="pause_commit"),
            asyncio.create_task(self._line2_translate_commits(), name="line2_translate_commits"),
            asyncio.create_task(self._line3_summary_10s(), name="line3_summary"),
        ]
        for task in self._tasks:
            task.add_done_callback(self._task_done)

        self._inited = True
        logger.warning(
            "[init] OK title_id=%s stt=%s tr=%s->%s",
            self.mem.title_id, self.mem.stt_language, self.mem.translate_source, self.mem.translate_target
        )

    def _task_done(self, t: asyncio.Task):
        try:
            exc = t.exception()
        except asyncio.CancelledError:
            logger.warning("[task_cancel] %s", t.get_name())
            return
        if exc:
            logger.exception("[task_crash] %s", t.get_name(), exc_info=exc)
        else:
            logger.warning("[task_done] %s", t.get_name())

    # =========================================================
    # Commit helpers
    # =========================================================
    async def _commit_source_segment(self, segment_raw: str):
        # normalize only at commit time
        segment = _norm_space(segment_raw).strip()
        if not segment:
            return
        if len(segment) < MIN_COMMIT_CHARS:
            return

        h = hash(segment)
        if h == getattr(self.mem, "_last_commit_hash", 0):
            return
        self.mem._last_commit_hash = h

        self.mem.session_src_segments.append(segment)
        await self.commit_q.put(segment)

        await self.send_json({"type": "stt.commit", "text": segment})

    async def _flush_draft_commit(self):
        full_raw = (self.mem.stt_cumulative or "")  # NO strip
        cur = int(getattr(self.mem, "_stt_committed_len", 0))
        cur = max(0, min(cur, len(full_raw)))
        cur = _avoid_cut_mid_word(full_raw, cur)
        self.mem._stt_committed_len = cur

        draft_raw = full_raw[cur:]
        # For end-flush, we can trim whitespace at ends safely for commit content only:
        if draft_raw and _norm_space(draft_raw).strip():
            self.mem._stt_committed_len = len(full_raw)
            await self._commit_source_segment(draft_raw)

    # =========================================================
    # Line 1: STT realtime -> stt.delta (live draft)
    # =========================================================
    async def _line1_stt(self):
        logger.warning("[line1] start stt")

        cfg = WhisperConfig(
            model_size="small",
            device="cuda",
            compute_type="float16",
            language=self.mem.stt_language,  # en/vi/zh (or set None if you want auto)
            vad_filter=False,               # keep as your design
            beam_size=1,
        )
        streamer = RealtimeWhisperStreamer(cfg)

        while not self.mem.stopped:
            # feed audio
            try:
                pcm = await asyncio.wait_for(self.audio_q.get(), timeout=0.25)
                streamer.push(pcm)
            except asyncio.TimeoutError:
                pass

            if streamer.ready():
                try:
                    full = await asyncio.to_thread(streamer.transcribe_cumulative)
                except Exception as e:
                    await self.send_json({"type": "error", "error": f"stt_fail: {e}"})
                    continue

                # IMPORTANT: keep RAW, do NOT strip
                full_raw = (full or "")
                if not full_raw:
                    if self.mem.stopping:
                        break
                    continue

                self.mem.stt_cumulative = full_raw
                self.mem.last_stt_update_ts = time.time()

                # cursor safety
                cur = int(getattr(self.mem, "_stt_committed_len", 0))
                cur = max(0, min(cur, len(full_raw)))
                cur = _avoid_cut_mid_word(full_raw, cur)
                self.mem._stt_committed_len = cur

                draft_raw = full_raw[cur:]

                # send live draft (FE should REPLACE)
                await self.send_json({
                    "type": "stt.delta",
                    "text": draft_raw.lstrip(),  # UI nicer; cursor still uses RAW
                })

                # immediate commit if punctuation exists inside draft
                cut_idx, commit_raw, remain_raw = _split_commit_by_punct(draft_raw)
                if cut_idx > 0:
                    commit_norm = _norm_space(commit_raw).strip()
                    if len(commit_norm) >= MIN_COMMIT_CHARS:
                        self.mem._stt_committed_len = cur + cut_idx
                        await self._commit_source_segment(commit_raw)

                        # update live after commit
                        await self.send_json({
                            "type": "stt.delta",
                            "text": remain_raw.lstrip(),
                        })

            if self.mem.stopping:
                logger.warning("[line1] stopping -> break")
                break

        logger.warning("[line1] exit")

    # =========================================================
    # Pause commit loop: commit draft when idle >= PAUSE_SEC
    # =========================================================
    async def _pause_commit_loop(self):
        logger.warning("[pause] start pause commit loop")

        while not self.mem.stopped:
            await asyncio.sleep(TICK)
            if self.mem.stopping:
                break

            full_raw = (self.mem.stt_cumulative or "")  # NO strip
            if not full_raw:
                continue

            cur = int(getattr(self.mem, "_stt_committed_len", 0))
            cur = max(0, min(cur, len(full_raw)))
            cur = _avoid_cut_mid_word(full_raw, cur)
            self.mem._stt_committed_len = cur

            draft_raw = full_raw[cur:]
            if not draft_raw:
                continue

            idle = time.time() - float(getattr(self.mem, "last_stt_update_ts", time.time()))
            if idle >= PAUSE_SEC:
                draft_norm = _norm_space(draft_raw).strip()
                if len(draft_norm) < MIN_COMMIT_CHARS:
                    continue

                # commit entire draft
                self.mem._stt_committed_len = len(full_raw)
                await self._commit_source_segment(draft_raw)

                # clear live draft on FE
                await self.send_json({"type": "stt.delta", "text": ""})

        logger.warning("[pause] exit")

    # =========================================================
    # Line 2: Translation realtime ONLY for committed segments
    # =========================================================
    async def _line2_translate_commits(self):
        logger.warning("[line2] start translate (commit_queue)")

        while not self.mem.stopped:
            if self.mem.stopping:
                logger.warning("[line2] stopping -> break")
                break

            try:
                seg = await asyncio.wait_for(self.commit_q.get(), timeout=0.25)
            except asyncio.TimeoutError:
                continue

            seg = (seg or "").strip()
            if not seg:
                continue

            self.mem._translating = True
            seg_cum = ""

            try:
                async for chunk in stream_translate_segment_async(
                    source_lang=self.mem.translate_source,
                    target_lang=self.mem.translate_target,
                    title_context_tail=self.mem.title_context_tail,
                    summary_context=self.mem.summary_context,
                    segment=seg,
                ):
                    if self.mem.stopped or self.mem.stopping:
                        break

                    chunk = chunk or ""
                    if not chunk:
                        continue

                    seg_cum += chunk
                    await self.send_json({"type": "translation.delta", "delta": chunk})

            except Exception as e:
                logger.exception("[line2] translate_fail")
                await self.send_json({"type": "error", "error": f"translate_fail: {e}"})
                self.mem._translating = False
                continue

            translated = _norm_space(seg_cum).strip()
            if translated:
                self.mem.session_tgt_segments.append(translated)
                await self.send_json({"type": "translation.commit", "text": translated})

            self.mem._translating = False

        logger.warning("[line2] exit")

    # =========================================================
    # Line 3: Summary every 10s
    # =========================================================
    async def _line3_summary_10s(self):
        logger.warning("[line3] start summary worker")

        while not self.mem.stopped:
            await asyncio.sleep(10.0)
            if self.mem.stopping:
                logger.warning("[line3] stopping -> break")
                break

            try:
                persisted = (self.mem.committed_source or "").strip()
                session_committed = "\n".join(self.mem.session_src_segments).strip()

                full_raw = (self.mem.stt_cumulative or "")
                cur = int(getattr(self.mem, "_stt_committed_len", 0))
                cur = max(0, min(cur, len(full_raw)))
                cur = _avoid_cut_mid_word(full_raw, cur)
                draft_raw = full_raw[cur:]

                parts = [p for p in [persisted, session_committed, _norm_space(draft_raw).strip()] if p]
                src2 = "\n".join(parts).strip()
                if not src2:
                    continue

                summ = await asyncio.to_thread(make_summary, self.mem.translate_source, src2)
                summ = (summ or "").strip()
                if not summ:
                    continue

                self.mem.summary_context = summ
                await self.send_json({"type": "summary.update", "summary": summ})

            except Exception as e:
                logger.warning("[line3] summary_fail: %s", e)
                continue

        logger.warning("[line3] exit")

    # =========================================================
    # STOP
    # =========================================================
    async def _on_stop(self):
        if self.mem.stopping or self.mem.stopped:
            return

        logger.warning("[stop] requested")
        self.mem.stopping = True

        # grace
        await asyncio.sleep(0.4)

        # flush remaining draft
        await self._flush_draft_commit()

        # wait translations bounded
        t0 = time.time()
        while time.time() - t0 < 2.0:
            if self.commit_q.empty() and not bool(getattr(self.mem, "_translating", False)):
                break
            await asyncio.sleep(0.1)

        try:
            persisted_src = (self.mem.committed_source or "").strip()
            session_src = "\n".join(self.mem.session_src_segments).strip()

            full_src = "\n".join([p for p in [persisted_src, session_src] if p]).strip()

            final_tgt = await asyncio.to_thread(
                final_translate_full,
                self.mem.translate_source,
                self.mem.translate_target,
                self.mem.title_context_tail,
                self.mem.summary_context,
                full_src,
            )
            final_tgt = (final_tgt or "").strip()

            write_source(self.mem.title_id, full_src)
            write_target(self.mem.title_id, final_tgt)

            self.mem.committed_source = full_src
            self.mem.committed_target = final_tgt
            self.mem.title_context_tail = build_title_context_tail(full_src, final_tgt)

            await self.send_json({
                "type": "final.result",
                "source": full_src,
                "target": final_tgt,
                "summary": (self.mem.summary_context or ""),
            })

            logger.warning("[stop] final.result sent (src=%s tgt=%s)", len(full_src), len(final_tgt))

        except Exception as e:
            await self.send_json({"type": "error", "error": f"final_translate_fail: {e}"})

        await self._shutdown()

    async def _shutdown(self):
        if self.mem.stopped:
            return
        self.mem.stopped = True

        self._stop_event.set()

        for t in getattr(self, "_tasks", []):
            if not t.done():
                t.cancel()

        if getattr(self, "_tasks", None):
            await asyncio.gather(*self._tasks, return_exceptions=True)

        logger.warning("[shutdown] done")
