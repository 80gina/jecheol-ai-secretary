"""
제철밥상 플래너 - 품목별 시계열 데이터 생성 (v3)

레코드 형태는 과제 요건대로 (date, value, memo) 세 개다.
    date  = 날짜
    value = 그 품목의 그날 kg당 소매가 (원)
    memo  = 품목명

v2 까지는 '하루 한 줄'이었다. 그러면 장바구니 평균 하나만 나와서
"그래서 뭘 사야 하나"에 답할 수 없다. 실제로 장을 볼 때 필요한 것은
품목별 판정이므로, 하루에 품목 수만큼 줄을 만든다.

품목 선정
    앞의 9개는 jecheol-planner 의 장바구니와 같다. 두 프로젝트가 같은 품목을
    보게 해서, KAMIS 실측으로 갈아끼울 때 그대로 맞물리게 했다.
    뒤의 3개(전어·대하·무화과)는 제철이 한두 달로 짧아 계절성이 극적인 품목이다.

계절 계수를 품목마다 다르게 준 이유
    '제철=저렴'이 정말인지 보려면 서로 반대로 움직이는 품목이 있어야 한다.
    시금치(겨울 제철)와 오이(여름 제철)를 짝으로 넣었고,
    콩나물은 실내 재배라 날씨 영향이 적어 대조군으로 넣었다.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

# catalog.py 는 backend/app/services 에 있다. 스크립트는 backend 에서 돌린다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import catalog  # noqa: E402

# 월별 계수 1~12월. 1.0 = 그 품목의 평년 수준.
ITEMS: dict[str, dict] = {
    # ── jecheol-planner 와 동일한 9품목 ───────────────────────────
    "배추": {
        "base": 1800, "category": "채소", "noise": 0.045, "shock": 0.030,
        # 여름 고온 피해로 급등, 가을 출하로 급락, 11월 김장 수요로 반등
        "months": [1.05, 1.08, 1.10, 1.02, 0.92, 0.88, 1.15, 1.28, 0.95, 0.82, 1.02, 1.00],
        "note": "요리교실 5개 지역 전부에 들어가는 기준 품목. 김장철 계절성이 가장 뚜렷하다.",
    },
    "무": {
        "base": 1500, "category": "채소", "noise": 0.040, "shock": 0.025,
        "months": [1.04, 1.06, 1.08, 1.00, 0.94, 0.90, 1.08, 1.16, 0.96, 0.85, 1.05, 1.02],
        "note": "배추와 함께 김장 수요를 받는다. 같은 시기에 오르는지 확인용.",
    },
    "애호박": {
        "base": 3500, "category": "채소", "noise": 0.060, "shock": 0.045,
        # 겨울 시설재배 난방비로 비싸고, 여름 노지 출하로 저렴
        "months": [1.35, 1.32, 1.15, 0.98, 0.85, 0.78, 0.82, 0.88, 0.92, 1.00, 1.18, 1.30],
        "note": "값이 작아 무시하기 쉽지만 12인 수업에서는 누적된다. 작황에 민감해 노이즈가 크다.",
    },
    "감자": {
        "base": 3200, "category": "식량작물", "noise": 0.035, "shock": 0.020,
        # 저장작물 — 수확기(6~7) 최저, 재고 소진되는 봄(4~5) 최고
        "months": [1.12, 1.18, 1.22, 1.20, 1.10, 0.85, 0.80, 0.86, 0.90, 0.94, 1.00, 1.06],
        "note": "저장이 가능한 작물. 수확기와 가격 저점이 어긋나는지 보려고 골랐다.",
    },
    "고구마": {
        "base": 4000, "category": "식량작물", "noise": 0.035, "shock": 0.020,
        "months": [1.10, 1.15, 1.20, 1.22, 1.15, 1.05, 0.98, 0.92, 0.82, 0.80, 0.88, 1.00],
        "note": "감자와 같은 저장 작물. 두 품목의 움직임이 닮았는지 비교한다.",
    },
    "시금치": {
        "base": 6000, "category": "채소", "noise": 0.070, "shock": 0.050,
        # 겨울이 제철 — 12~2월 최저, 여름 최고
        "months": [0.78, 0.80, 0.92, 1.05, 1.20, 1.42, 1.55, 1.48, 1.15, 0.95, 0.84, 0.76],
        "note": "겨울이 제철로 알려진 채소. '제철=저렴'이 맞는지 검증할 대표 사례.",
    },
    "콩나물": {
        "base": 2800, "category": "채소", "noise": 0.025, "shock": 0.010,
        # 실내 재배 — 거의 평탄 (대조군)
        "months": [1.02, 1.02, 1.01, 1.00, 0.99, 0.98, 1.00, 1.01, 1.00, 0.99, 0.99, 1.01],
        "note": "실내 재배라 날씨 영향이 적다. 계절성이 강한 품목들과 대조하기 위한 대조군.",
    },
    "대파": {
        "base": 3600, "category": "채소", "noise": 0.055, "shock": 0.040,
        "months": [1.28, 1.30, 1.18, 1.00, 0.88, 0.82, 0.86, 0.94, 0.96, 0.92, 1.05, 1.20],
        "note": "거의 모든 메뉴에 들어가는 공통 재료. 값이 크게 튀면 전 회차 원가에 영향을 준다.",
    },
    "오이": {
        "base": 3000, "category": "채소", "noise": 0.060, "shock": 0.040,
        # 여름이 제철 — 시금치와 정반대
        "months": [1.42, 1.38, 1.20, 1.00, 0.86, 0.76, 0.72, 0.78, 0.90, 1.05, 1.25, 1.40],
        "note": "여름이 제철인 채소. 시금치와 정반대 계절성이 나오는지 확인해 짝으로 본다.",
    },

    # ── 제철이 짧아 계절성이 극적인 3품목 ────────────────────────
    "전어": {
        "base": 12000, "category": "수산", "noise": 0.080, "shock": 0.055,
        # 가을(9~10월)이 제철. 나머지 달은 물량이 적어 비싸다.
        "months": [1.45, 1.50, 1.40, 1.30, 1.25, 1.28, 1.20, 1.00, 0.70, 0.72, 0.95, 1.30],
        "note": "제철이 한두 달로 짧다. '가을 전어' 라는 말이 값으로도 나타나는지 본다.",
    },
    "대하": {
        "base": 28000, "category": "수산", "noise": 0.075, "shock": 0.050,
        "months": [1.30, 1.35, 1.32, 1.25, 1.18, 1.15, 1.10, 0.95, 0.72, 0.75, 1.00, 1.25],
        "note": "서해 대하 축제가 열리는 가을에 값이 내려간다.",
    },
    "무화과": {
        "base": 15000, "category": "과일", "noise": 0.090, "shock": 0.060,
        # 8~9월에만 제대로 나온다. 겨울에는 사실상 구하기 어려워 값이 매우 높다.
        "months": [1.80, 1.85, 1.80, 1.70, 1.55, 1.30, 1.00, 0.68, 0.70, 0.95, 1.45, 1.75],
        "note": "제철이 가장 짧은 품목. 무르기 쉬워 구매 당일 조리하는 메뉴에만 넣어야 한다.",
    },
}

# ══════════════════════════════════════════════════════════════════════
# 나머지 품목 — 월별 곡선을 손으로 적지 않고 카탈로그에서 끌어낸다
#
# 위의 12품목은 '제철=저렴이 맞는가'를 검증하려고 곡선을 하나씩 손으로 맞췄다.
# 그 검증이 끝난 지금, 나머지 30여 품목까지 같은 방식으로 적는 것은
#   ① 손이 많이 가고
#   ② catalog.py 의 제철 달과 어긋날 위험이 있다 (같은 사실이 두 곳에 적히면
#      한쪽만 고쳐지기 마련이다)
# 그래서 제철 달은 catalog.py 한 곳에서만 읽고, 여기서는 품목마다
# '기준가'와 '계절을 얼마나 타는지'만 정한다.
#
#   이름: (kg당 기준가, 일간 노이즈)
#   진폭(계절을 타는 정도)은 중분류에서 가져온다 — 버섯은 거의 평탄하고
#   산나물은 두 달만 나오므로 극단적이다.
# ══════════════════════════════════════════════════════════════════════
DERIVED: dict[str, tuple[int, float]] = {
    # 엽경채류
    "김장배추": (1700, 0.050), "알배추": (2600, 0.045), "얼갈이배추": (2200, 0.050),
    "봄동": (3000, 0.060), "열무": (2400, 0.055), "양배추": (1900, 0.040),
    "근대": (3400, 0.055), "쑥갓": (5200, 0.065), "상추": (6500, 0.075),
    "깻잎": (9000, 0.070), "숙주": (2600, 0.030), "미나리": (5000, 0.065),
    "부추": (4600, 0.060), "브로콜리": (4200, 0.050), "시래기": (4800, 0.040),
    "고구마순": (5500, 0.060), "우거지": (3200, 0.040), "콜리플라워": (4500, 0.050),
    # 산나물
    "냉이": (9500, 0.085), "달래": (12000, 0.090), "쑥": (7000, 0.080),
    "두릅": (22000, 0.095), "다래순": (11000, 0.085), "머위": (8000, 0.080),
    "취나물": (12000, 0.085), "고사리": (25000, 0.060), "엄나무순": (20000, 0.090),
    # 근채류
    "총각무": (2200, 0.045), "토란": (6500, 0.055), "연근": (5200, 0.045),
    "우엉": (4800, 0.045), "죽순": (11000, 0.070), "콜라비": (3000, 0.040),
    "토란대": (7000, 0.055),
    # 조미채소
    "쪽파": (5500, 0.060), "양파": (2100, 0.045), "마늘": (9500, 0.040),
    "마늘종": (6000, 0.055), "생강": (7500, 0.050), "꽈리고추": (7000, 0.060),
    "파프리카": (6500, 0.055),
    # 과채류
    "주키니호박": (2600, 0.050), "단호박": (3400, 0.045), "가지": (3800, 0.060),
    "토마토": (4200, 0.055), "옥수수": (3600, 0.050), "아스파라거스": (16000, 0.065),
    "풋고추": (7500, 0.065),
    # 버섯
    "표고버섯": (11000, 0.030), "느타리버섯": (5500, 0.028), "새송이버섯": (5000, 0.025),
    # 두류
    "완두콩": (8500, 0.055), "강낭콩": (9000, 0.055),
    # 수산
    "고등어": (9500, 0.060), "삼치": (12000, 0.065), "꽁치": (7000, 0.055),
    "동태": (7500, 0.050), "명태": (8000, 0.050), "코다리": (11000, 0.045),
    "흰다리새우": (19000, 0.055), "굴": (14000, 0.080), "꼬막": (13000, 0.080),
    "바지락": (7000, 0.070), "홍합": (4500, 0.065), "주꾸미": (22000, 0.080),
    "오징어": (14000, 0.075), "낙지": (32000, 0.080),
    "미역": (6000, 0.035), "다시마": (5000, 0.035), "파래": (8000, 0.055),
    # 과일·견과
    "복숭아": (7500, 0.075), "포도": (9000, 0.070), "사과": (5500, 0.055),
    "배": (5000, 0.055), "귤": (4500, 0.060), "한라봉": (9500, 0.060),
    "유자": (8000, 0.065), "매실": (7000, 0.070), "살구": (8500, 0.075),
    "레몬": (7000, 0.045), "밤": (9000, 0.060), "은행": (14000, 0.065),
}

# 중분류별 '계절을 타는 폭'. 제철 달에 (1-폭), 정반대 달에 (1+폭) 이 된다.
SEASON_AMPLITUDE: dict[str, float] = {
    "산나물": 0.55, "과일류": 0.42, "견과류": 0.45, "생선류": 0.38, "패류": 0.35,
    "연체류": 0.30, "과채류": 0.30, "두류·잡곡": 0.28, "엽경채류": 0.25,
    "조미채소": 0.24, "근채류": 0.20, "해조류": 0.15, "버섯류": 0.07, "기타": 0.20,
}


def _month_distance(m: int, season: list[int]) -> float:
    """그 달이 제철에서 몇 달 떨어져 있나 (0~6). 12월과 1월은 1달로 본다."""
    if not season:
        return 3.0
    return float(min(min(abs(m - s), 12 - abs(m - s)) for s in season))


def derive_months(name: str, amplitude: float | None = None) -> list[float]:
    """
    catalog.py 의 제철 달로 12개월 계수를 만든다.

    제철에 가장 싸고, 반대편 계절에 가장 비싸다 — 유통에서 흔한 모양이다.
    손으로 적은 12품목처럼 '수확기와 저점이 어긋나는' 미묘한 사례는 못 만들지만,
    없는 근거로 미묘한 곡선을 지어내는 것보다는 단순하고 설명 가능한 편이 낫다.
    """
    info = catalog.info(name)
    amp = amplitude if amplitude is not None else SEASON_AMPLITUDE.get(info["mid"], 0.20)
    season = info["season_months"]
    return [round(1.0 + amp * (_month_distance(m, season) / 3.0 - 1.0), 3)
            for m in range(1, 13)]


def _expand_items(names: list[str] | None = None) -> None:
    """손으로 적은 12품목 뒤에 DERIVED 품목을 붙인다. 이미 있으면 건드리지 않는다."""
    for name, (base, noise) in DERIVED.items():
        if name in ITEMS or (names is not None and name not in names):
            continue
        info = catalog.info(name)
        ITEMS[name] = {
            "base": base,
            "category": info["major"],
            "noise": noise,
            "shock": round(noise * 0.7, 3),
            "months": derive_months(name),
            "note": f"{info['major']}·{info['mid']} — 제철 {info['season_months'] or '연중'}, "
                    f"곡선은 카탈로그의 제철 달에서 산출",
        }


# ══════════════════════════════════════════════════════════════════════
# 규모 선택 — Firestore 무료 요금제(Spark)는 하루 쓰기 2만 건이 한도다.
#
#   품목 수 × 일수 = 레코드 수 = 업로드 시 쓰기 횟수
#   94품목 × 730일 = 68,620건  →  하루에 못 올린다 (나흘 걸린다)
#
# 일수를 줄이면 될 것 같지만 그럴 수 없다. 이 서비스의 '평년 대비'는
# **다른 해의 같은 시기**와 비교하는 것이라 최소 2년치가 있어야 성립한다.
# 그래서 줄여야 하는 쪽은 일수가 아니라 품목 수다.
#
#   lite     27품목 × 730일 = 19,710건  → 무료 한도 안에서 하루에 끝난다 (기본값)
#   standard 49품목 × 730일 = 35,770건  → 이틀에 나눠 올리거나 Blaze 요금제
#   full     94품목 × 730일 = 68,620건  → 카탈로그 전부. Blaze 요금제 권장
# ══════════════════════════════════════════════════════════════════════
LITE_EXTRA = [
    # 손으로 맞춘 12품목에 더해, 분류 화면의 갈래가 비어 보이지 않을 만큼만 고른다.
    "양파", "마늘", "상추", "부추", "브로콜리",      # 채소 — 엽경채·조미채소
    "연근", "가지", "단호박",                        # 채소 — 근채·과채
    "표고버섯",                                       # 버섯 (변동성 대조군)
    "고등어", "굴", "바지락", "오징어", "미역",      # 수산 — 생선·패류·연체·해조
    "사과",                                           # 과일 (무화과와 대조)
]

ANNUAL_INFLATION = 0.06

# 품목·연도별 작황 계수의 폭.
#
# 왜 필요한가
#   물가 상승만 넣으면 올해 값이 평년(과거 평균)보다 항상 높게 나온다.
#   그러면 모든 품목이 "비쌉니다" 로만 판정되어 서비스가 무의미해진다.
#   실제 농산물은 그 해 작황에 따라 품목마다 따로 오르내린다 —
#   같은 해에도 배추는 풍년이라 싸고 대하는 흉년이라 비쌀 수 있다.
#   그 변동을 품목×연도 단위로 하나씩 준다.
#   폭은 품목마다 다르다. 날씨에 민감한 품목일수록 해마다 크게 흔들리고,
#   실내에서 기르는 콩나물은 작황이라는 개념 자체가 거의 없다.
#   그래서 그 품목의 일간 노이즈(= 날씨 민감도)에 비례시킨다.
HARVEST_SWING_MAX = 0.25


def harvest_factor(rng: random.Random, years: list[int], noise: float) -> dict[int, float]:
    """연도별 작황 계수. 날씨에 민감한 품목일수록 폭이 크다."""
    swing = min(HARVEST_SWING_MAX, noise * 3)
    return {y: 1.0 + rng.uniform(-swing, swing) for y in years}


def seasonal_factor(months: list[float], d: date) -> float:
    """
    월별 계수를 부드럽게 이어 붙인다.

    계수를 그 달에 통째로 곱하면 매달 1일에 값이 절벽처럼 튄다.
    (v2 에서 8/31 → 9/1 사이에 -21% 가 나온 적이 있다)
    각 달의 계수를 '그 달 15일의 값'으로 보고 사이를 선형 보간한다.
    """
    mid = 15
    if d.day >= mid:
        m0 = d.month
        m1 = d.month % 12 + 1
        nxt = date(d.year + (d.month == 12), m1, 1)
        span = (nxt - date(d.year, d.month, 1)).days
        pos = d.day - mid
    else:
        m1 = d.month
        m0 = (d.month - 2) % 12 + 1
        prev_year = d.year - (d.month == 1)
        span = (date(d.year, d.month, 1) - date(prev_year, m0, 1)).days
        pos = d.day - mid + span

    t = min(max(pos / span, 0.0), 1.0)
    return months[m0 - 1] * (1 - t) + months[m1 - 1] * t


def build_records(days: int, end: date, seed: int = 20260908) -> list[dict]:
    records: list[dict] = []
    start = end - timedelta(days=days - 1)

    years = sorted({(start + timedelta(days=i)).year for i in range(days)})

    for name, spec in ITEMS.items():
        # 품목마다 다른 난수열 — 품목끼리 노이즈가 똑같이 움직이면 부자연스럽다
        rng = random.Random(seed + sum(ord(c) for c in name))
        harvest = harvest_factor(rng, years, spec["noise"])

        for i in range(days):
            d = start + timedelta(days=i)

            seasonal = seasonal_factor(spec["months"], d) * harvest[d.year]
            trend = 1.0 + (i / 365) * ANNUAL_INFLATION
            weekly = 1.0 + 0.012 * math.sin(2 * math.pi * i / 7)
            if d.weekday() >= 5:
                weekly += 0.010

            noise = rng.gauss(0, spec["noise"])
            shock = rng.uniform(0.10, 0.30) if rng.random() < spec["shock"] else 0.0

            value = spec["base"] * seasonal * trend * weekly * (1 + noise + shock)
            step = 10 if spec["base"] < 10000 else 100
            value = int(round(value / step) * step)

            records.append({"date": d.isoformat(), "value": value, "memo": name})

    records.sort(key=lambda r: (r["date"], r["memo"]))
    return records


def report(records: list[dict], days: int) -> None:
    by_item: dict[str, list[float]] = defaultdict(list)
    by_item_month: dict[tuple[str, int], list[float]] = defaultdict(list)
    for r in records:
        by_item[r["memo"]].append(r["value"])
        by_item_month[(r["memo"], int(r["date"][5:7]))].append(r["value"])

    print(f"\n생성 완료: {len(records):,}건 = {len(ITEMS)}품목 × {days}일")
    print(f"  기간: {records[0]['date']} ~ {records[-1]['date']}\n")

    print(f"  {'품목':<8}{'평균':>10}{'최저':>10}{'최고':>10}   가장 싼 달 / 비싼 달")
    print("  " + "─" * 62)
    for name in ITEMS:
        vals = by_item[name]
        monthly = {m: sum(v) / len(v) for (n, m), v in by_item_month.items() if n == name}
        cheap = min(monthly, key=monthly.get)
        dear = max(monthly, key=monthly.get)
        print(f"  {name:<8}{sum(vals)/len(vals):>9,.0f}원{min(vals):>9,.0f}원{max(vals):>9,.0f}원"
              f"   {cheap:>2}월 / {dear:>2}월")

    # 계절성이 정말 반대로 나왔는지 확인 — 설계 의도가 데이터에 반영됐는지 검증
    def cheapest_month(name: str) -> int:
        monthly = {m: sum(v) / len(v) for (n, m), v in by_item_month.items() if n == name}
        return min(monthly, key=monthly.get)

    print("\n  설계 의도 확인")
    checks = [
        ("시금치(겨울 제철)", cheapest_month("시금치") in (12, 1, 2)),
        ("오이(여름 제철)", cheapest_month("오이") in (6, 7, 8)),
        ("전어(가을 제철)", cheapest_month("전어") in (9, 10)),
        ("무화과(늦여름 제철)", cheapest_month("무화과") in (8, 9)),
    ]
    for label, ok in checks:
        print(f"    {'✅' if ok else '❌'} {label} 이 그 계절에 가장 싸다")

    sp = statistics.pstdev(by_item["콩나물"]) / statistics.mean(by_item["콩나물"])
    sv = statistics.pstdev(by_item["무화과"]) / statistics.mean(by_item["무화과"])
    print(f"    {'✅' if sp < sv / 2 else '❌'} 콩나물(대조군) 변동성 {sp:.1%} < 무화과 {sv:.1%}")


def main() -> None:
    parser = argparse.ArgumentParser(description="품목별 제철 식재료 가격 시계열 생성")
    parser.add_argument("--days", type=int, default=730, help="일수 (기본 730 = 2년)")
    parser.add_argument("--end", type=str, default=None, help="마지막 날짜 YYYY-MM-DD")
    parser.add_argument("--out", type=str, default="data/seed_data.json")
    parser.add_argument("--profile", choices=["core", "lite", "standard", "full"],
                        default="lite",
                        help="규모. core=12 / lite=27(무료 한도 안) / standard=49 / full=94")
    args = parser.parse_args()

    if args.profile == "lite":
        _expand_items(LITE_EXTRA)
    elif args.profile == "standard":
        from app.services.alternatives import ALT_TABLE
        _expand_items(sorted(ALT_TABLE))
    elif args.profile == "full":
        _expand_items()
    # core 는 손으로 곡선을 맞춘 12품목 그대로 — 계절성 검증용

    end = date.fromisoformat(args.end) if args.end else date.today()
    records = build_records(args.days, end)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")

    report(records, args.days)
    print(f"\n  저장: {out}  ({out.stat().st_size / 1024:.0f} KB)")

    # 업로드 전에 알아야 하는 것 — 다 만들고 나서 실패하면 시간만 버린다
    n = len(records)
    print(f"\n  Firestore 업로드 시 쓰기 {n:,}회가 필요합니다.")
    if n > 20_000:
        print(f"    ⚠️  무료 요금제(Spark)의 하루 한도는 2만 건입니다.")
        print(f"       --profile lite 로 줄이거나, 며칠에 나눠 올리거나, Blaze 로 바꾸세요.")
    else:
        print("    ✅ 무료 요금제 하루 한도(2만 건) 안에 들어갑니다.")


if __name__ == "__main__":
    main()
