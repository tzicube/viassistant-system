from typing import List, Dict
from .models import Message, AppMemory


def get_app_memory() -> Dict[str, str]:
    qs = AppMemory.objects.all()
    return {m.key: m.value for m in qs}


def set_app_memory(key: str, value: str) -> None:
    value = (value or "").strip()
    if not value:
        return
    AppMemory.objects.update_or_create(
        key=key,
        defaults={"value": value}
    )


def format_app_memory_text() -> str:
    mem = get_app_memory()
    if not mem:
        return ""
    lines = ["APP_MEMORY (long-term facts):"]
    for k, v in mem.items():
        lines.append(f"- {k}: {v}")
    return "\n".join(lines)


def get_history_messages(conversation_id: int) -> List[Dict[str, str]]:
    qs = Message.objects.filter(conversation_id=conversation_id).order_by("created_at", "id")
    return [{"role": m.role, "content": m.content} for m in qs
    ]
