"""
조건 손잡이 → 음식 추천 → 장바구니.

사용자가 미는 것
    조리법 · 식사 목적 · 계절감 · 신선도 · 난이도 · 편의성
그러면 서버가 하는 것
    ① 조건에 맞는 음식을 점수 매겨 고른다
    ② 그 음식의 재료를 모아 지금 값으로 판정한다
    ③ 비싼 재료에는 대체재를 붙인다

왜 서버가 고르나 (GPT 가 아니라)
    같은 조건이면 같은 답이 나와야 사용자가 손잡이를 신뢰한다.
    손잡이를 조금 밀었는데 추천이 통째로 바뀌면 그건 고장으로 느껴진다.
    GPT 모드는 따로 두어, 사용자가 원할 때 말로 된 제안을 받게 한다.

점수를 매기는 방식
    조건마다 0~1 로 맞음 정도를 재고 가중합한다. 조건을 아예 안 고르면
    그 축은 만점으로 둔다 — '상관없음'을 불이익으로 만들면 안 된다.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from . import alternatives, catalog, dishes
from .summary_service import build_summary


def _month_fit(months: list[int], month: int, weight: float) -> float:
    """계절감 손잡이. weight 0 이면 '아무 때나', 1 이면 '지금 제철인 것만'."""
    if not months or weight <= 0:
        return 1.0
    dist = min(min(abs(month - m), 12 - abs(month - m)) for m in months)
    fit = max(0.0, 1 - dist / 3)
    return 1 - weight + weight * fit


def _level_fit(value: int, want: int | None, weight: float) -> float:
    """1~5 눈금 축. want 를 안 주면 만점."""
    if want is None or weight <= 0:
        return 1.0
    fit = 1 - abs(value - want) / 4
    return 1 - weight + weight * max(0.0, fit)


def recommend(
    prep: list[str] | None = None,
    purpose: list[str] | None = None,
    season_weight: float = 0.7,
    freshness_weight: float = 0.5,
    difficulty: int | None = None,
    convenience: int | None = None,
    limit: int = 5,
    month: int | None = None,
) -> dict[str, Any]:
    month = month or date.today().month
    prep = [p for p in (prep or []) if p]
    purpose = [p for p in (purpose or []) if p]

    summary = build_summary()
    by_item = {i["item"]: i for i in summary.get("items", [])}
    if not by_item:
        return {"ok": False, "reason": "가격 데이터가 없어 추천할 수 없습니다.",
                "dishes": [], "basket": [], "month": month}

    scored: list[tuple[float, dict[str, Any], dict[str, float]]] = []
    for d in dishes.all_dishes():
        have = [i for i in d["items"] if i in by_item]
        if not have:
            continue  # 값을 모르는 음식은 추천해도 판정을 못 해준다

        parts = {
            "조리법": 1.0 if not prep else (1.0 if d["prep"] in prep else 0.25),
            "목적": 1.0 if not purpose else (1.0 if set(d["purpose"]) & set(purpose) else 0.25),
            "계절감": _month_fit(d["months"], month, season_weight),
            "난이도": _level_fit(d["difficulty"], difficulty, 0.8),
            "편의성": _level_fit(d["convenience"], convenience, 0.8),
        }
        # 값이 유리한 음식에 가산점 — 재료들의 평년 대비 평균
        yoys = [by_item[i]["vs_normal_pct"] for i in have
                if by_item[i].get("vs_normal_pct") is not None]
        price_fit = 0.5 if not yoys else max(0.0, min(1.0, 0.5 - (sum(yoys) / len(yoys)) / 40))
        parts["가격"] = price_fit

        # 아는 재료 비율 — 절반만 아는 음식은 추천 순위를 낮춘다
        coverage = len(have) / len(d["items"])

        # 조리법·목적은 사용자가 **직접 고른** 것이라 취향이 아니라 조건이다.
        # 가중합에 섞으면 계절감·가격에 밀려 "국물 요리"를 골랐는데 전이 올라온다.
        # 그래서 곱셈 관문으로 둔다 — 안 맞으면 뒤로 밀리되 아주 사라지지는 않는다.
        gate = parts["조리법"] * parts["목적"]
        score = (parts["계절감"] * 1.6 + parts["난이도"] * 0.9
                 + parts["편의성"] * 0.9 + parts["가격"] * 1.4) * coverage * gate
        scored.append((score, d, parts))

    scored.sort(key=lambda x: -x[0])
    top = scored[:limit]

    picked: list[dict[str, Any]] = []
    basket_names: list[str] = []
    for score, d, parts in top:
        rows = []
        total = 0.0
        for name in d["items"]:
            it = by_item.get(name)
            if not it:
                rows.append({"item": name, "known": False})
                continue
            total += it.get("recent_avg") or 0
            rows.append({
                "item": name, "known": True,
                "recent_avg": it.get("recent_avg"),
                "vs_normal_pct": it.get("vs_normal_pct"),
                "verdict_short": it.get("verdict_short"),
                "verdict_tone": it.get("verdict_tone"),
                "alternatives": (alternatives.alternatives_for(name)[:2]
                                 if it.get("verdict_tone") in ("warn", "bad") else []),
            })
            if name not in basket_names:
                basket_names.append(name)

        best = max(parts, key=parts.get)
        picked.append({
            **d,
            "score": round(score, 2),
            "fit": {k: round(v, 2) for k, v in parts.items()},
            "why": _why(d, parts, month),
            "best_axis": best,
            "ingredients": rows,
            "cost": round(total),
        })

    return {
        "ok": True,
        "month": month,
        "dishes": picked,
        "basket": basket_names,
        "conditions": {
            "prep": prep, "purpose": purpose,
            "season_weight": season_weight, "freshness_weight": freshness_weight,
            "difficulty": difficulty, "convenience": convenience,
        },
        "vocabulary": catalog.vocabulary(),
    }


def _why(d: dict[str, Any], parts: dict[str, float], month: int) -> str:
    """왜 이 음식이 올라왔는지 한 줄. 근거 없는 추천은 쓸모가 없다."""
    bits: list[str] = []
    if parts["계절감"] >= 0.9 and d["months"]:
        bits.append(f"{month}월에 어울립니다")
    if parts["가격"] >= 0.65:
        bits.append("재료값이 평년보다 유리합니다")
    elif parts["가격"] <= 0.35:
        bits.append("재료값은 다소 비싼 편입니다")
    if d["convenience"] >= 4:
        bits.append("준비가 간단합니다")
    if d["difficulty"] >= 4:
        bits.append("손이 많이 가는 편입니다")
    return " · ".join(bits) or "조건에 무난히 맞습니다"


def condition_prompt(conditions: dict[str, Any]) -> str:
    """
    GPT 모드용. 손잡이 값을 사람 말로 바꿔 프롬프트에 얹는다.
    판정과 가격은 여전히 서버 것을 쓰고, GPT 는 이 조건에 맞춰 말만 고른다.
    """
    bits = []
    if conditions.get("prep"):
        bits.append("조리법은 " + ", ".join(conditions["prep"]))
    if conditions.get("purpose"):
        bits.append("용도는 " + ", ".join(conditions["purpose"]))
    if conditions.get("difficulty"):
        bits.append(f"손질 난이도는 5단계 중 {conditions['difficulty']} 정도")
    if conditions.get("convenience"):
        bits.append(f"준비 간편함은 5단계 중 {conditions['convenience']} 정도")
    if conditions.get("season_weight", 0) >= 0.7:
        bits.append("제철인 것 위주로")
    if not bits:
        return ""
    return "사용자가 고른 조건: " + " / ".join(bits) + ". 이 조건에 맞는 음식을 우선 제안하세요."
