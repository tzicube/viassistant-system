import json
import os
import tempfile
import requests

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from customer import stt_from_audio_file
from .models import insert_topic, insert_title_row  , list_topics  , get_topic_detail

SUPPORTED_LANGS = {"vi", "en", "zh"}

OLLAMA_URL = "http://127.0.0.1:11434/v1/chat/completions"
OLLAMA_MODEL = "gemma2:27b"


def _lang_label(lang: str) -> str:
    if lang == "vi":
        return "Vietnamese"
    if lang == "en":
        return "English"
    if lang == "zh":
        return "Traditional Chinese (繁體中文)"
    return lang


def translate_text(text: str, source_language: str, target_language: str, title_name: str) -> str:
    src = _lang_label(source_language)
    tgt = _lang_label(target_language)

    system = (
        "You are a professional translator.\n"
        "Rules:\n"
        "- Output ONLY the translated text. No explanations, no quotes.\n"
        "- Preserve numbers, proper nouns, and formatting.\n"
        "- If target is Traditional Chinese, use 繁體中文.\n" \
        "The translated content must be entirely in the chosen language. Exceptions include specialized English terminology, which may be retained in its original form.\n"
    )

    user = (
        f"Translate from {src} to {tgt}.\n"
        f"Domain/Topic (for terminology): {title_name}\n"
        f"Text:\n{text}"
    )

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "stream": False,
    }

    r = requests.post(OLLAMA_URL, json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    return (data["choices"][0]["message"]["content"] or "").strip()


@csrf_exempt
def api_new_topic(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST only"}, status=405)

    try:
        body = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "invalid JSON"}, status=400)

    title_name = (body.get("title_name") or "").strip()
    if not title_name:
        return JsonResponse({"error": "missing title_name"}, status=400)

    title_id = insert_topic(title_name)

    return JsonResponse({"ok": True, "title_id": title_id, "title_name": title_name})

@csrf_exempt
def api_record_history(request):
    if request.method != "GET":
        return JsonResponse({"ok": False, "error": "GET only"}, status=405)

    titles = list_topics()
    return JsonResponse({"titles": titles})

@csrf_exempt
def api_record_detail(request):
    if request.method != "GET":
        return JsonResponse({"ok": False, "error": "GET only"}, status=405)

    title_id_raw = (request.GET.get("title_id") or "").strip()
    if not title_id_raw.isdigit():
        return JsonResponse({"ok": False, "error": "missing or invalid title_id"}, status=400)

    title_id = int(title_id_raw)
    data = get_topic_detail(title_id)

    if not data:
        return JsonResponse({"ok": False, "error": "title_id not found"}, status=404)

    # format đúng theo ảnh (không cần ok/http_status)
    return JsonResponse(data)

@csrf_exempt
def api_virecord(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST only"}, status=405)

    audio_file = request.FILES.get("audio")
    if not audio_file:
        return JsonResponse({"ok": False, "error": "missing 'audio' file"}, status=400)

    # nhận topic
    title_id_raw = (request.POST.get("title_id") or "").strip()
    title_name = (request.POST.get("title_name") or "chủ đề máy tính").strip()

    # nhận ngôn ngữ
    source_language = (request.POST.get("source_language") or "vi").strip()
    target_language = (request.POST.get("target_language") or "zh").strip()

    if source_language not in SUPPORTED_LANGS:
        return JsonResponse({"ok": False, "error": f"invalid source_language: {source_language}"}, status=400)
    if target_language not in SUPPORTED_LANGS:
        return JsonResponse({"ok": False, "error": f"invalid target_language: {target_language}"}, status=400)
    if source_language == target_language:
        return JsonResponse({"ok": False, "error": "source_language and target_language must differ"}, status=400)

    # nếu FE không gửi title_id -> tạo topic mới
    if title_id_raw.isdigit():
        title_id = int(title_id_raw)
    else:
        title_id = insert_topic(title_name)

    tmp_path = None
    try:
        filename = (audio_file.name or "").lower()
        ext = os.path.splitext(filename)[1] or ".webm"

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            for chunk in audio_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        original_text = (stt_from_audio_file(tmp_path, language=source_language) or "").strip()
        if not original_text:
            return JsonResponse({"ok": False, "error": "STT returned empty text"}, status=400)

        try:
            translated_text = translate_text(
                text=original_text,
                source_language=source_language,
                target_language=target_language,
                title_name=title_name,
            )
        except Exception as e:
            return JsonResponse({"ok": False, "error": f"AI translate failed: {e}"}, status=502)

        # ✅ ghi DB: update vào topic đã chọn
        insert_title_row(title_id=title_id, original_text=original_text, translated_text=translated_text)

        return JsonResponse({
            "ok": True,
            "title_id": title_id,
            "title_name": title_name,
            "original_text": original_text,
            "translated_text": translated_text,
        })

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
