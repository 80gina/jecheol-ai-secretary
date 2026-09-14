"""
대화 기록 API 라우터.

요구사항 6번의 '대화 불러오기' UX 는 (A) 방식으로 구현한다:
    GET /api/conversations        -> messages 를 포함하지 않는 목록 (가볍게)
    GET /api/conversations/{id}   -> 해당 대화의 전체 messages
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from ..models.schemas import (
    ConversationCreate,
    ConversationDetailOut,
    ConversationListOut,
    MessageOut,
)
from ..services import conversation_service

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", response_model=ConversationListOut, summary="대화 목록 조회 (messages 미포함)")
def get_conversations(limit: int = Query(50, ge=1, le=200)) -> dict:
    items = conversation_service.list_conversations(limit=limit)
    return {"count": len(items), "items": items}


@router.post(
    "",
    response_model=ConversationDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="대화 저장",
)
def post_conversation(payload: ConversationCreate) -> dict:
    messages = [m.model_dump() for m in payload.messages]
    return conversation_service.create_conversation(messages, payload.title)


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetailOut,
    summary="특정 대화 불러오기 (전체 messages 포함)",
)
def get_conversation(conversation_id: str) -> dict:
    try:
        return conversation_service.get_conversation(conversation_id)
    except conversation_service.ConversationNotFound:
        raise HTTPException(
            status_code=404, detail=f"대화를 찾을 수 없습니다: {conversation_id}"
        )


@router.delete("/{conversation_id}", response_model=MessageOut, summary="대화 삭제")
def delete_conversation(conversation_id: str) -> dict:
    try:
        conversation_service.delete_conversation(conversation_id)
    except conversation_service.ConversationNotFound:
        raise HTTPException(
            status_code=404, detail=f"대화를 찾을 수 없습니다: {conversation_id}"
        )
    return {"ok": True, "message": f"삭제 완료: {conversation_id}"}
