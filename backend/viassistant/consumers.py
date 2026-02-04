from __future__ import annotations

import base64
import os
import tempfile
import json
import asyncio
import logging

from channels.generic.websocket import AsyncWebsocketConsumer

from .voice_pipeline import STTConfig, stt_wav_to_text, tts_text_to_wav_bytes
from .views import _detect_device_command, _call_esp_relay, _call_ai

logger = logging.getLogger("viassistant.ws")


def _write_wav(path: str, pcm: bytes, sample_rate: int = 16000, channels: int = 1, sampwidth: int = 2):
    import wave
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
        device_result = None
        if device_action:
            try:
                device_result = await asyncio.to_thread(
                    _call_esp_relay, device_action["room"], device_action["state"]
                )
            except Exception as e:
                device_result = {"ok": False, "error": str(e)}
        logger.warning("[ws] device action=%s", device_action)

        if device_action:
            room = device_action["room"]
            if device_action["state"] == "on":
                ai_text = f"I have turned on the {room} light."
            else:
                ai_text = f"I have turned off the {room} light."
        else:
            ai_text = await asyncio.to_thread(_call_ai, stt_text)
        logger.warning("[ws] ai done text_len=%d", len(ai_text or ""))

        tts_bytes = await asyncio.to_thread(tts_text_to_wav_bytes, ai_text)
        audio_b64 = base64.b64encode(tts_bytes).decode("ascii") if tts_bytes else ""
        logger.warning("[ws] tts done bytes=%d", len(tts_bytes or b""))

        await self.send(
            text_data=json.dumps(
                {
                    "type": "result",
                    "ok": True,
                    "stt_text": stt_text,
                    "ai_text": ai_text,
                    "device_action": device_action,
                    "device_result": device_result,
                    "audio_b64": audio_b64,
                    "audio_mime": "audio/wav",
                }
            )
        )

        # reset
        self._pcm.clear()
        self._started = False
