"""
대화에서 '필요한 식재료'를 뽑아낸다.

무엇을 하나
    사용자가 "김치찌개 하려고" 라고 하면 배추·대파를,
    "전어 값 어때?" 라고 하면 전어를 골라낸다.
    화면은 그 품목을 시세판 맨 위로 올려 보여준다.

왜 GPT 에게 시키지 않고 여기서 뽑는가
    ① 결정적이다 — 같은 문장이면 항상 같은 품목이 나온다.
       GPT 에게 "품목을 뽑아줘"라고 하면 매번 조금씩 다르게 답한다.
    ② 공짜다 — 토큰을 쓰지 않고 API 왕복도 없다.
    ③ 틀려도 안전하다 — 못 뽑으면 그냥 평소 순서로 보여주면 그만이다.
    판정을 서버가 내리는 것과 같은 이유다.

한계
    말뜻을 이해하는 게 아니라 글자를 맞추는 방식이다.
    "배추 말고" 처럼 부정문도 배추로 잡는다. 그래도 화면 정렬만 바뀌므로
    잘못돼도 손해가 없고, 맞을 때의 이득이 훨씬 크다고 보고 이 방식을 택했다.
"""

from __future__ import annotations

import re
from typing import Any

# 요리 이름 -> 그 요리에 들어가는 우리 품목.
# 표는 dishes.py 한 곳에만 둔다. 여기서 따로 들고 있으면 한쪽만 고쳐져서
# "추천은 되는데 대화에서는 못 알아듣는" 어긋남이 생긴다.
from .dishes import DISH_INGREDIENTS  # noqa: E402


def _norm(text: str) -> str:
    """비교용으로 공백을 없앤다. '김치 찌개' 와 '김치찌개' 를 같게 보기 위해서."""
    return re.sub(r"\s+", "", text or "")


def extract(text: str, known_items: list[str]) -> dict[str, Any]:
    """
    문장에서 품목을 뽑는다.

    돌려주는 것
        items   : 품목 이름 목록 (등장 순서 유지, 중복 제거)
        matched : 무엇 때문에 뽑혔는지 — 화면에 이유로 보여준다
                  [{"by": "품목"|"요리", "term": "김치찌개", "items": [...]}]
    """
    flat = _norm(text)
    if not flat:
        return {"items": [], "matched": []}

    found: list[str] = []
    matched: list[dict[str, Any]] = []

    def add(names: list[str], by: str, term: str) -> None:
        new = [n for n in names if n in known_items and n not in found]
        if not new:
            return
        found.extend(new)
        matched.append({"by": by, "term": term, "items": new})

    # ① 요리 이름 먼저. 긴 이름부터 봐야 '김치찌개'가 '김치'에 먹히지 않는다.
    for dish in sorted(DISH_INGREDIENTS, key=len, reverse=True):
        if _norm(dish) in flat:
            # 이미 잡힌 요리의 부분 문자열이면 건너뛴다 (김치찌개 → 김치)
            if any(_norm(dish) in _norm(m["term"]) and m["by"] == "요리" for m in matched):
                continue
            add(DISH_INGREDIENTS[dish], "요리", dish)

    # ② 품목 이름 직접 언급
    for name in sorted(known_items, key=len, reverse=True):
        if _norm(name) in flat:
            add([name], "품목", name)

    return {"items": found, "matched": matched}


def describe(matched: list[dict[str, Any]]) -> str:
    """왜 이 품목들이 올라왔는지 한 줄로. 화면에 그대로 보여준다."""
    if not matched:
        return ""
    parts = []
    for m in matched:
        if m["by"] == "요리":
            parts.append(f"{m['term']} → {', '.join(m['items'])}")
        else:
            parts.append(m["term"])
    return " · ".join(parts)
