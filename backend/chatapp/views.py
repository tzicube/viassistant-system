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
#ollama run gemma2:27b

# ✅ reuse HTTP connection (keep-alive)
_http = requests.Session()

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

    # (1) DB: get/create + save user msg
  
    conv, _ = Conversation.objects.get_or_create(id=conversation_id)
    Message.objects.create(conversation=conv, role="user", content=user_text)
 

    # (2) AI
    assistant_text = call_ai(user_text)


    # (3) DB: save assistant msg
    Message.objects.create(conversation=conv, role="assistant", content=assistant_text)

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


