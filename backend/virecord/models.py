from django.db import connections

# Create your models here.
def insert_topic(title_name: str) -> int:
    """
    Tạo topic mới trong bảng titles.
    Lưu ý: bảng titles PHẢI cho phép original_text/translated_text NULL (hoặc có default),
    vì new topic chỉ có title_name.
    """
    sql = """
        INSERT INTO titles (title_name, created_at, updated_at)
        VALUES (%s, NOW(), NOW())
    """
    with connections["virecord"].cursor() as cursor:
        cursor.execute(sql, [title_name])
        return cursor.lastrowid


def insert_title_row(title_id: int, original_text: str, translated_text: str) -> None:
    """
    Update nội dung cho topic đã có.
    """
    sql = """
        UPDATE titles
        SET original_text=%s, translated_text=%s, updated_at=NOW()
        WHERE title_id=%s
    """
    with connections["virecord"].cursor() as cursor:
        cursor.execute(sql, [original_text, translated_text, title_id])


def list_topics() -> list[dict]:
    """
    GET /api/record_history
    """
    sql = """
        SELECT title_id, title_name
        FROM titles
        ORDER BY updated_at DESC, title_id DESC
    """
    with connections["virecord"].cursor() as cursor:
        cursor.execute(sql)
        rows = cursor.fetchall()

    return [{"title_id": r[0], "title_name": r[1]} for r in rows]


def get_topic_detail(title_id: int) -> dict | None:
    """
    GET /api/record_detail?title_id=...
    """
    sql = """
        SELECT title_id, title_name, original_text, translated_text
        FROM titles
        WHERE title_id=%s
        LIMIT 1
    """
    with connections["virecord"].cursor() as cursor:
        cursor.execute(sql, [title_id])
        row = cursor.fetchone()

    if not row:
        return None

    return {
        "title_id": row[0],
        "title_name": row[1],
        "original_text": row[2] or "",
        "translated_text": row[3] or "",
    }
