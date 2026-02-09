from __future__ import annotations

import base64
import os
import tempfile
import wave
import time
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .assistant_logic import (
    _call_ai,
    _call_esp_relay,
    _call_esp_sensor,
    _detect_device_command,
    _detect_sensor_query,
    _format_device_reply,
    _format_sensor_reply,
)
from .voice_pipeline import STTConfig, stt_wav_to_text, tts_text_to_wav_bytes

logger = logging.getLogger("viassistant")


def _read_wav_info(path: str) -> dict:
    with wave.open(path, "rb") as wf:
        return {
            "channels": wf.getnchannels(),
            "sample_width": wf.getsampwidth(),
            "sample_rate": wf.getframerate(),
            "frames": wf.getnframes(),
            "duration_sec": wf.getnframes() / float(wf.getframerate() or 1),
        }


@csrf_exempt
@require_POST
def voice(request):
    """
    HTTP pipeline: WAV -> STT -> AI -> TTS -> return audio (base64).
    """
    audio = request.FILES.get("audio")
    language = (request.POST.get("language") or "").strip() or None

    if not audio:
        return JsonResponse({"ok": False, "error": "missing_audio"}, status=400)

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
            for chunk in audio.chunks():
                tmp.write(chunk)

        try:
            wav_info = _read_wav_info(tmp_path)
        except wave.Error as e:
            return JsonResponse({"ok": False, "error": f"bad_wav: {e}"}, status=400)

        t0 = time.time()
        logger.warning("[voice] start request")

        cfg = STTConfig(language=language)
        stt_text = stt_wav_to_text(tmp_path, cfg)
        logger.warning("[voice] stt done (%.2fs)", time.time() - t0)
        if not stt_text:
            return JsonResponse(
                {"ok": False, "error": "stt_empty", "wav_info": wav_info},
                status=200,
            )

        device_action = _detect_device_command(stt_text)
        sensor_query = _detect_sensor_query(stt_text)
        device_target = None
        device_result = None
        sensor_result = None
        if device_action:
            device_target = device_action.get("rooms") or device_action.get("room")
            try:
                device_result = _call_esp_relay(device_target, device_action["state"])
            except Exception as e:
                device_result = {"ok": False, "error": str(e)}
        logger.warning("[voice] device done (%.2fs)", time.time() - t0)

        reply_source = "ai"
        if device_action:
            reply_source = "device"
            ai_text = _format_device_reply(device_target, device_action["state"])
        elif sensor_query:
            reply_source = "sensor"
            try:
                sensor_result = _call_esp_sensor()
            except Exception as e:
                logger.exception("[voice] sensor error: %s", e)
                sensor_result = {"ok": False, "error": str(e)}
            ai_text = _format_sensor_reply(
                sensor_result,
                sensor_query["temperature"],
                sensor_query["humidity"],
            )
            logger.warning("[voice] sensor done (%.2fs)", time.time() - t0)
        else:
            try:
                ai_text = _call_ai(stt_text)
            except Exception as e:
                logger.exception("[voice] ai error: %s", e)
                return JsonResponse(
                    {
                        "ok": False,
                        "error": "ai_error",
                        "detail": str(e),
                        "stt_text": stt_text,
                        "device_action": device_action,
                        "device_result": device_result,
                        "sensor_query": sensor_query,
                        "sensor_result": sensor_result,
                    },
                    status=200,
                )
        logger.warning("[voice] reply done source=%s (%.2fs)", reply_source, time.time() - t0)

        tts_bytes = tts_text_to_wav_bytes(ai_text)
        logger.warning("[voice] tts done (%.2fs)", time.time() - t0)

        audio_b64 = base64.b64encode(tts_bytes).decode("ascii") if tts_bytes else ""

        return JsonResponse(
            {
                "ok": True,
                "stt_text": stt_text,
                "ai_text": ai_text,
                "audio_b64": audio_b64,
                "audio_mime": "audio/wav",
                "wav_info": wav_info,
                "device_action": device_action,
                "device_result": device_result,
                "sensor_query": sensor_query,
                "sensor_result": sensor_result,
            },
            status=200,
        )
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
