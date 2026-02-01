import time
import json
from django.http import JsonResponse , StreamingHttpResponse 
from django.views.decorators.csrf import csrf_exempt
from .models import Conversation, Message
from django.db import transaction
import requests
from django.conf import settings 
from config.settings import OLLAMA_URL, OLLAMA_MODEL
from .memory import get_history_messages, format_app_memory_text, set_app_memory
from django.views.decorators.http import require_POST
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_MODEL = "gemma2:27b" #  qwen2.5:14b    gemma2:27b
# ✅ reuse HTTP connection (keep-alive)
_http = requests.Session()

def save_message(conversation_id: int, role: str, content: str) -> Conversation:
    """
    Lưu 1 message vào DB theo conversation_id.
    Nếu conversation chưa tồn tại thì tự tạo.
    Trả về conv (Conversation instance).
    """
    conv, _ = Conversation.objects.get_or_create(id=conversation_id)
    Message.objects.create(conversation=conv, role=role, content=content)
    return conv

@csrf_exempt
def chat(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST method is allowed"}, status=405)

    data = json.loads(request.body or "{}")
    
    conversation_id = data.get("conversation_id")
    user_text = (data.get("message") or "").strip()

    if not conversation_id:
        return JsonResponse({"error": "conversation_id is required"}, status=400)
    if not user_text:
        return JsonResponse({"error": "message is required"}, status=400)

    
    
    # Save to data base 
    conv = save_message(conversation_id, "user", user_text)
    assistant_text = call_ai(conv.id, user_text)
    save_message(conv.id, "assistant", assistant_text)


    return JsonResponse({
        "message": {
            "conversation_id": conv.id,
            "role": "assistant",
            "content": assistant_text
        }
    })

def call_ai(conversation_id: int, user_text: str) -> str:
    system_prompt = getattr(settings, "AI_SYSTEM_PROMPT", "You are a helpful assistant.")

    # 1) global memory text
    app_memory_text = format_app_memory_text()

    # 2) full history
    history = get_history_messages(conversation_id)

    messages = []

    # ===== A) SYSTEM PROMPT =====
    # Chuẩn là role="system". Nhưng anh muốn role="assistant" thì để như dưới:
    messages.append({"role": "assistant", "content": system_prompt})

    # ===== B) APP MEMORY =====
    if app_memory_text.strip():
        # cái này cũng nên là system, nhưng nếu anh muốn đồng bộ thì để assistant
        messages.append({"role": "assistant", "content": app_memory_text})

    # ===== C) HISTORY + CURRENT USER =====
    messages.extend(history)

    # đảm bảo user_text có mặt (trong trường hợp history chưa có)
    if not history or history[-1].get("role") != "user" or history[-1].get("content") != user_text:
        messages.append({"role": "user", "content": user_text})

    r = _http.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False
        },
        timeout=(3, 120)
    )
    r.raise_for_status()
    data = r.json()
    return (data.get("message", {}) or {}).get("content", "").strip() or "No response."

