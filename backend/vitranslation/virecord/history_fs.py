# vitranslation/virecord/history_fs.py
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime
from django.conf import settings

def history_root() -> Path:
    p = Path(settings.BASE_DIR) / "vitranslation" / "history"
    p.mkdir(parents=True, exist_ok=True)
    return p

def ensure_session(title_id: str, title_name: str | None = None) -> Path:
    folder = history_root() / title_id
    folder.mkdir(parents=True, exist_ok=True)

    meta_path = folder / "meta.json"
    if not meta_path.exists():
        meta = {
            "title_id": title_id,
            "title_name": title_name or title_id,
            "created_at": title_id,
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    for f in ["source.txt", "target.txt"]:
        fp = folder / f
        if not fp.exists():
            fp.write_text("", encoding="utf-8")

    return folder

def new_session(title_name: str | None = None):
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    title_id = ts
    title_name = title_name or ts
    folder = ensure_session(title_id, title_name)
    meta = {"title_id": title_id, "title_name": title_name, "created_at": ts}
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    # init files
    (folder / "source.txt").write_text("", encoding="utf-8")
    (folder / "target.txt").write_text("", encoding="utf-8")
    return title_id, title_name, folder

def list_titles():
    root = history_root()
    out = []
    for p in sorted(root.iterdir(), reverse=True):
        if not p.is_dir():
            continue
        meta = {}
        meta_path = p / "meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        out.append({
            "title_id": meta.get("title_id") or p.name,
            "title_name": meta.get("title_name") or p.name,
            "created_at": meta.get("created_at") or p.name,
        })
    return out

def read_detail(title_id: str):
    folder = ensure_session(title_id)
    src = (folder / "source.txt").read_text(encoding="utf-8")
    tgt = (folder / "target.txt").read_text(encoding="utf-8")
    meta = {}
    try:
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    except Exception:
        meta = {"title_id": title_id, "title_name": title_id}

    # FE expects: original_text, translated_text
    return {
        "title_id": title_id,
        "title_name": meta.get("title_name", title_id),
        "original_text": src,
        "translated_text": tgt,
        "meta": meta,
    }

def read_source_target(title_id: str) -> tuple[str, str]:
    folder = ensure_session(title_id)
    src = (folder / "source.txt").read_text(encoding="utf-8")
    tgt = (folder / "target.txt").read_text(encoding="utf-8")
    return src, tgt

def write_source(title_id: str, text: str):
    folder = ensure_session(title_id)
    (folder / "source.txt").write_text(text or "", encoding="utf-8")

def write_target(title_id: str, text: str):
    folder = ensure_session(title_id)
    (folder / "target.txt").write_text(text or "", encoding="utf-8")

def build_title_context_tail(prev_source: str, prev_target: str, max_lines: int = 12) -> str:
    """
    Context theo title (không AI): lấy vài dòng cuối từ source/target file.
    """
    s_lines = [ln.strip() for ln in (prev_source or "").splitlines() if ln.strip()]
    t_lines = [ln.strip() for ln in (prev_target or "").splitlines() if ln.strip()]
    s_tail = s_lines[-max_lines:]
    t_tail = t_lines[-max_lines:]

    # zip theo index (không cần cùng length tuyệt đối)
    n = min(len(s_tail), len(t_tail))
    pairs = []
    for i in range(n):
        pairs.append(f"SOURCE: {s_tail[-n + i]}\nTARGET: {t_tail[-n + i]}")
    # nếu thiếu target thì chỉ source
    if len(s_tail) > n:
        for i in range(len(s_tail) - n):
            pairs.append(f"SOURCE: {s_tail[n + i]}\nTARGET: ")
    return "\n---\n".join(pairs).strip()
