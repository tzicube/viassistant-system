from __future__ import annotations

import base64
import os
import tempfile
from collections import deque
import json
import asyncio
import logging
import wave
import io
import platform
import shutil
import subprocess
from pathlib import Path
import threading
from typing import Optional

from channels.generic.websocket import AsyncWebsocketConsumer

from .voice_pipeline import STTConfig, stt_wav_to_text, tts_text_to_wav_bytes
from .bluetooth_audio import play_tts_audio, init_bluetooth_speaker
from .assistant_logic import (
    _call_ai,
    _call_esp_relay,
    _call_esp_sensor,
    _detect_device_command,
    _detect_sensor_query,
    _format_device_reply,
    _format_sensor_reply,
)

logger = logging.getLogger("viassistant.ws")
ESP_INLINE_WAV_MAX_BYTES = int(os.getenv("VI_ESP_INLINE_WAV_MAX_BYTES", "65536"))
ESP_INLINE_TTS_MAX_CHARS = int(os.getenv("VI_ESP_INLINE_TTS_MAX_CHARS", "120"))
ESP_TTS_STREAM_CHUNK_BYTES = int(os.getenv("VI_ESP_TTS_STREAM_CHUNK_BYTES", "480"))
ESP_TTS_STREAM_PREFILL_CHUNKS = int(os.getenv("VI_ESP_TTS_STREAM_PREFILL_CHUNKS", "10"))
ESP_TTS_STREAM_PACE_FACTOR = float(os.getenv("VI_ESP_TTS_STREAM_PACE_FACTOR", "1.00"))
BT_SPEAKER_NAME = os.getenv("VI_BT_SPEAKER_NAME", "MAP140")
DEBUG_SAVE_TTS = os.getenv("VI_DEBUG_SAVE_TTS", "0") == "1"
MAX_CONVERSATION_TURNS = 5
HISTORY_FILE_PATH = Path(__file__).resolve().parent / "ai_history.json"
HISTORY_FILE_MAX_ENTRIES = int(os.getenv("VI_HISTORY_FILE_MAX_ENTRIES", "1000"))
HISTORY_FILE_LOCK = threading.Lock()
_BT_INIT_LOCK: Optional[asyncio.Lock] = None
_BT_READY = False


def _write_wav(path: str, pcm: bytes, sample_rate: int = 16000, channels: int = 1, sampwidth: int = 2):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)


