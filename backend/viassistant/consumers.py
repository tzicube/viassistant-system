from __future__ import annotations

import base64
import os
import tempfile
import json
import asyncio
import logging
import wave
import io

from channels.generic.websocket import AsyncWebsocketConsumer

from .voice_pipeline import STTConfig, stt_wav_to_text, tts_text_to_wav_bytes
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


def _write_wav(path: str, pcm: bytes, sample_rate: int = 16000, channels: int = 1, sampwidth: int = 2):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)


class ViAssistantConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self._pcm = bytearray()
        self._started = False
        self._language = "en"
        self._client = "generic"
        await self.accept()
        logger.warning("[ws] connected")

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
        if device_action:
            reply_source = "device"
            ai_text = _format_device_reply(device_target, device_action["state"])
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
            ai_text = await asyncio.to_thread(_call_ai, stt_text)
        logger.warning("[ws] reply done source=%s text_len=%d", reply_source, len(ai_text or ""))

        tts_bytes = await asyncio.to_thread(tts_text_to_wav_bytes, ai_text)
        logger.warning("[ws] tts done bytes=%d", len(tts_bytes or b""))

        if self._client == "esp32":
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

        chunk_size = 1024
        chunk_count = (len(pcm) + chunk_size - 1) // chunk_size
        logger.warning("[ws] tts stream start pcm=%d chunks=%d", len(pcm), chunk_count)
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

        for i in range(0, len(pcm), chunk_size):
            await self.send(bytes_data=pcm[i : i + chunk_size])

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
