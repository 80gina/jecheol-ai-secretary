"""
평가 지표와 SWOT — 숫자를 '살까 말까'의 언어로 바꾸는 층.

여섯 축을 쓰는 이유
    가격 하나만 보면 "싼데 왜 안 사지?"를 설명하지 못한다.
    제철이 아니라 맛이 없을 수도, 손질이 번거로워 수업에 못 쓸 수도 있다.
    그래서 사실 축(계절성·가격·신선도)과 참고 축(기호도·편의성·쉬움)을
    한 그림에 얹되, **어느 쪽이 측정값인지 화면에 표시한다.**

        측정  계절성 · 가격 · 신선도   ← Firestore 의 실제 가격에서 계산
        참고  기호도 · 편의성 · 쉬움   ← catalog.py 의 도메인 지식(사람의 판단)

    섞어서 하나의 '종합점수'만 보여주면, 틀렸을 때 어디가 틀렸는지 알 수 없다.

SWOT 을 서버가 만드는 이유
    GPT 에게 맡기면 그럴듯한 문장이 나오지만 근거가 매번 달라진다.
    강점·위협은 전부 계산으로 나오는 것이다 — 평년보다 싸면 강점,
    다음 달 평균이 더 비싸면 위협. 그래서 여기서 만든다.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from . import catalog

# 축 정의 — (키, 화면 이름, 출처)
AXES = [
    ("season", "계절성", "measured"),
    ("price", "가격", "measured"),
    ("freshness", "신선도", "measured"),
    ("prefer", "기호도", "reference"),
    ("convenience", "편의성", "reference"),
    ("ease", "쉬움", "reference"),
]


def _clamp(v: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, v))


def _month_distance(month: int, season: list[int]) -> int:
    """이번 달이 제철에서 몇 달 떨어져 있나. 12월→1월은 1달로 본다."""
    if not season:
        return 6
    return min(min(abs(month - s), 12 - abs(month - s)) for s in season)


def season_score(item: dict[str, Any], month: int) -> float:
    """
    계절성 — 두 근거를 반반 섞는다.
      ① 카탈로그의 제철 달과 이번 달의 거리 (사람이 아는 제철)
      ② 실제 데이터에서 가장 쌌던 달과의 거리 (값이 말하는 제철)
    둘이 어긋나는 품목이 있는데, 그 자체가 볼 만한 정보라 평균을 낸다.
    """
    info = catalog.info(item["item"])
    by_catalog = 100 - _month_distance(month, info["season_months"]) * 16.7
    cheapest = item.get("cheapest_month")
    if cheapest:
        by_data = 100 - _month_distance(month, [cheapest]) * 16.7
        return _clamp((by_catalog + by_data) / 2)
    return _clamp(by_catalog)


def price_score(item: dict[str, Any]) -> float:
    """가격 매력도 — 평년 대비 -20% 면 100점, +20% 면 0점."""
    v = item.get("vs_normal_pct")
    if v is None:
        return 50.0
    return _clamp(50 - v * 2.5)


def freshness_score(item: dict[str, Any], month: int) -> float:
    """
    신선도 — 우리는 산지 상태를 볼 수 없다. 대신
    '제철에 가까울수록 물건이 좋다'는 유통의 상식을 쓰고,
    상하기 쉬운 품목(catalog.freshness 가 높은 것)일수록 그 차이를 크게 본다.
    """
    info = catalog.info(item["item"])
    dist = _month_distance(month, info["season_months"] or [item.get("cheapest_month") or month])
    penalty = dist * (info["freshness"] * 3.0)
    return _clamp(100 - penalty)


def scores_for(item: dict[str, Any], month: int | None = None) -> dict[str, Any]:
    """품목 하나의 여섯 축. 화면의 레이더가 이것을 그대로 그린다."""
    month = month or date.today().month
    info = catalog.info(item["item"])
    values = {
        "season": round(season_score(item, month)),
        "price": round(price_score(item)),
        "freshness": round(freshness_score(item, month)),
        "prefer": info["prefer"] * 20,
        "convenience": info["convenience"] * 20,
        "ease": (6 - info["difficulty"]) * 20,
    }
    measured = [values[k] for k, _, src in AXES if src == "measured"]
    return {
        "item": item["item"],
        "major": info["major"], "mid": info["mid"], "minor": info["minor"],
        "axes": [{"key": k, "label": label, "source": src, "value": values[k]}
                 for k, label, src in AXES],
        "values": values,
        "measured_avg": round(sum(measured) / len(measured)),
        "total": round(sum(values.values()) / len(values)),
    }


# ---------------------------------------------------------------- SWOT
def _next_month_gap(item: dict[str, Any], monthly: dict[str, float], month: int) -> float | None:
    """다음 달 평균이 이번 달보다 몇 % 비싼가. 위협/기회의 근거."""
    cur = monthly.get(f"{month:02d}")
    nxt = monthly.get(f"{month % 12 + 1:02d}")
    if not cur or not nxt:
        return None
    return (nxt - cur) / cur * 100


def swot(items: list[dict[str, Any]], monthly_by_item: dict[str, dict[str, float]],
         month: int | None = None) -> dict[str, list[dict[str, str]]]:
    """
    장바구니 전체의 SWOT.

    S 지금 값이 유리한 것 / W 지금 불리한 것
    O 곧 더 좋아질 것      / T 곧 나빠질 것 · 값이 잘 튀는 것
    모두 계산 결과이며, 각 항목에 '왜'를 붙여 근거 없이 남지 않게 한다.
    """
    month = month or date.today().month
    S: list[dict[str, str]] = []
    W: list[dict[str, str]] = []
    O: list[dict[str, str]] = []
    T: list[dict[str, str]] = []

    for it in items:
        name = it["item"]
        info = catalog.info(name)
        yoy = it.get("vs_normal_pct")
        monthly = monthly_by_item.get(name, {})
        gap = _next_month_gap(it, monthly, month)

        if yoy is not None and yoy <= -4:
            S.append({"item": name, "why": f"평년보다 {abs(yoy):.0f}% 쌉니다"})
        if month in info["season_months"]:
            S.append({"item": name, "why": f"{month}월이 제철입니다"})

        if yoy is not None and yoy >= 12:
            W.append({"item": name, "why": f"평년보다 {yoy:.0f}% 비쌉니다"})
        if info["difficulty"] >= 4:
            W.append({"item": name, "why": "손질에 손이 많이 갑니다"})

        if gap is not None and gap <= -8:
            O.append({"item": name, "why": f"다음 달 평균이 {abs(gap):.0f}% 더 쌉니다 — 미룰수록 유리"})
        if info["season_months"] and _month_distance(month, info["season_months"]) == 1:
            O.append({"item": name, "why": "제철이 한 달 앞입니다"})

        if gap is not None and gap >= 8:
            T.append({"item": name, "why": f"다음 달 평균이 {gap:.0f}% 더 비쌉니다 — 지금이 낫습니다"})
        rng = (it.get("max") or 0) - (it.get("min") or 0)
        avg = it.get("average") or 0
        if avg and rng / avg > 1.2:
            T.append({"item": name, "why": "값이 크게 흔들리는 품목입니다"})
        if info["sensitivity"]["fx"] >= 0.3:
            T.append({"item": name, "why": "수입 비중이 있어 환율에 흔들립니다"})

    def top(rows: list[dict[str, str]]) -> list[dict[str, str]]:
        seen, out = set(), []
        for r in rows:
            key = (r["item"], r["why"])
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
        return out[:6]

    return {"strength": top(S), "weakness": top(W), "opportunity": top(O), "threat": top(T)}
