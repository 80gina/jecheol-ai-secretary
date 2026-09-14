"""
[보너스 ②] 확장 통계.

요약(/api/data/summary)은 'AI 에게 먹일 짧은 문장'이 목적이라 지표를 늘리면 안 된다.
프롬프트가 길어지면 토큰만 먹고 답변 품질은 오히려 떨어진다.

그래서 화면에서 보여줄 자세한 지표는 이 파일에 따로 두고
/api/data/statistics 로 나눠 제공한다. 목적이 다르면 엔드포인트도 나눈다.

제공하는 지표
    이동평균 7일 / 30일   추세를 눈으로 보기 위한 것
    요일별 평균           주말 장보기 수요가 실제로 있는지
    월별 평균 + 건수      계절성
    사분위수              분포가 한쪽으로 쏠렸는지
    최장 연속 상승/하락    변동의 성격
    품목별 평균           어떤 제철 품목이 있을 때 값이 낮은지
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date
from typing import Any

from .data_service import list_data

WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


def _moving_average(values: list[float], window: int) -> list[float | None]:
    """단순 이동평균. 창이 다 차기 전에는 None 을 넣어 날짜와 길이를 맞춘다."""
    out: list[float | None] = []
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= window:
            running -= values[i - window]
        out.append(round(running / window, 1) if i >= window - 1 else None)
    return out


def _longest_run(values: list[float], rising: bool) -> int:
    """연속으로 오른(또는 내린) 최대 일수."""
    best = cur = 0
    for a, b in zip(values, values[1:]):
        if (b > a) if rising else (b < a):
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _quartiles(values: list[float]) -> dict[str, float]:
    s = sorted(values)
    n = len(s)
    if n < 4:
        return {"q1": s[0], "median": s[n // 2], "q3": s[-1]}
    q = statistics.quantiles(s, n=4, method="inclusive")
    return {"q1": round(q[0], 1), "median": round(q[1], 1), "q3": round(q[2], 1)}


def build_statistics(window_days: int | None = None,
                     item: str | None = None) -> dict[str, Any]:
    """
    item 을 주면 그 품목만, 생략하면 전 품목을 날짜별로 합산한 '장바구니'를 본다.

    품목을 섞어 그냥 평균 내면 대하(3만원)와 무(2천원)가 뒤엉켜
    아무 의미 없는 숫자가 나온다. 그래서 기본값은 '합계'다.
    """
    if item:
        items = list_data(item=item)
    else:
        # 날짜별 합계 = 12품목을 1kg 씩 담은 장바구니
        from collections import defaultdict as _dd
        bucket: dict[str, float] = _dd(float)
        memo: dict[str, str] = {}
        for r in list_data():
            bucket[r["date"]] += r["value"]
            memo[r["date"]] = "장바구니 합계"
        items = [{"date": d, "value": v, "memo": memo[d]} for d, v in sorted(bucket.items())]
    if not items:
        return {
            "count": 0,
            "item": item or "장바구니 합계",
            "period": "데이터 없음",
            "series": [],
            "weekday_average": {},
            "monthly": [],
            "distribution": {},
            "runs": {},
            "item_average": [],
        }

    if window_days and window_days > 0:
        items = items[-window_days:]

    dates = [i["date"] for i in items]
    values = [i["value"] for i in items]

    ma7 = _moving_average(values, 7)
    ma30 = _moving_average(values, 30)

    # 요일별 평균 — 주말에 정말 오르는지 확인하는 지표
    by_weekday: dict[int, list[float]] = defaultdict(list)
    for d, v in zip(dates, values):
        try:
            by_weekday[date.fromisoformat(d).weekday()].append(v)
        except ValueError:
            continue
    weekday_avg = {
        WEEKDAY_KO[w]: round(sum(v) / len(v), 1)
        for w, v in sorted(by_weekday.items())
    }

    # 월별
    by_month: dict[str, list[float]] = defaultdict(list)
    for d, v in zip(dates, values):
        by_month[d[:7]].append(v)
    monthly = [
        {"month": m, "average": round(sum(v) / len(v), 1),
         "min": min(v), "max": max(v), "count": len(v)}
        for m, v in sorted(by_month.items())
    ]

    # 품목별
    by_item: dict[str, list[float]] = defaultdict(list)
    for it in items:
        if it["memo"]:
            by_item[it["memo"]].append(it["value"])
    item_avg = sorted(
        ({"item": k, "average": round(sum(v) / len(v), 1), "count": len(v)}
         for k, v in by_item.items() if len(v) >= 3),
        key=lambda x: x["average"],
    )

    return {
        "count": len(items),
        "item": item or "장바구니 합계",
        "period": f"{dates[0]} ~ {dates[-1]}",
        "unit": "원/kg",
        "series": [
            {"date": d, "value": v, "ma7": a, "ma30": b}
            for d, v, a, b in zip(dates, values, ma7, ma30)
        ],
        "weekday_average": weekday_avg,
        "monthly": monthly,
        "distribution": {
            **_quartiles(values),
            "mean": round(sum(values) / len(values), 1),
            "std_dev": round(statistics.pstdev(values), 1) if len(values) > 1 else 0.0,
        },
        "runs": {
            "longest_rise_days": _longest_run(values, rising=True),
            "longest_fall_days": _longest_run(values, rising=False),
        },
        "item_average": item_avg,
    }


def to_csv(items: list[dict[str, Any]]) -> str:
    """
    내보내기용 CSV.

    앞에 BOM(\\ufeff)을 붙인다. 이게 없으면 엑셀이 한글을 CP949 로 읽어
    memo 칸이 전부 깨진다. (PowerShell 스크립트에서 겪은 것과 같은 문제)
    """
    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["date", "value", "memo"])
    for it in items:
        w.writerow([it["date"], it["value"], it["memo"]])
    return "﻿" + buf.getvalue()
