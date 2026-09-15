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
    return client.chat.completions.create(**kwargs)


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
        messages.append(
            {
                "role": "assistant",
                "content": assistant_msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in assistant_msg.tool_calls
                ],
            }
        )

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

    reply = (choice.message.content or "").strip() or "답변을 생성하지 못했습니다. 다시 시도해 주세요."

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
