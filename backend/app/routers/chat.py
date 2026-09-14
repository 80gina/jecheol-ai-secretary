"""AI 챗봇 API 라우터."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models.schemas import ChatRequest, ChatResponse
from ..services import chat_service
from ..services.tools import TOOL_SPECS

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse, summary="데이터 기반 AI 대화")
def post_chat(payload: ChatRequest) -> dict:
    """
    동작 흐름
      1. 데이터 요약 조회
      2. 요약을 시스템 프롬프트에 삽입 (컨텍스트 주입)
      3. GPT 호출 (use_tools=true 이면 GPT 가 내부 API 를 도구로 호출)
      4. 대화 내용을 conversations 컬렉션에 자동 저장
    """
    try:
        return chat_service.chat(
            message=payload.message,
            conversation_id=payload.conversation_id,
            use_tools=payload.use_tools,
            conditions=payload.conditions.model_dump() if payload.conditions else None,
        )
    except chat_service.ChatConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"AI 응답 생성 실패: {exc}")


@router.get("/tools", tags=["chat"], summary="[보너스] GPT 에 노출된 도구 스키마 조회")
def get_tools() -> dict:
    """README 와 MCP Server 가 참조하는 도구 정의를 그대로 보여준다."""
    return {"count": len(TOOL_SPECS), "tools": TOOL_SPECS}