@csrf_exempt
def create_conversation(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST method is allowed"}, status=405)

    data = json.loads(request.body or "{}")
    user_text = (data.get("message") or "").strip()

    if not user_text:
        return JsonResponse({"error": "message is required"}, status=400)

    # 1) tạo conversation
    conv = Conversation.objects.create(title="")

    # 2) lưu message đầu tiên (user)
    save_message(conv.id, "user", user_text)

    # 3) trả lời assistant + lưu DB
    assistant_text = call_ai(conv.id, user_text)
    save_message(conv.id, "assistant", assistant_text)

    # 4) tạo title prompt
    title_prompt = (
        "Based on the user's message, generate a very short chat title (max 6 words). "
        "Return ONLY the title, no quotes, no punctuation.\n"
        f"User message: {user_text}"
    )

    # 5) gọi AI để tạo title (dùng cùng conversation_id cho tiện)
    ai_title = call_ai(conv.id, title_prompt)

    # 6) làm sạch title
    ai_title = (ai_title or "").strip().replace("\n", " ")
    if not ai_title:
        ai_title = f"Conversation {conv.id}"
    if len(ai_title) > 60:
        ai_title = ai_title[:60].strip()

    # 7) lưu title
    conv.title = ai_title
    conv.save(update_fields=["title"])

    # 8) trả về
    return JsonResponse({
        "conversation_id": conv.id,
        "title": conv.title,
        "message": {
            "conversation_id": conv.id,
            "role": "assistant",
            "content": assistant_text
        }
    }, status=201)




@csrf_exempt
def list_conversations(request):
    if request.method != "GET":
        return JsonResponse({"error": "Only GET method is allowed"}, status=405)

    qs = Conversation.objects.filter(is_deleted=False).order_by("-id")

    conversations = []
    for c in qs:
        conversations.append({
            "conversation_id": c.id,
            "title": c.title or f"Conversation {c.id}"
        })

    return JsonResponse({"conversations": conversations}, status=200)



@csrf_exempt
def conversation_detail(request, conversation_id: int):
    if request.method != "GET":
        return JsonResponse({"error": "Only GET method is allowed"}, status=405)

    try:
        conv = Conversation.objects.get(id=conversation_id, is_deleted=False)

    except Conversation.DoesNotExist:
        return JsonResponse({"error": "Conversation not found"}, status=404)

    qs = Message.objects.filter(conversation_id=conversation_id).order_by("created_at")

    messages = [
        {
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat()
        }
        for m in qs
    ]

    return JsonResponse({
        "conversation_id": conv.id,
        "title": conv.title or f"Conversation {conv.id}",
        "messages": messages
    }, status=200)

@csrf_exempt
def delete_conversation(request, conversation_id):
    if request.method != "DELETE":
        return JsonResponse({"error": "Only DELETE method is allowed"}, status=405)

    # ✅ debug chứng cứ
    last_ids = list(Conversation.objects.order_by("-id").values_list("id", flat=True)[:10])
    exists = Conversation.objects.filter(id=conversation_id).exists()

    if not exists:
        return JsonResponse({
            "error": "Conversation not found",
            "asked_id": conversation_id,
            "last_ids_in_db": last_ids,
        }, status=404)

    conv = Conversation.objects.get(id=conversation_id)
    conv.is_deleted = True
    conv.save(update_fields=["is_deleted"])
    return JsonResponse({"success": True, "deleted_id": conversation_id}, status=200)


def ollama_stream(messages):
    with _http.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": True
        },
        stream=True,
        timeout=(3, 120)
    ) as r:
        r.raise_for_status()

        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue

            obj = json.loads(line)

            chunk = ((obj.get("message") or {}).get("content") or "")
            if chunk:
                yield chunk

            if obj.get("done") is True:
                break
@csrf_exempt
def chat_stream(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST method is allowed"}, status=405)

    data = json.loads(request.body or "{}")
    conversation_id = data.get("conversation_id")
    user_text = (data.get("message") or "").strip()

    if not conversation_id:
        return JsonResponse({"error": "conversation_id is required"}, status=400)
    if not user_text:
        return JsonResponse({"error": "message is required"}, status=400)

    # 1) lưu user message
    conv = save_message(conversation_id, "user", user_text)

    system_prompt = getattr(settings, "AI_SYSTEM_PROMPT", "You are a helpful assistant.")

    # ✅ GIỮ NGUYÊN theo ý anh (assistant prompt)
    app_memory_text = format_app_memory_text()
    history = get_history_messages(conv.id)

    messages = []
    messages.append({"role": "assistant", "content": system_prompt})

    if app_memory_text.strip():
        messages.append({"role": "assistant", "content": app_memory_text})

    messages.extend(history)

    if not history or history[-1].get("role") != "user" or history[-1].get("content") != user_text:
        messages.append({"role": "user", "content": user_text})


    def event_stream():
        full = []
        try:
            # 2) stream token ra dần
            for chunk in ollama_stream(messages):
                full.append(chunk)
                # SSE format
                yield f"data: {chunk}\n\n"

            # 3) lưu assistant message sau khi xong
            assistant_text = "".join(full).strip() or "No response."
            save_message(conv.id, "assistant", assistant_text)

            yield "event: done\ndata: [DONE]\n\n"

        except Exception as e:
            yield f"event: error\ndata: {str(e)}\n\n"

    resp = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp


@csrf_exempt
@require_POST
def translate_audio(request):
    audio = request.FILES.get("audio")
    title = request.POST.get("title", "").strip()
    input_lang = request.POST.get("input_lang", "").strip()
    output_lang = request.POST.get("output_lang", "").strip()
    setting = request.POST.get("setting", "").strip()

    if not audio:
        return JsonResponse({"ok": False, "error": "missing_audio"}, status=400)
    if not input_lang:
        return JsonResponse({"ok": False, "error": "missing_input_lang"}, status=400)
    if not output_lang:
        return JsonResponse({"ok": False, "error": "missing_output_lang"}, status=400)

    # tối giản: title/setting cho phép rỗng
    if not title:
        title = "default"
    if not setting:
        setting = "Translate accurately using the title and chat history."

    try:
        data = process_translate_audio(
            title=title,
            input_lang=input_lang,
            output_lang=output_lang,
            setting=setting,
            uploaded_file=audio
        )
        return JsonResponse(data, status=200)
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=500)