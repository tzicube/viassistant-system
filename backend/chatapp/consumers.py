import json
import httpx

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from django.conf import settings

from config.settings import OLLAMA_URL, OLLAMA_MODEL
from .models import Conversation, Message
from .memory import get_history_messages, format_app_memory_text
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_MODEL = "gemma2:27b" #  qwen2.5:14b    gemma2:27b

class ViChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        await self.accept()
        await self.send_json({"type": "ws.connected"})

    async def receive_json(self, content, **kwargs):
        t = (content or {}).get("type")

        if t == "chat.send":
            await self._handle_chat_send(content)
            return

        await self.send_json({"type": "chat.error", "error": "unknown_message_type"})

    async def _handle_chat_send(self, content: dict):
        conversation_id = content.get("conversation_id")
        user_text = (content.get("message") or "").strip()

        if not conversation_id:
            await self.send_json({"type": "chat.error", "error": "conversation_id is required"})
            return
        if not user_text:
            await self.send_json({"type": "chat.error", "error": "message is required"})
            return

        # 1) Save user message
        conv_id = await self._save_message(conversation_id, "user", user_text)

        # 2) Build messages giữ nguyên logic của views.py
        messages = await self._build_ollama_messages(conv_id, user_text)

        # 3) Stream token về client
        full = []
        try:
            await self.send_json({"type": "chat.start", "conversation_id": conv_id})

            async for chunk in self._ollama_stream_async(messages):
                if chunk:
                    full.append(chunk)
                    await self.send_json({"type": "chat.delta", "text_delta": chunk})

            assistant_text = "".join(full).strip() or "No response."

            # 4) Save assistant message
            await self._save_message(conv_id, "assistant", assistant_text)

            await self.send_json({"type": "chat.done", "conversation_id": conv_id})

        except Exception as e:
            await self.send_json({"type": "chat.error", "error": str(e)})

    # =========================
    # DB (async-safe)
    # =========================
    @database_sync_to_async
    def _save_message(self, conversation_id: int, role: str, content: str) -> int:
        conv, _ = Conversation.objects.get_or_create(id=conversation_id)
        Message.objects.create(conversation=conv, role=role, content=content)
        return conv.id

    @database_sync_to_async
    def _get_history(self, conversation_id: int):
        return get_history_messages(conversation_id)

    @database_sync_to_async
    def _get_app_memory_text(self):
        return format_app_memory_text()

    async def _build_ollama_messages(self, conversation_id: int, user_text: str):
        system_prompt = getattr(settings, "AI_SYSTEM_PROMPT", "You are a helpful assistant.")

        app_memory_text = await self._get_app_memory_text()
        history = await self._get_history(conversation_id)

        messages = []

        # GIỮ NGUYÊN: system prompt dùng role assistant theo ý anh
        messages.append({"role": "assistant", "content": system_prompt})

        if (app_memory_text or "").strip():
            messages.append({"role": "assistant", "content": app_memory_text})

        messages.extend(history)

        if not history or history[-1].get("role") != "user" or history[-1].get("content") != user_text:
            messages.append({"role": "user", "content": user_text})

        return messages

    # =========================
    # Ollama stream (async)
    # =========================
    async def _ollama_stream_async(self, messages):
        timeout = httpx.Timeout(connect=3.0, read=120.0, write=120.0, pool=3.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "messages": messages,
                    "stream": True
                },
            ) as r:
                r.raise_for_status()

                async for line in r.aiter_lines():
                    if not line:
                        continue

                    obj = json.loads(line)

                    chunk = ((obj.get("message") or {}).get("content") or "")
                    if chunk:
                        yield chunk

                    if obj.get("done") is True:
                        break
