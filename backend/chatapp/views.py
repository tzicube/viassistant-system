import time
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import Conversation, Message
from django.db import transaction
import requests
from django.conf import settings

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_MODEL = "gemma2:27b" 
#qwen2.5-coder:14b
#llama3.2-vision


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
    assistant_text = call_ai(user_text)
    save_message(conv.id, "assistant", assistant_text)


    return JsonResponse({
        "message": {
            "conversation_id": conv.id,
            "role": "assistant",
            "content": assistant_text
        }
    })

def call_ai(user_text: str) -> str:
    system_prompt = getattr(settings, "AI_SYSTEM_PROMPT", "You are a helpful assistant.")

    messages = [
        {"role": "assistant", "content": system_prompt},
    ]
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
    assistant_text = call_ai(user_text)
    save_message(conv.id, "assistant", assistant_text)

    # 4) tạo title
    title_prompt = (
        "Based on the user's message, generate a very short chat title (max 6 words). "
        "Return ONLY the title, no quotes, no punctuation.\n"
        f"User message: {user_text}"
    )
    ai_title = call_ai(title_prompt)

    # 5) làm sạch title
    ai_title = (ai_title or "").strip().replace("\n", " ")
    if not ai_title:
        ai_title = f"Conversation {conv.id}"
    if len(ai_title) > 60:
        ai_title = ai_title[:60].strip()

    # ✅ 6) LƯU TITLE VÀO DB
    conv.title = ai_title
    conv.save(update_fields=["title"])

    # 7) trả về
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

def delete_conversation(request, conversation_id):
    if request.method != "DELETE":
        return JsonResponse({"error": "Only DELETE method is allowed"}, status=405)

    try:
        conv = Conversation.objects.get(id=conversation_id)
    except Conversation.DoesNotExist:
        return JsonResponse({"error": "Conversation not found"}, status=404)

    conv.is_deleted = True
    conv.save(update_fields=["is_deleted"])

    return JsonResponse({"success": True})