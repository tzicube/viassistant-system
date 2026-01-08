import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import Conversation, Message
import requests

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

    # (1) lấy conversation
    conv, _ = Conversation.objects.get_or_create(id=conversation_id)

    # (2) lưu message user vào DB
    Message.objects.create(conversation=conv, role="user", content=user_text)

    # (3) trả lời 
    assistant_text = call_ai(user_text)

    # (4) lưu message assistant vào DB
    Message.objects.create(conversation=conv, role="assistant", content=assistant_text)

    # (5) trả JSON đúng format FE cần
    return JsonResponse({
        "message": {
            "conversation_id": conv.id,
            "role": "assistant",
            "content": assistant_text
        }
    })

def call_ai(user_text: str) -> str:
    r = requests.post(
        "http://127.0.0.1:11434/api/chat",
        json={
            "model": "llama3.2-vision",
            "messages": [
                {"role": "user", "content": user_text}
            ],
            "stream": False
        },
        timeout=60
    )
    r.raise_for_status()
    data = r.json()
    return (data.get("message", {}) or {}).get("content", "").strip() or "No response."

