import urllib.parse
import requests

WIKI_LANG = "en"  # anh chat English
WIKI_TIMEOUT = (3, 8)

def should_use_wikipedia(text: str) -> bool:
    """
    Rule đơn giản để tránh gọi wiki cho câu quá ngắn / câu debug code.
    """
    t = (text or "").strip().lower()
    if len(t) < 8:
        return False

    skip_keywords = [
        "error", "bug", "traceback", "stack trace", "exception",
        "django", "python", "flask", "fastapi",
        "sql", "mysql", "api", "http", "post", "get", "cors",
        "git", "github", "commit", "push",
    ]
    if any(k in t for k in skip_keywords):
        return False

    return True

def fetch_wikipedia_summary(query: str, lang: str = WIKI_LANG) -> dict | None:
    """
    Trả về dict: {title, extract, url} hoặc None nếu không có.
    """
    q = (query or "").strip()
    if not q:
        return None

    # (1) Tìm title gần đúng bằng OpenSearch
    search_url = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action": "opensearch",
        "search": q,
        "limit": 1,
        "namespace": 0,
        "format": "json",
    }

    try:
        s = requests.get(search_url, params=params, timeout=WIKI_TIMEOUT, headers={"User-Agent": "ViChat/1.0"})
        s.raise_for_status()
        data = s.json()
        titles = data[1] if len(data) > 1 else []
        if not titles:
            return None
        title = titles[0]
    except Exception:
        return None

    # (2) Lấy summary theo title (REST API)
    title_enc = urllib.parse.quote(title, safe="")
    summary_url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title_enc}"

    try:
        r = requests.get(summary_url, timeout=WIKI_TIMEOUT, headers={"User-Agent": "ViChat/1.0"})
        r.raise_for_status()
        js = r.json()

        extract = (js.get("extract") or "").strip()
        page_url = None
        if isinstance(js.get("content_urls"), dict):
            page_url = js["content_urls"].get("desktop", {}).get("page")

        if not extract:
            return None

        return {
            "title": js.get("title") or title,
            "extract": extract,
            "url": page_url,
        }
    except Exception:
        return None
