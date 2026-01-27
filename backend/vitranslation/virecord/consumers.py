# vitranslation/virecord/consumers.py
from __future__ import annotations

import asyncio
import base64
import time
import logging
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


def _safe_lang(x: str) -> str:
    return (x or "").strip().lower()


def _b64_to_bytes(b64: str) -> bytes:
    # b64 string -> raw bytes (PCM16 LE)
    return base64.b64decode((b64 or "").encode("utf-8"))


class ViRecordConsumer(AsyncJsonWebsocketConsumer):
    """
    FE -> BE (theo FE hiện tại của anh):
      - {type:"init", title_id, title_name, stt_language, translate_source, translate_target}
      - {type:"audio.chunk", pcm16_b64}
      - {type:"utt.commit"}  (FE cũ)
      - {type:"stop"}        (FE mới)  -> BE support cả 2

    BE -> FE (schema mới realtime):
      - {"type":"stt.delta","delta":"..."}                 # append-only
      - {"type":"translation.delta","delta":"..."}         # append-only realtime
      - {"type":"summary.update","summary":"..."}          # optional mỗi 10s
      - {"type":"final.result","source":"...","target":"...","summary":"..."}
      - {"type":"error","error":"..."}
    """

    async def connect(self):
        await self.accept()
        self.mem = SessionMemory()

        self.audio_q: asyncio.Queue[bytes] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []
        self._inited = False

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

        # load history for this title (dịch theo title)
        prev_src, prev_tgt = read_source_target(self.mem.title_id)
        self.mem.committed_source = (prev_src or "").strip()
        self.mem.committed_target = (prev_tgt or "").strip()
        self.mem.title_context_tail = build_title_context_tail(prev_src, prev_tgt)

        # runtime buffers
        self.mem.stt_cumulative = ""
        self.mem.tr_cumulative = ""
        self.mem.summary_context = ""
        self.mem._stt_last_emit = ""
        self.mem._tr_last_emit = ""
        self.mem._tr_last_src_len = 0
        self.mem.last_audio_ts = time.time()

        self._tasks = [
            asyncio.create_task(self._line1_stt(), name="line1_stt"),
            asyncio.create_task(self._line2_translate_realtime(), name="line2_translate"),
            asyncio.create_task(self._line3_summary_10s(), name="line3_summary"),
        ]

        # attach done callbacks
        for task in self._tasks:
            task.add_done_callback(self._task_done)

        self._inited = True
        logger.warning("[init] OK title_id=%s stt=%s tr=%s->%s",
                       self.mem.title_id, self.mem.stt_language, self.mem.translate_source, self.mem.translate_target)

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

    # =========================
    # Line 1: STT realtime -> stt.delta
    # =========================
    async def _line1_stt(self):
        logger.warning("[line1] start stt")
        cfg = WhisperConfig(
            model_size="small",
            device="cuda",
            compute_type="float16",
            language=self.mem.stt_language,  # en/vi/zh
            vad_filter=False,               # tắt để tránh onnxruntime
        )
        streamer = RealtimeWhisperStreamer(cfg)

        while not self.mem.stopped:
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

                full = (full or "").strip()
                if not full:
                    if self.mem.stopping:
                        break
                    continue

                old = self.mem._stt_last_emit or ""
                if full == old:
                    if self.mem.stopping:
                        break
                    continue

                self.mem.stt_cumulative = full

                # delta append-only
                if full.startswith(old):
                    delta = full[len(old):]
                else:
                    delta = full

                self.mem._stt_last_emit = full

                if delta:
                    await self.send_json({"type": "stt.delta", "delta": delta})

            if self.mem.stopping:
                logger.warning("[line1] stopping -> break")
                break

        logger.warning("[line1] exit")

    # =========================
    # Line 2: Translation realtime (poll STT) -> translation.delta
    # IMPORTANT: dùng stream_translate_segment_async để không block event-loop
    # =========================
    async def _line2_translate_realtime(self):
        POLL_SEC = 1.0
        MIN_NEW_CHARS = 6
        MAX_SEG_CHARS = 260

        logger.warning("[line2] start translate realtime")

        while not self.mem.stopped:
            if self.mem.stopping:
                logger.warning("[line2] stopping -> break")
                break

            await asyncio.sleep(POLL_SEC)

            src_full = (self.mem.stt_cumulative or "").strip()
            last_src_len = int(self.mem._tr_last_src_len or 0)

            logger.warning("[line2] tick src_len=%s last_src_len=%s", len(src_full), last_src_len)

            if not src_full:
                continue

            # detect reset
            if len(src_full) < last_src_len:
                logger.warning("[line2] stt reset detected")
                last_src_len = 0
                self.mem._tr_last_src_len = 0
                self.mem._tr_last_emit = ""

            new_part = src_full[last_src_len:].strip()
            if len(new_part) < MIN_NEW_CHARS:
                continue

            if len(new_part) > MAX_SEG_CHARS:
                new_part = new_part[-MAX_SEG_CHARS:]

            logger.warning("[line2] CALL OLLAMA seg_len=%s seg_head=%r", len(new_part), new_part[:80])

            out_cum = ""
            prev_out = self.mem._tr_last_emit or ""

            try:
                async for chunk in stream_translate_segment_async(
                    source_lang=self.mem.translate_source,
                    target_lang=self.mem.translate_target,
                    title_context_tail=self.mem.title_context_tail,
                    summary_context=self.mem.summary_context,
                    segment=new_part,
                ):
                    if self.mem.stopped or self.mem.stopping:
                        break

                    out_cum += (chunk or "")

                    # cumulative -> delta
                    if out_cum.startswith(prev_out):
                        delta = out_cum[len(prev_out):]
                    else:
                        delta = out_cum

                    if delta:
                        await self.send_json({"type": "translation.delta", "delta": delta})

                    prev_out = out_cum
                    self.mem._tr_last_emit = out_cum

            except Exception as e:
                await self.send_json({"type": "error", "error": f"translate_fail: {e}"})
                continue

            # mark consumed
            self.mem._tr_last_src_len = len(src_full)
            self.mem.tr_cumulative = (self.mem.tr_cumulative or "") + (out_cum or "")

        logger.warning("[line2] exit")

    # =========================
    # Line 3: Summary every 10s
    # =========================
    async def _line3_summary_10s(self):
        logger.warning("[line3] start summary worker")

        while not self.mem.stopped:
            await asyncio.sleep(10.0)
            if self.mem.stopping:
                logger.warning("[line3] stopping -> break")
                break

            try:
                committed = (self.mem.committed_source or "").strip()
                live = (self.mem.stt_cumulative or "").strip()

                if committed and live:
                    if live.startswith(committed):
                        src2 = live
                    else:
                        src2 = committed + "\n" + live
                else:
                    src2 = committed or live

                src2 = (src2 or "").strip()
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

    # =========================
    # STOP: final translate full, persist history, send final.result
    # =========================
    async def _on_stop(self):
        if self.mem.stopping or self.mem.stopped:
            return

        logger.warning("[stop] requested")
        self.mem.stopping = True

        # grace time
        await asyncio.sleep(0.4)

        try:
            committed = (self.mem.committed_source or "").strip()
            live = (self.mem.stt_cumulative or "").strip()

            if committed and live:
                if live.startswith(committed):
                    full_src = live
                else:
                    full_src = committed + "\n" + live
            else:
                full_src = committed or live

            full_src = (full_src or "").strip()

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

        for t in getattr(self, "_tasks", []):
            if not t.done():
                t.cancel()

        if getattr(self, "_tasks", None):
            await asyncio.gather(*self._tasks, return_exceptions=True)

        logger.warning("[shutdown] done")
