from __future__ import annotations

import base64
import json
import os
import tempfile
import wave
import re
import time
import logging

import requests
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .voice_pipeline import STTConfig, stt_wav_to_text, tts_text_to_wav_bytes

_HTTP = requests.Session()
logger = logging.getLogger("viassistant")
_ESP_BASE_URL = "http://192.168.1.111"

_ROOM_ALIASES = {
    "living": {"living", "living room", "livingroom", "lounge"},
    "kitchen": {"kitchen", "cook room", "cookroom"},
    "bed": {"bed", "bedroom", "bed room", "sleep room", "sleeproom"},
}

_ROOM_LABELS_EN = {
    "living": "living room",
    "kitchen": "kitchen",
    "bed": "bedroom",
}


def _detect_device_command(text: str) -> dict | None:
    t = " ".join((text or "").lower().split())
    if not t:
        return None

    state = None
    if re.search(r"\b(turn on|switch on|enable|open|power on)\b", t):
        state = "on"
    if re.search(r"\b(turn off|switch off|disable|close|power off)\b", t):
        state = "off"
    if state is None:
        return None

    room = None
    for key, aliases in _ROOM_ALIASES.items():
        for a in aliases:
            if a in t:
                room = key
                break
        if room:
            break

    if not room:
        return None

    return {"room": room, "state": state}


def _call_esp_relay(room: str, state: str) -> dict:
    url = f"{_ESP_BASE_URL.rstrip('/')}/relay"
    r = _HTTP.get(url, params={"room": room, "state": state}, timeout=(2, 5))
    r.raise_for_status()
    return {"ok": True, "text": (r.text or "").strip()}


def _read_wav_info(path: str) -> dict:
    with wave.open(path, "rb") as wf:
        return {
            "channels": wf.getnchannels(),
            "sample_width": wf.getsampwidth(),
            "sample_rate": wf.getframerate(),
            "frames": wf.getnframes(),
            "duration_sec": wf.getnframes() / float(wf.getframerate() or 1),
        }


def _call_ai(user_text: str) -> str:
    system_prompt = (
        "You are Vi Assistant. Reply with plain text only. "
        "Do not use emojis, icons, or markdown. "
        "Keep responses concise and natural."
        "Develop at MingChuan University"
    )
    ollama_url = getattr(settings, "OLLAMA_URL", "http://127.0.0.1:11434")
    ollama_model = getattr(settings, "OLLAMA_MODEL", "gemma2:9b")

    url = f"{ollama_url.rstrip('/')}/api/chat"
    messages = [
        {"role": "assistant", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]

    r = _HTTP.post(
        url,
        json={
            "model": ollama_model,
            "messages": messages,
            "stream": False,
        },
        timeout=(3, 120),
    )
    r.raise_for_status()
    data = r.json()
    return (data.get("message", {}) or {}).get("content", "").strip() or "No response."


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
        device_result = None
        if device_action:
            try:
                device_result = _call_esp_relay(device_action["room"], device_action["state"])
            except Exception as e:
                device_result = {"ok": False, "error": str(e)}
        logger.warning("[voice] device done (%.2fs)", time.time() - t0)

        if device_action:
            temp = room_label if room_label != "kitchen" else None
            room_label = _ROOM_LABELS_EN.get(device_action["room"], device_action["room"])
            if device_action["state"] == "on":
                ai_text = f"I have turned on the light in {room_label}" + temp
            else:
                ai_text = f"I have turned off the light in {room_label}" + temp
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
                    },
                    status=200,
                )
            logger.warning("[voice] ai done (%.2fs)", time.time() - t0)

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
            },
            status=200,
        )
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
