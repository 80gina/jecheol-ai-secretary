"""
AI 챗봇 로직.

핵심 흐름 (요구사항 7번):
    1) 데이터 요약 조회        -> summary_service.build_summary()
    2) 요약을 시스템 프롬프트에 삽입 (컨텍스트 주입)
    3) GPT 호출               -> (보너스) 필요하면 GPT 가 도구를 호출하는 루프
    4) 대화 내용을 conversations 컬렉션에 자동 저장
"""

from __future__ import annotations

import json
from typing import Any

from ..config import settings
from . import conversation_service, data_service, mentions, recommend_service, tools
from .summary_service import build_summary, build_system_prompt

MAX_TOOL_ROUNDS = 3  # 무한 호출 방지
HISTORY_TURNS = 8  # 프롬프트에 실어보낼 최근 메시지 수 (토큰 절약)


class ChatConfigError(Exception):
    """OpenAI 키 등 설정 문제"""


def _is_gemini() -> bool:
    """
    Gemini 계열 모델인지 판단한다.

    주소만 보면 안 된다. 중계 서버(예: 코디세이 교육용 게이트웨이)를 거치면
    주소는 googleapis.com 이 아니지만 실제로 답하는 것은 Gemini 다.
    그래서 주소와 모델 이름을 함께 본다.
    """
    return (
        "googleapis.com" in settings.OPENAI_BASE_URL
        or settings.OPENAI_MODEL.lower().startswith("gemini")
    )


def _client():
    if not settings.OPENAI_API_KEY:
        raise ChatConfigError(
            "OPENAI_API_KEY 가 설정되지 않았습니다. .env 또는 배포 환경 변수에 추가하세요."
        )
    from openai import OpenAI

    # OPENAI_BASE_URL 이 비어 있으면 라이브러리 기본값(OpenAI)으로 간다.
    # 값이 있으면 그 주소로 붙는다 — Gemini 의 OpenAI 호환 엔드포인트가 그 예다.
    kwargs: dict[str, Any] = {"api_key": settings.OPENAI_API_KEY}
    if settings.OPENAI_BASE_URL:
        kwargs["base_url"] = settings.OPENAI_BASE_URL
    return OpenAI(**kwargs)


def _assistant_turn(assistant_msg: Any) -> dict[str, Any]:
    """
    도구를 호출한 모델의 응답을 '다음 요청에 되돌려줄 형태'로 만든다.

    왜 통째로 돌려주나.
        Gemini 3 계열은 도구 호출마다 thought_signature(생각 서명)를 함께 준다.
        다음 요청에 그 서명이 없으면 400 으로 거부한다 — 모델이 자기가 왜 그 도구를
        불렀는지 이어서 기억하기 위한 장치다.
        필요한 필드만 골라 새로 조립하면 그 서명이 조용히 사라진다.
        그래서 받은 응답을 그대로 되돌려주고, 공급자가 덧붙인 필드는 건드리지 않는다.
        이렇게 하면 앞으로 어떤 공급자가 무엇을 덧붙이든 같은 방식으로 동작한다.
    """
    try:
        turn = assistant_msg.model_dump(exclude_none=True)
        if turn.get("tool_calls"):
            turn.setdefault("role", "assistant")
            turn.setdefault("content", assistant_msg.content or "")
            return turn
    except Exception:  # noqa: BLE001 - 라이브러리 형태가 달라도 아래로 넘어간다
        pass

    # 되돌려줄 수 없는 형태라면 최소한의 정보로라도 잇는다 (기존 방식).
    return {
        "role": "assistant",
        "content": assistant_msg.content or "",
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in assistant_msg.tool_calls
        ],
    }


def _load_history(conversation_id: str | None) -> list[dict[str, str]]:
    if not conversation_id:
        return []
    try:
        conv = conversation_service.get_conversation(conversation_id)
    except conversation_service.ConversationNotFound:
        return []
    history = [
        {"role": m["role"], "content": m["content"]}
        for m in conv["messages"]
        if m.get("role") in ("user", "assistant")
    ]
    return history[-HISTORY_TURNS:]