def _play_wav_bytes_local(wav_bytes: bytes) -> None:
    """Play wav bytes on the server's default audio output (blocking)."""
    if not wav_bytes:
        return
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    Path(path).write_bytes(wav_bytes)
    try:
        if platform.system() == "Windows":
            try:
                import winsound

                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_SYNC | winsound.SND_NODEFAULT)
                logger.info("[ws] local playback via winsound")
            except Exception:
                logger.exception("[ws] winsound failed, fallback PowerShell SoundPlayer")
                ps_cmd = [
                    "powershell",
                    "-Command",
                    "(New-Object Media.SoundPlayer '{0}').PlaySync()".format(path.replace("'", "''")),
                ]
                subprocess.run(ps_cmd, check=False, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            player = shutil.which("ffplay") or shutil.which("aplay")
            if player:
                cmd = (
                    [player, "-nodisp", "-autoexit", "-loglevel", "quiet", path]
                    if "ffplay" in player
                    else [player, path]
                )
                subprocess.run(cmd, check=False)
            else:
                logger.warning("[ws] local playback skipped (no player found)")
    except Exception:
        logger.exception("[ws] local playback failed")
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


def _load_history_entries() -> list[dict[str, str]]:
    if not HISTORY_FILE_PATH.exists():
        return []

    try:
        raw = HISTORY_FILE_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        logger.exception("[ws] failed reading history file: %s", HISTORY_FILE_PATH)
        return []

    if not raw:
        return []

    try:
        data = json.loads(raw)
    except Exception:
        logger.exception("[ws] invalid history json: %s", HISTORY_FILE_PATH)
        return []

    if not isinstance(data, list):
        logger.warning("[ws] history json is not a list: %s", HISTORY_FILE_PATH)
        return []

    entries: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue

        q = str(item.get("q") or item.get("user") or "").strip()
        a = str(item.get("a") or item.get("assistant") or "").strip()
        if not q or not a:
            continue

        entries.append({"q": q, "a": a})

    return entries


def _load_recent_turns(limit: int) -> list[dict[str, str]]:
    entries = _load_history_entries()
    turns: list[dict[str, str]] = []
    for item in entries[-limit:]:
        turns.append({"user": item["q"], "assistant": item["a"]})
    return turns


def _append_history_entry(question: str, answer: str):
    q = (question or "").strip()
    a = (answer or "").strip()
    if not q or not a:
        return

    with HISTORY_FILE_LOCK:
        entries = _load_history_entries()
        entries.append({"q": q, "a": a})

        if HISTORY_FILE_MAX_ENTRIES > 0 and len(entries) > HISTORY_FILE_MAX_ENTRIES:
            entries = entries[-HISTORY_FILE_MAX_ENTRIES:]

        HISTORY_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(entries, ensure_ascii=False, indent=2) + "\n"
        temp_path = HISTORY_FILE_PATH.with_suffix(HISTORY_FILE_PATH.suffix + ".tmp")
        try:
            temp_path.write_text(payload, encoding="utf-8")
            temp_path.replace(HISTORY_FILE_PATH)
        except Exception:
            # On Windows, atomic replace can fail when the file is locked by an editor.
            logger.exception("[ws] history atomic replace failed, fallback direct write")
            HISTORY_FILE_PATH.write_text(payload, encoding="utf-8")


def _shorten_tts_text(text: str, max_chars: int = ESP_INLINE_TTS_MAX_CHARS) -> str:
    cleaned = " ".join((text or "").split()).strip()
    if not cleaned or len(cleaned) <= max_chars:
        return cleaned

    clipped = cleaned[:max_chars].rstrip()
    split_pos = max(
        clipped.rfind("."),
        clipped.rfind("!"),
        clipped.rfind("?"),
        clipped.rfind(","),
        clipped.rfind(";"),
        clipped.rfind(":"),
    )
    if split_pos >= max_chars // 2:
        clipped = clipped[: split_pos + 1].rstrip()
    return clipped


def _debug_save_wav(wav_bytes: bytes, label: str):
    if not DEBUG_SAVE_TTS or not wav_bytes:
        return
    try:
        path = Path(__file__).resolve().parent / f"debug_tts_{label}.wav"
        path.write_bytes(wav_bytes)
        logger.warning("[ws] debug saved tts wav -> %s (%d bytes)", path.name, len(wav_bytes))
    except Exception:
        logger.exception("[ws] failed saving debug tts wav")


def _normalize_wav_header(wav_bytes: bytes) -> bytes:
    """
    Some TTS outputs carry bogus nframes (e.g., 0x7fffffff) causing winsound to fail.
    Re-wrap frames with a clean WAV header.
    """
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            params = wf.getparams()
            frames = wf.readframes(wf.getnframes())
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf2:
            wf2.setnchannels(params.nchannels)
            wf2.setsampwidth(params.sampwidth)
            wf2.setframerate(params.framerate)
            wf2.writeframes(frames)
        fixed = buf.getvalue()
        return fixed if fixed else wav_bytes
    except Exception:
        logger.exception("[ws] normalize wav header failed")
        return wav_bytes


async def _ensure_bt_ready() -> bool:
    """
    Init Bluetooth speaker once (no-op if already ready).
    Windows path always returns True but we keep flag for symmetry.
    """
    global _BT_INIT_LOCK, _BT_READY
    if _BT_READY:
        return True
    if _BT_INIT_LOCK is None:
        _BT_INIT_LOCK = asyncio.Lock()
    async with _BT_INIT_LOCK:
        if _BT_READY:
            return True
        try:
            ok = await init_bluetooth_speaker(BT_SPEAKER_NAME)
        except Exception:
            logger.exception("[bt] init failed")
            ok = False
        _BT_READY = ok
        return ok


class ViAssistantConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self._pcm = bytearray()
        self._started = False
        self._language = "en"
        self._client = "generic"
        self._history = deque(
            _load_recent_turns(MAX_CONVERSATION_TURNS),
            maxlen=MAX_CONVERSATION_TURNS,
        )
        await self.accept()
        logger.warning("[ws] connected history_turns=%d", len(self._history))

    async def receive(self, text_data=None, bytes_data=None):
        if text_data:
            try:
                msg = json.loads(text_data)
            except Exception:
                await self.send(text_data=json.dumps({"type": "error", "error": "bad_json"}))
                return

            t = (msg.get("type") or "").strip().lower()
            if t == "start":
                self._pcm.clear()
                self._started = True
                self._language = (msg.get("language") or "en").strip() or "en"
                self._client = (msg.get("client") or "generic").strip().lower() or "generic"
                logger.warning("[ws] start language=%s", self._language)
                await self.send(text_data=json.dumps({"type": "ack", "status": "started"}))
                return

            if t == "stop":
                logger.warning("[ws] stop (pcm=%d bytes)", len(self._pcm))
                await self._finalize_and_reply()
                return

            await self.send(text_data=json.dumps({"type": "error", "error": "unknown_type"}))
            return

        if bytes_data:
            if not self._started:
                return
            self._pcm.extend(bytes_data)

    async def _finalize_and_reply(self):
        if not self._pcm:
            await self.send(text_data=json.dumps({"type": "result", "ok": False, "error": "empty_audio"}))
            return

        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            _write_wav(path, bytes(self._pcm))
            stt_cfg = STTConfig(language=self._language)
            stt_text = await asyncio.to_thread(stt_wav_to_text, path, stt_cfg)
            logger.warning("[ws] stt done text_len=%d text=%s", len(stt_text or ""), stt_text)
        finally:
            try:
                os.remove(path)
            except Exception:
                pass

        device_action = _detect_device_command(stt_text)
        sensor_query = _detect_sensor_query(stt_text)
        device_target = None
        device_result = None
        sensor_result = None
        if device_action:
            device_target = device_action.get("rooms") or device_action.get("room")
            try:
                device_result = await asyncio.to_thread(
                    _call_esp_relay, device_target, device_action["state"]
                )
            except Exception as e:
                device_result = {"ok": False, "error": str(e)}
        logger.warning("[ws] device action=%s", device_action)

        reply_source = "ai"
        history_snapshot = list(self._history)
        if device_action:
            reply_source = "device"
            ai_text = _format_device_reply(device_target, device_action["state"], device_result)
        elif sensor_query:
            reply_source = "sensor"
            try:
                sensor_result = await asyncio.to_thread(_call_esp_sensor)
            except Exception as e:
                logger.exception("[ws] sensor error: %s", e)
                sensor_result = {"ok": False, "error": str(e)}
            ai_text = _format_sensor_reply(
                sensor_result,
                sensor_query["temperature"],
                sensor_query["humidity"],
            )
            logger.warning("[ws] sensor query=%s", sensor_query)
        else:
            ai_text = await asyncio.to_thread(_call_ai, stt_text, history_snapshot)

        user_text = (stt_text or "").strip()
        assistant_text = (ai_text or "").strip()
        if user_text and assistant_text:
            self._history.append({"user": user_text, "assistant": assistant_text})
            try:
                await asyncio.to_thread(_append_history_entry, user_text, assistant_text)
            except Exception:
                logger.exception("[ws] failed writing history file")
            logger.warning("[ws] memory turns=%d", len(self._history))
        else:
            logger.warning(
                "[ws] history skipped user_len=%d assistant_len=%d",
                len(user_text),
                len(assistant_text),
            )
        logger.warning("[ws] reply done source=%s text_len=%d", reply_source, len(ai_text or ""))

        if self._client == "esp32":
            esp_tts_text = _shorten_tts_text(ai_text, ESP_INLINE_TTS_MAX_CHARS)
            if esp_tts_text != (ai_text or "").strip():
                logger.warning(
                    "[ws] esp tts shortened chars=%d->%d",
                    len((ai_text or "").strip()),
                    len(esp_tts_text),
                )

            tts_raw = await asyncio.to_thread(tts_text_to_wav_bytes, esp_tts_text) if esp_tts_text else b""
            tts_bytes = _normalize_wav_header(tts_raw)
            _debug_save_wav(tts_bytes, "esp")
            
            # Play audio on Bluetooth speaker (MAP140)
            if tts_bytes:
                try:
                    bt_ok = await _ensure_bt_ready()
                    if bt_ok:
                        logger.info("[ws] streaming TTS audio to Bluetooth speaker")
                        played = await play_tts_audio(tts_bytes)
                        if not played:
                            logger.warning("[ws] Bluetooth audio playback reported failure, fallback local")
                            await asyncio.to_thread(_play_wav_bytes_local, tts_bytes)
                    else:
                        logger.warning("[ws] Bluetooth init failed, skip playback")
                except Exception as e:
                    logger.warning("[ws] Bluetooth audio playback failed: %s", e)
                    await asyncio.to_thread(_play_wav_bytes_local, tts_bytes)
            
            await self.send(
                text_data=json.dumps(
                    {
                        "type": "result",
                        "ok": True,
                        "stt_text": stt_text,
                        "ai_text": ai_text,
                        "device_action": device_action,
                        "device_result": device_result,
                        "sensor_query": sensor_query,
                        "sensor_result": sensor_result,
                        "audio_stream": True,
                        "audio_format": "pcm_s16le",
                        "sample_rate": 16000,
                        "channels": 1,
                    }
                )
            )
            await self._send_tts_pcm_chunks(tts_bytes)
        else:
            tts_raw = await asyncio.to_thread(tts_text_to_wav_bytes, ai_text)
            tts_bytes = _normalize_wav_header(tts_raw)
            logger.warning("[ws] tts done bytes=%d", len(tts_bytes or b""))
            _debug_save_wav(tts_bytes, "server")
            
            # Play audio on Bluetooth speaker (MAP140)
            if tts_bytes:
                try:
                    bt_ok = await _ensure_bt_ready()
                    if bt_ok:
                        logger.info("[ws] streaming TTS audio to Bluetooth speaker")
                        played = await play_tts_audio(tts_bytes)
                        if not played:
                            logger.warning("[ws] Bluetooth audio playback reported failure, fallback local")
                            await asyncio.to_thread(_play_wav_bytes_local, tts_bytes)
                    else:
                        logger.warning("[ws] Bluetooth init failed, skip playback")
                except Exception as e:
                    logger.warning("[ws] Bluetooth audio playback failed: %s", e)
                    await asyncio.to_thread(_play_wav_bytes_local, tts_bytes)
            
            audio_b64 = base64.b64encode(tts_bytes).decode("ascii") if tts_bytes else ""
            await self.send(
                text_data=json.dumps(
                    {
                        "type": "result",
                        "ok": True,
                        "stt_text": stt_text,
                        "ai_text": ai_text,
                        "device_action": device_action,
                        "device_result": device_result,
                        "sensor_query": sensor_query,
                        "sensor_result": sensor_result,
                        "audio_b64": audio_b64,
                        "audio_mime": "audio/wav",
                    }
                )
            )

        # reset
        self._pcm.clear()
        self._started = False

    async def _send_tts_pcm_chunks(self, wav_bytes: bytes):
        if not wav_bytes:
            logger.warning("[ws] tts stream empty wav")
            await self.send(text_data=json.dumps({"type": "tts_end"}))
            return

        try:
            pcm = await asyncio.to_thread(self._wav_to_pcm16_mono, wav_bytes)
        except Exception:
            logger.exception("[ws] tts stream convert failed")
            await self.send(text_data=json.dumps({"type": "tts_end"}))
            return

        if not pcm:
            logger.warning("[ws] tts stream empty pcm")
            await self.send(text_data=json.dumps({"type": "tts_end"}))
            return

        chunk_size = max(320, ESP_TTS_STREAM_CHUNK_BYTES)
        chunk_size &= ~1  # keep 16-bit sample alignment
        chunk_count = (len(pcm) + chunk_size - 1) // chunk_size
        prefill_chunks = max(0, ESP_TTS_STREAM_PREFILL_CHUNKS)
        pace_factor = min(max(0.5, ESP_TTS_STREAM_PACE_FACTOR), 1.2)
        logger.warning(
            "[ws] tts stream start pcm=%d chunks=%d chunk_size=%d prefill=%d pace=%.2f",
            len(pcm),
            chunk_count,
            chunk_size,
            prefill_chunks,
            pace_factor,
        )
        await self.send(
            text_data=json.dumps(
                {
                    "type": "tts_start",
                    "audio_format": "pcm_s16le",
                    "sample_rate": 16000,
                    "channels": 1,
                    "bits_per_sample": 16,
                }
            )
        )

        bytes_per_second = 16000 * 2  # PCM16 mono 16k
        loop = asyncio.get_running_loop()
        chunk_index = 0
        for i in range(0, len(pcm), chunk_size):
            chunk = pcm[i : i + chunk_size]
            t0 = loop.time()
            await self.send(bytes_data=chunk)
            if chunk_index >= prefill_chunks:
                target = (len(chunk) / bytes_per_second) * pace_factor
                remain = target - (loop.time() - t0)
                if remain > 0:
                    await asyncio.sleep(remain)
            chunk_index += 1

        await self.send(text_data=json.dumps({"type": "tts_end"}))
        logger.warning("[ws] tts stream end")

    @staticmethod
    def _wav_to_pcm16_mono(wav_bytes: bytes) -> bytes:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            nframes = wf.getnframes()
            raw = wf.readframes(nframes)

        if sampwidth != 2:
            raise ValueError(f"unsupported sample width: {sampwidth}")

        if channels == 1:
            return raw

        # Downmix multi-channel 16-bit PCM to mono (simple average).
        import array

        src = array.array("h")
        src.frombytes(raw)
        frame_count = len(src) // channels
        out = array.array("h", [0] * frame_count)
        for i in range(frame_count):
            acc = 0
            base = i * channels
            for c in range(channels):
                acc += src[base + c]
            out[i] = int(acc / channels)
        return out.tobytes()
