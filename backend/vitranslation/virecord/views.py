# vitranslation/virecord/views.py
from __future__ import annotations

import json
from django.http import JsonResponse, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt

from .history_fs import list_titles, new_session, read_detail, delete_session

def api_record_history(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    # FE expects {titles: [...]}
    return JsonResponse({"titles": list_titles()})

@csrf_exempt
def api_new_topic(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        body = {}
    title_name = body.get("title_name") or None
    title_id, title_name, _ = new_session(title_name=title_name)
    return JsonResponse({"title_id": title_id, "title_name": title_name})

def api_record_detail(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    title_id = (request.GET.get("title_id") or "").strip()
    if not title_id:
        return JsonResponse({"error": "missing title_id"}, status=400)
    return JsonResponse(read_detail(title_id))


@csrf_exempt
def api_delete_topic(request):
    if request.method not in ("POST", "DELETE"):
        return HttpResponseNotAllowed(["POST", "DELETE"])
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        body = {}
    title_id = (body.get("title_id") or "").strip()
    if not title_id:
        return JsonResponse({"error": "missing title_id"}, status=400)
    ok = delete_session(title_id)
    if ok:
        return JsonResponse({"ok": True})
    return JsonResponse({"error": "not_found_or_failed"}, status=400)