def _call_openai(client, messages: list[dict[str, Any]], use_tools: bool):
    kwargs: dict[str, Any] = {
        "model": settings.OPENAI_MODEL,
        "messages": messages,
        "max_tokens": settings.OPENAI_MAX_TOKENS,
        "temperature": 0.4,
    }
    if use_tools:
        kwargs["tools"] = tools.openai_tool_params()
        kwargs["tool_choice"] = "auto"

    # Gemini 2.5 계열은 '생각(thinking)' 토큰을 먼저 쓰고 그 다음에 답을 쓴다.
    # 그 둘이 같은 max_tokens 예산을 나눠 쓰므로, 예산이 빠듯하면 생각만 하다가
    # 본문이 비어 있는 응답(finish_reason="length")이 돌아온다 — 화면에는
    # "답변을 생성하지 못했습니다" 로만 보여서 원인을 알기 어렵다.
    # 이 앱은 데이터 요약을 이미 서버에서 계산해 넘기므로 모델이 따로 추론할 것이
    # 많지 않다. 생각을 끄고 예산을 전부 답변에 쓰게 한다.
    if _is_gemini():
        kwargs["reasoning_effort"] = "none"

    try:
        return client.chat.completions.create(**kwargs)
    except Exception as exc:
        # reasoning_effort 는 공급자·모델·라이브러리 버전에 따라 없을 수 있다.
        # 그것 때문에 거부당한 경우에만 그 옵션을 빼고 한 번 더 시도한다.
        # 다른 이유의 오류까지 삼키면 진짜 원인을 못 보게 되므로 그대로 올려보낸다.
        if "reasoning_effort" in str(exc) and "reasoning_effort" in kwargs:
            kwargs.pop("reasoning_effort", None)
            return client.chat.completions.create(**kwargs)
        raise


def chat(message: str, conversation_id: str | None, use_tools: bool = True,
         conditions: dict[str, Any] | None = None) -> dict[str, Any]:
    # 1) 요약 조회
    summary = build_summary()

    # 2) 컨텍스트 주입
    system_prompt = build_system_prompt(summary)

    # 화면의 조건 손잡이를 말로 바꿔 얹는다. 판정과 값은 여전히 서버 것을 쓰고,
    # GPT 는 그 조건에 맞는 음식을 고르는 말투만 담당한다.
    if conditions:
        extra = recommend_service.condition_prompt(conditions)
        if extra:
            system_prompt += "\n\n" + extra

    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    messages += _load_history(conversation_id)
    messages.append({"role": "user", "content": message})

    client = _client()
    traces: list[dict[str, Any]] = []

    # 3) GPT 호출 (+ 도구 호출 루프)
    response = _call_openai(client, messages, use_tools)
    choice = response.choices[0]

    rounds = 0
    while use_tools and choice.finish_reason == "tool_calls" and rounds < MAX_TOOL_ROUNDS:
        rounds += 1
        assistant_msg = choice.message
        messages.append(_assistant_turn(assistant_msg))

        for tc in assistant_msg.tool_calls:
            args, result = tools.run_tool_json(tc.function.name, tc.function.arguments)
            payload = json.dumps(result, ensure_ascii=False)
            traces.append(
                {
                    "name": tc.function.name,
                    "arguments": args,
                    "result_preview": payload[:300],
                }
            )
            messages.append(
                {"role": "tool", "tool_call_id": tc.id, "content": payload}
            )

        response = _call_openai(client, messages, use_tools)
        choice = response.choices[0]

    reply = (choice.message.content or "").strip()
    if not reply:
        # 왜 비었는지를 구분해서 알린다. "다시 시도해 주세요" 한 줄로 뭉뚱그리면
        # 토큰 예산 문제인지 모델 문제인지 알 수 없어 고칠 수가 없다.
        if choice.finish_reason == "length":
            reply = (
                "답변이 길이 제한에 걸려 끊겼습니다. "
                f"환경 변수 OPENAI_MAX_TOKENS(현재 {settings.OPENAI_MAX_TOKENS})를 늘려 주세요."
            )
        else:
            reply = f"답변을 생성하지 못했습니다 (종료 사유: {choice.finish_reason}). 다시 시도해 주세요."

    # 이 대화에서 '필요한 식재료'를 뽑는다. 화면은 이 품목을 시세판 맨 위로 올린다.
    # 질문을 먼저 보고 답변을 나중에 봐서, 사용자가 물은 것이 앞에 오게 한다.
    known = data_service.list_item_names()
    found = mentions.extract(f"{message}\n{reply}", known)

    # 4) 대화 자동 저장
    new_messages = [
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply},
    ]
    if conversation_id:
        try:
            conv = conversation_service.append_messages(conversation_id, new_messages)
        except conversation_service.ConversationNotFound:
            conv = conversation_service.create_conversation(new_messages)
    else:
        conv = conversation_service.create_conversation(new_messages)

    return {
        "conversation_id": conv["id"],
        "reply": reply,
        "summary_used": summary,
        "tool_calls": traces,
        "mentioned_items": found["items"],
        "mention_reason": mentions.describe(found["matched"]),
    }
