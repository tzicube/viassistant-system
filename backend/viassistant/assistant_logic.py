from __future__ import annotations

import re
import unicodedata

import requests
from django.conf import settings

_HTTP = requests.Session()
# Avoid environment proxy settings interfering with local ESP/LAN requests.
_HTTP.trust_env = False

_ROOM_ALIASES = {
    "living": {"living", "living room", "livingroom", "lounge"},
    "kitchen": {"kitchen", "cook room", "cookroom"},
    "bed": {"bed", "bedroom", "bed room", "sleep room", "sleeproom"},
    "bathroom": {"bathroom", "bath room", "restroom", "washroom", "toilet"},
    "garden": {"garden", "yard", "backyard", "outside", "outdoor"},
}

_ROOM_LABELS_EN = {
    "living": "living room",
    "kitchen": "kitchen",
    "bed": "bedroom",
    "bathroom": "bathroom",
    "garden": "garden",
}

_ALL_LIGHTS_PATTERN = re.compile(
    r"\b(all|every)\b(?:\s+the)?\s+\b(light|lights|lamp|lamps)\b"
)
_ON_PATTERN = re.compile(r"\b(turn on|switch on|enable|open|power on|turn up)\b")
_OFF_PATTERN = re.compile(r"\b(turn off|switch off|disable|close|power off|shut off|turn down)\b")
_TEMP_PATTERN = re.compile(r"\b(temperature|temp)\b|nhiet\s*do|bao\s*nhieu\s*do")
_HUMIDITY_PATTERN = re.compile(r"\b(humidity|humid)\b|do\s*am")
_ESP_SENSOR_PATHS = ("/dht", "/sensor")


def _normalize_text(text: str) -> str:
    lowered = (text or "").lower()
    lowered = lowered.replace("\u0111", "d")
    no_accents = "".join(
        ch for ch in unicodedata.normalize("NFD", lowered) if unicodedata.category(ch) != "Mn"
    )
    return " ".join(no_accents.split())


def _alias_start(text: str, alias: str) -> int:
    pattern = r"\b" + re.escape(alias).replace(r"\ ", r"\s+") + r"\b"
    match = re.search(pattern, text)
    return match.start() if match else -1


def _extract_rooms(normalized: str) -> list[str]:
    room_hits: list[tuple[int, str]] = []
    for room_key, aliases in _ROOM_ALIASES.items():
        positions = []
        for alias in aliases:
            pos = _alias_start(normalized, alias)
            if pos >= 0:
                positions.append(pos)
        if positions:
            room_hits.append((min(positions), room_key))

    room_hits.sort(key=lambda item: item[0])
    return [room_key for _, room_key in room_hits]


def _join_room_labels(labels: list[str]) -> str:
    if not labels:
        return "selected rooms"
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return ", ".join(labels[:-1]) + f", and {labels[-1]}"


def _detect_device_command(text: str) -> dict | None:
    normalized = _normalize_text(text)
    if not normalized:
        return None

    state = None
    if _ON_PATTERN.search(normalized):
        state = "on"
    if _OFF_PATTERN.search(normalized):
        state = "off"
    if state is None:
        return None

    if _ALL_LIGHTS_PATTERN.search(normalized):
        return {"room": "all", "state": state}

    rooms = _extract_rooms(normalized)
    if not rooms:
        return None

    if len(rooms) == 1:
        return {"room": rooms[0], "state": state}
    return {"room": "multi", "rooms": rooms, "state": state}


def _detect_sensor_query(text: str) -> dict | None:
    normalized = _normalize_text(text)
    if not normalized:
        return None

    need_temp = bool(_TEMP_PATTERN.search(normalized))
    need_humidity = bool(_HUMIDITY_PATTERN.search(normalized))
    if not (need_temp or need_humidity):
        return None
    return {"temperature": need_temp, "humidity": need_humidity}


