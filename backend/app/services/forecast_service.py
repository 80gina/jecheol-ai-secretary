"""
향후 가격 추이선.

무엇을 근거로 그리나 — 세 가지를 곱한다
    ① 계절 곡선   같은 달력 날짜(±3일)의 **다른 해** 값 평균.
                  "해마다 이맘때 이런 모양이었다"가 뼈대가 된다.
    ② 수준 보정   최근 14일 실제값 ÷ 같은 기간 계절 곡선.
                  올해가 평년보다 10% 비쌌으면 앞으로도 그 수준에서 출발한다.
    ③ 추세 감쇠   최근 30일 기울기를 절반만, 그리고 갈수록 약해지게 반영.
                  최근 흐름을 그대로 늘리면 60일 뒤 값이 터무니없어진다.

환율·날씨·운송비는 어떻게 들어가나
    우리 DB 에는 그 데이터가 없다. 없는 것을 있는 척 하지 않는다.
    대신 **가정값 손잡이**로 둔다 — "환율이 5% 오르면?" 을 사용자가 밀어 보면,
    품목별 민감도(catalog.sensitivity)를 곱해 선을 움직인다.
    그래서 이 선은 예언이 아니라 '조건을 넣었을 때의 계산'이다.
    화면에도 그렇게 적는다.

한계를 분명히
    작황 급변·수입 중단·명절 수요처럼 과거 패턴에 없던 사건은 못 맞힌다.
    그래서 선 하나가 아니라 **평년의 흩어짐으로 만든 띠**를 함께 그린다.
    띠가 넓은 품목은 그만큼 못 믿을 품목이라는 뜻이다.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from .data_service import list_data

WINDOW = 3          # 계절 곡선을 만들 때 볼 날짜 폭(±일)
LEVEL_DAYS = 14     # 수준 보정에 쓰는 최근 기간
TREND_DAYS = 30     # 추세를 재는 기간
TREND_DAMP = 0.5    # 추세를 얼마나 믿을지 (1.0 = 그대로 연장)
MAX_HORIZON = 180


def _by_md(rows: list[dict[str, Any]]) -> dict[str, list[tuple[int, float]]]:
    idx: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for r in rows:
        d = r["date"]
        if len(d) >= 10:
            idx[d[5:10]].append((int(d[:4]), r["value"]))
    return idx


def _seasonal(target: date, idx: dict[str, list[tuple[int, float]]],
              exclude_year: int | None = None) -> tuple[float, float, int] | None:
    """그 날짜의 (계절 평균, 흩어짐(표준편차), 근거 건수)."""
    vals: list[float] = []
    for off in range(-WINDOW, WINDOW + 1):
        nd = target + timedelta(days=off)
        for year, value in idx.get(nd.strftime("%m-%d"), []):
            if exclude_year is None or year != exclude_year:
                vals.append(value)
    if not vals:
        return None
    sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
    return sum(vals) / len(vals), sd, len(vals)


def _slope(rows: list[dict[str, Any]]) -> float:
    """최근 구간의 하루당 변화량 (최소제곱 기울기)."""
    tail = rows[-TREND_DAYS:]
    n = len(tail)
    if n < 7:
        return 0.0
    xs = list(range(n))
    ys = [r["value"] for r in tail]
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else 0.0


def build_forecast(item: str | None = None, days: int = 60,
                   fx_pct: float = 0.0, weather_pct: float = 0.0,
                   fuel_pct: float = 0.0) -> dict[str, Any]:
    """
    item 을 주면 그 품목, 생략하면 전 품목 합계(장바구니)를 예측한다.

    fx_pct / weather_pct / fuel_pct 는 '가정'이다.
        fx_pct=5      환율이 5% 오른다고 치면
        weather_pct=10 작황이 10% 나빠진다고 치면
        fuel_pct=3    운송비가 3% 오른다고 치면
    각 품목의 민감도를 곱해 예측선을 밀어 올린다.
    """
    from . import catalog  # 순환 참조 방지를 위해 늦게 부른다

    days = max(7, min(MAX_HORIZON, days))
    rows = list_data(item=item) if item else None

    if item:
        series = sorted(rows or [], key=lambda r: r["date"])
        sens = catalog.info(item)["sensitivity"]
        subject = item
    else:
        # 장바구니 = 그날의 모든 품목 합계. 민감도는 품목 평균을 쓴다.
        agg: dict[str, float] = defaultdict(float)
        names: set[str] = set()
        for r in list_data():
            agg[r["date"]] += r["value"]
            if r.get("memo"):
                names.add(r["memo"])
        series = [{"date": d, "value": v} for d, v in sorted(agg.items())]
        infos = [catalog.info(n)["sensitivity"] for n in names] or [{"fx": .15, "weather": .6, "transport": .4}]
        sens = {k: sum(i[k] for i in infos) / len(infos) for k in ("fx", "weather", "transport")}
        subject = "장바구니 합계"

    if len(series) < 30:
        return {"item": subject, "ok": False,
                "reason": "예측하려면 최소 30일치가 필요합니다. 데이터를 더 모아 주세요.",
                "history": series, "forecast": []}

    idx = _by_md(series)
    last_date = date.fromisoformat(series[-1]["date"])

    # ② 수준 보정 — 최근 실제가 계절 곡선보다 몇 배였나
    ratios: list[float] = []
    for r in series[-LEVEL_DAYS:]:
        d = date.fromisoformat(r["date"])
        s = _seasonal(d, idx, exclude_year=d.year)
        if s and s[0]:
            ratios.append(r["value"] / s[0])
    level = statistics.median(ratios) if ratios else 1.0

    # ③ 추세
    slope = _slope(series) * TREND_DAMP

    # 손잡이 → 이 품목에 얼마나 먹히는가
    adjust_pct = (fx_pct * sens["fx"] + weather_pct * sens["weather"] + fuel_pct * sens["transport"])

    out: list[dict[str, Any]] = []
    fallback = statistics.mean(r["value"] for r in series[-LEVEL_DAYS:])
    for k in range(1, days + 1):
        d = last_date + timedelta(days=k)
        s = _seasonal(d, idx, exclude_year=None)
        base = s[0] * level if s else fallback
        # 추세는 갈수록 약해진다 (30일이면 절반만 남는다)
        decay = 0.5 ** (k / 30)
        value = base + slope * k * decay
        value *= (1 + adjust_pct / 100)

        # 띠 = 평년의 흩어짐 + 멀어질수록 커지는 불확실성
        sd = (s[1] if s else base * 0.1)
        widen = 1 + k / days
        out.append({
            "date": d.isoformat(),
            "value": round(max(0.0, value), 1),
            "low": round(max(0.0, value - sd * widen), 1),
            "high": round(value + sd * widen, 1),
            "peers": s[2] if s else 0,
        })

    return {
        "item": subject,
        "ok": True,
        "days": days,
        "history": series[-180:],
        "forecast": out,
        "level_ratio": round(level, 3),
        "slope_per_day": round(slope, 2),
        "adjust_pct": round(adjust_pct, 2),
        "sensitivity": {k: round(v, 2) for k, v in sens.items()},
        "assumptions": {"fx_pct": fx_pct, "weather_pct": weather_pct, "fuel_pct": fuel_pct},
        "method": (
            f"같은 달력 시기(±{WINDOW}일)의 다른 해 평균을 뼈대로, "
            f"최근 {LEVEL_DAYS}일 수준(×{level:.2f})과 최근 {TREND_DAYS}일 추세를 "
            f"절반만 반영했습니다."
            + (f" 여기에 환율 {fx_pct:+g}% · 날씨 {weather_pct:+g}% · 운송비 {fuel_pct:+g}% 가정을 "
               f"이 품목 민감도로 환산해 {adjust_pct:+.1f}% 적용했습니다."
               if adjust_pct else "")
        ),
        "caveat": "과거 패턴에서 뽑은 계산이라 작황 급변·명절 수요 같은 사건은 반영되지 않습니다.",
    }
