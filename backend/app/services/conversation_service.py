"""대화 기록 도메인 로직 (Firestore conversations 컬렉션)."""

from __future__ import annotations

from typing import Any, Optional

from ..db import CONVERSATIONS_COLLECTION, get_db, utc_now_iso


class ConversationNotFound(Exception):
    """해당 id 의 대화가 없을 때"""


def _title_from(messages: list[dict[str, Any]]) -> str:
    for m in messages:
        if m.get("role") == "user" and m.get("content"):
            text = m["content"].strip().replace("\n", " ")
            return text[:40] + ("…" if len(text) > 40 else "")
    return "새 대화"


def _preview(messages: list[dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("content"):
            text = m["content"].strip().replace("\n", " ")
            return text[:60] + ("…" if len(text) > 60 else "")
    return ""


def _to_summary(doc_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    messages = raw.get("messages", []) or []
    return {
        "id": doc_id,
        "title": raw.get("title") or _title_from(messages),
        "message_count": len(messages),
        "created_at": raw.get("created_at"),
        "updated_at": raw.get("updated_at"),
        "preview": _preview(messages),
    }


def _to_detail(doc_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    detail = _to_summary(doc_id, raw)
    detail["messages"] = raw.get("messages", []) or []
    return detail


def list_conversations(limit: int = 50) -> list[dict[str, Any]]:
    """목록에는 messages 를 포함하지 않는다. 전체 메시지는 단건 조회로 가져간다."""
    db = get_db()
    items = [
        _to_summary(d.id, d.to_dict())
        for d in db.collection(CONVERSATIONS_COLLECTION).stream()
    ]
    items.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    return items[:limit]


def get_conversation(doc_id: str) -> dict[str, Any]:
    db = get_db()
    snap = db.collection(CONVERSATIONS_COLLECTION).document(doc_id).get()
    if not snap.exists:
        raise ConversationNotFound(doc_id)
    return _to_detail(snap.id, snap.to_dict())


def create_conversation(
    messages: list[dict[str, Any]], title: Optional[str] = None
) -> dict[str, Any]:
    db = get_db()
    now = utc_now_iso()
    body = {
        "title": title or _title_from(messages),
        "messages": messages,
        "created_at": now,
        "updated_at": now,
    }
    _, doc = db.collection(CONVERSATIONS_COLLECTION).add(body)
    return _to_detail(doc.id, body)


def append_messages(doc_id: str, new_messages: list[dict[str, Any]]) -> dict[str, Any]:
    """기존 대화에 메시지를 이어붙인다 (POST /api/chat 의 자동 저장 경로)."""
    db = get_db()
    ref = db.collection(CONVERSATIONS_COLLECTION).document(doc_id)
    snap = ref.get()
    if not snap.exists:
        raise ConversationNotFound(doc_id)

    raw = snap.to_dict()
    messages = (raw.get("messages") or []) + new_messages
    patch = {"messages": messages, "updated_at": utc_now_iso()}
    ref.update(patch)

    raw.update(patch)
    return _to_detail(doc_id, raw)


def delete_conversation(doc_id: str) -> None:
    db = get_db()
    ref = db.collection(CONVERSATIONS_COLLECTION).document(doc_id)
    if not ref.get().exists:
        raise ConversationNotFound(doc_id)
    ref.delete()