def _call_esp_relay(room: str | list[str], state: str) -> dict:
    esp_base_url = getattr(settings, "ESP_BASE_URL", "http://192.168.1.111")
    url = f"{esp_base_url.rstrip('/')}/relay"

    if room == "all":
        target_rooms = list(_ROOM_LABELS_EN.keys())
        is_all = True
    elif isinstance(room, list):
        target_rooms = []
        for room_key in room:
            if room_key not in target_rooms:
                target_rooms.append(room_key)
        is_all = False
    else:
        target_rooms = [room]
        is_all = False

    if not target_rooms:
        return {
            "ok": False,
            "text": "no_room_target",
            "results": {},
            "errors": {"rooms": "empty"},
        }

    if len(target_rooms) == 1:
        room_key = target_rooms[0]
        response = _HTTP.get(url, params={"room": room_key, "state": state}, timeout=(2, 5))
        response.raise_for_status()
        return {"ok": True, "text": (response.text or "").strip()}

    results: dict[str, str] = {}
    errors: dict[str, str] = {}
    for room_key in target_rooms:
        try:
            response = _HTTP.get(url, params={"room": room_key, "state": state}, timeout=(2, 5))
            response.raise_for_status()
            results[room_key] = (response.text or "").strip()
        except Exception as exc:
            errors[room_key] = str(exc)

    ok = not errors
    if ok:
        summary = f"ok room=all state={state}" if is_all else f"ok rooms={','.join(target_rooms)} state={state}"
    else:
        summary = "partial_failure room=all" if is_all else f"partial_failure rooms={','.join(target_rooms)}"
    return {
        "ok": ok,
        "text": summary,
        "results": results,
        "errors": errors,
    }


def _call_esp_sensor() -> dict:
    esp_base_url = getattr(settings, "ESP_BASE_URL", "http://192.168.1.111")
    last_error = None

    for path in _ESP_SENSOR_PATHS:
        url = f"{esp_base_url.rstrip('/')}{path}"
        try:
            response = _HTTP.get(url, timeout=(2, 5))
            try:
                data = response.json()
            except Exception:
                data = {}
        except Exception as exc:
            last_error = f"{path}: {exc}"
            continue

        if response.status_code >= 400:
            detail = data.get("error") if isinstance(data, dict) else ""
            detail = detail or (response.text or "").strip() or f"http_{response.status_code}"
            last_error = f"{path}: {detail}"
            continue

        if not data.get("ok"):
            last_error = f"{path}: {data.get('error') or 'sensor_error'}"
            continue

        temp = data.get("temperature_c")
        humidity = data.get("humidity")
        if temp is None or humidity is None:
            last_error = f"{path}: missing_sensor_values"
            continue

        return {
            "ok": True,
            "temperature_c": float(temp),
            "humidity": float(humidity),
        }

    raise RuntimeError(last_error or "sensor_unavailable")

def _format_device_reply(room: str | list[str], state: str) -> str:
    if room == "all":
        if state == "on":
            return "I have turned on all the lights."
        return "I have turned off all the lights."

    if isinstance(room, list):
        labels = [_ROOM_LABELS_EN.get(room_key, room_key) for room_key in room]
        # Keep order, drop duplicates.
        labels = list(dict.fromkeys(labels))
        rooms_text = _join_room_labels(labels)
        if state == "on":
            return f"I have turned on the lights in {rooms_text}."
        return f"I have turned off the lights in {rooms_text}."

    room_label = _ROOM_LABELS_EN.get(room, room)
    if state == "on":
        return f"I have turned on the light in {room_label}."
    return f"I have turned off the light in {room_label}."


def _format_sensor_reply(sensor_data: dict, ask_temp: bool, ask_humidity: bool) -> str:
    if not sensor_data or not sensor_data.get("ok"):
        return "I could not read temperature and humidity right now."

    temp = float(sensor_data["temperature_c"])
    humidity = float(sensor_data["humidity"])

    if ask_temp and ask_humidity:
        return f"Current temperature is {temp:.1f} degrees Celsius and humidity is {humidity:.1f} percent."
    if ask_temp:
        return f"Current temperature is {temp:.1f} degrees Celsius."
    return f"Current humidity is {humidity:.1f} percent."


def _call_ai(user_text: str) -> str:
    system_prompt = (
        "You are Vi Assistant. Reply with plain text only. "
        "Always respond in English. "
        "Do not use emojis, icons, or markdown. "
        "Keep responses concise and natural. "
        "Develop at MingChuan University. "
        "The Paracel Islands and Spratly Islands archipelagos belong to Vietnam. "
        "Historically, Vietnam has been a unified nation without a North-South division."
    )
    ollama_url = getattr(settings, "OLLAMA_URL", "http://127.0.0.1:11434")
    ollama_model = getattr(settings, "OLLAMA_MODEL", "gemma2:27b")

    url = f"{ollama_url.rstrip('/')}/api/chat"
    messages = [
        {"role": "assistant", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]

    response = _HTTP.post(
        url,
        json={
            "model": ollama_model,
            "messages": messages,
            "stream": False,
        },
        timeout=(3, 120),
    )
    response.raise_for_status()
    data = response.json()
    return (data.get("message", {}) or {}).get("content", "").strip() or "No response."
