"""
데이터 요약 계산 - 이 과제의 심장.

여기서 만든 요약문이 그대로 시스템 프롬프트에 주입된다.
원본 레코드는 건드리지 않고, 조회 시점에 파생 계산만 한다.
따라서 데이터가 추가/수정/삭제되면 요약도 자동으로 따라간다.

── 왜 품목별로 계산하는가 ────────────────────────────────────────
    장바구니 전체 평균 하나만으로는 "그래서 뭘 사야 하나"에 답할 수 없다.
    같은 날에도 배추는 평년보다 14% 싸고 오이는 12% 비쌀 수 있다.
    실제로 장을 볼 때 필요한 것은 품목마다의 판정이므로, 판정을 품목 단위로
    계산하고 장바구니 전체는 '요약 헤드라인'으로만 쓴다.

── 왜 축이 두 개인가 ────────────────────────────────────────────
    전주 대비(단기)만 보면 "지금 오르는 중인가"만 알 수 있고,
    평년 대비(장기)만 보면 "이 시기치고 비싼가"만 알 수 있다.

        평년보다 싼데 오르는 중  -> 지금 사는 게 낫다
        평년보다 싼데 내리는 중  -> 조금 더 기다려도 된다

── 왜 판정을 GPT 가 아니라 서버가 하는가 ─────────────────────────
    GPT 에게 날숫자만 주면 "비싼 편이네요" 같은 근거 없는 말을 지어낸다.
    판정은 결정적(deterministic)으로 서버가 내리고, GPT 는 말투만 입히게 한다.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from .data_service import list_data

NORMAL_WINDOW_DAYS = 7   # 평년을 구할 때 같은 시기로 인정하는 범위 (±일)
RECENT_DAYS = 7          # '최근'으로 보는 기간

# 판정 밴드 — 평년 대비 몇 %부터 무엇으로 부를지. 한곳에 모아 두어야
# 프론트·프롬프트·문서가 같은 기준을 쓴다.
#   (임계값, 문장형 판정, 짧은 판정, 톤)
#   짧은 판정은 표에 들어간다 — 좁은 칸에서 "미루는 편이 / 낫습니다" 로
#   두 줄이 되면 표가 읽히지 않는다.
VERDICT_BANDS = [
    (-12.0, "지금 사세요", "지금 사세요", "good"),
    (-4.0, "사도 좋습니다", "사도 좋음", "good"),
    (5.0, "평년 수준", "평년 수준", "mid"),
    (12.0, "조금 비쌉니다", "조금 비쌈", "warn"),
    (None, "미루는 편이 낫습니다", "미루세요", "bad"),
]

SUBJECT = "제철 식재료"
SUBJECT_DETAIL = "품목별 kg당 소매가"
UNIT = "원/kg"

EMPTY_SUMMARY: dict[str, Any] = {
    "period": "데이터 없음",
    "count": 0,
    "item_count": 0,
    "subject": SUBJECT,
    "subject_detail": SUBJECT_DETAIL,
    "unit": UNIT,
    "items": [],
    "buy_now": [],
    "avoid": [],
    "basket": {},
    "trend": "데이터 없음",
    "verdict": "판단 불가",
    "verdict_short": "판단 불가",
    "verdict_tone": "mid",
    "verdict_reason": "등록된 데이터가 없어 판정할 수 없습니다.",
    "normal_basis": "데이터 없음",
    "metrics": {"total": 0, "average": 0, "max": 0, "min": 0},
    "monthly_average": {},
    "peak_date": None,
    "trough_date": None,
}


# ---------------------------------------------------------------- 평년
def _normal_for(target: str, by_md: dict[str, list[tuple[int, float]]]) -> tuple[float, int] | None:
    """
    평년값 = 같은 달력 시기(±7일)의 '다른 해' 값들의 평균.

    같은 해의 값은 제외한다 — 자기 자신과 비교하면 항상 0% 가 나오기 때문이다.
    """
    try:
        d = date.fromisoformat(target)
    except ValueError:
        return None

    peers: list[float] = []
    for off in range(-NORMAL_WINDOW_DAYS, NORMAL_WINDOW_DAYS + 1):
        nd = d + timedelta(days=off)
        for year, value in by_md.get(nd.strftime("%m-%d"), []):
            if year != d.year:
                peers.append(value)

    return (sum(peers) / len(peers), len(peers)) if peers else None


def _md_index(rows: list[dict[str, Any]]) -> dict[str, list[tuple[int, float]]]:
    idx: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for r in rows:
        d = r["date"]
        if len(d) >= 10:
            idx[d[5:10]].append((int(d[:4]), r["value"]))
    return idx


# ---------------------------------------------------------------- 판정
def _verdict(yoy: float | None) -> tuple[str, str, str]:
    """(문장형 판정, 짧은 판정, 톤)"""
    if yoy is None:
        return "판단 불가", "판단 불가", "mid"
    for threshold, label, short, tone in VERDICT_BANDS:
        if threshold is None or yoy <= threshold:
            return label, short, tone
    return "평년 수준", "평년 수준", "mid"


def _reason(name: str, yoy: float | None, wow: float | None) -> str:
    if yoy is None:
        return f"{name}은(는) 비교할 작년 같은 시기 기록이 없어 평년 대비를 낼 수 없습니다."

    if yoy <= -12:
        head = (f"평년보다 {abs(yoy):.0f}% 쌉니다. "
                "이만큼 내려오는 일이 자주 있지 않으니 지금 사는 편이 이득입니다.")
    elif yoy <= -4:
        head = f"평년보다 {abs(yoy):.0f}% 낮습니다. 무리 없이 담아도 되는 값입니다."
    elif yoy < 5:
        head = "평년과 비슷합니다. 급하면 사고, 아니면 다음 장을 봐도 손해가 크지 않습니다."
    elif yoy < 12:
        head = f"평년보다 {yoy:.0f}% 높습니다. 양을 줄이거나 대체 재료를 보는 편이 낫습니다."
    else:
        head = f"평년보다 {yoy:.0f}% 높습니다. 이번에는 빼고 대체 재료로 바꾸는 것을 권합니다."

    if wow is None:
        return head

    direction = "내리는 중" if wow <= -3 else ("오르는 중" if wow >= 3 else "움직임이 적음")
    tail = f" 전주 대비로는 {wow:+.0f}%로 {direction}입니다."

    # 두 축이 엇갈릴 때가 이 설계의 존재 이유다. 그 경우만 한마디 더 붙인다.
    if yoy <= -4 and wow >= 3:
        tail += " 싼 구간이지만 반등이 시작됐으니 미루지 않는 편이 좋습니다."
    elif yoy <= -4 and wow <= -3:
        tail += " 아직 더 내려갈 여지가 있어 급하지 않다면 며칠 지켜봐도 됩니다."
    elif yoy >= 5 and wow <= -3:
        tail += " 비싸지만 내려오는 중이라 조금 기다리면 평년 수준에 닿을 수 있습니다."

    return head + tail


def _describe_trend(pct: float | None) -> str:
    if pct is None:
        return "판단 불가 (비교 구간 부족)"
    if pct >= 5:
        return f"상승 (최근 7일 평균 {pct:+.1f}%)"
    if pct <= -5:
        return f"하락 (최근 7일 평균 {pct:+.1f}%)"
    return f"보합 (최근 7일 평균 {pct:+.1f}%)"


# ---------------------------------------------------------------- 품목별
def _analyze_item(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """한 품목의 두 축과 판정을 계산한다."""
    rows = sorted(rows, key=lambda r: r["date"])
    values = [r["value"] for r in rows]

    recent = rows[-RECENT_DAYS:]
    prev = rows[-RECENT_DAYS * 2:-RECENT_DAYS]
    recent_vals = [r["value"] for r in recent]
    prev_vals = [r["value"] for r in prev]

    recent_avg = sum(recent_vals) / len(recent_vals) if recent_vals else None
    prev_avg = sum(prev_vals) / len(prev_vals) if prev_vals else None
    wow = ((recent_avg - prev_avg) / prev_avg * 100
           if recent_avg is not None and prev_avg else None)

    idx = _md_index(rows)
    pairs = [p for p in (_normal_for(r["date"], idx) for r in recent) if p is not None]
    normals = [avg for avg, _ in pairs]
    peer_total = sum(n for _, n in pairs)
    normal_avg = sum(normals) / len(normals) if normals else None
    yoy = ((recent_avg - normal_avg) / normal_avg * 100
           if recent_avg is not None and normal_avg else None)

    verdict, verdict_short, tone = _verdict(yoy)

    # 이 품목이 1년 중 가장 싼 달 — "제철"이 값으로 나타나는지
    by_month: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by_month[r["date"][5:7]].append(r["value"])
    month_avg = {m: sum(v) / len(v) for m, v in by_month.items()}
    cheapest_month = min(month_avg, key=month_avg.get) if month_avg else None

    return {
        "item": name,
        "count": len(rows),
        "latest": values[-1] if values else None,
        "latest_date": rows[-1]["date"] if rows else None,
        "recent_avg": round(recent_avg, 1) if recent_avg is not None else None,
        "prev_avg": round(prev_avg, 1) if prev_avg is not None else None,
        "normal_avg": round(normal_avg, 1) if normal_avg is not None else None,
        "vs_normal_pct": round(yoy, 1) if yoy is not None else None,
        "change_rate_pct": round(wow, 1) if wow is not None else None,
        "verdict": verdict,
        "verdict_short": verdict_short,
        "verdict_tone": tone,
        "verdict_reason": _reason(name, yoy, wow),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "average": round(sum(values) / len(values), 1) if values else None,
        "cheapest_month": int(cheapest_month) if cheapest_month else None,
        "normal_peers": peer_total,
    }


# ---------------------------------------------------------------- 요약
def build_summary() -> dict[str, Any]:
    rows = list_data()
    if not rows:
        return dict(EMPTY_SUMMARY)

    by_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_item[r["memo"] or "(품목 없음)"].append(r)

    # 평년 대비가 낮은 순 = 지금 사기 좋은 순
    items = sorted(
        (_analyze_item(name, rs) for name, rs in by_item.items()),
        key=lambda x: (x["vs_normal_pct"] is None, x["vs_normal_pct"]),
    )

    buy_now = [i["item"] for i in items if i["verdict_tone"] == "good"]
    avoid = [i["item"] for i in items if i["verdict_tone"] == "bad"]

    dates = sorted({r["date"] for r in rows})
    years = sorted({d[:4] for d in dates})
    peers = sum(i["normal_peers"] for i in items)
    if any(i["vs_normal_pct"] is not None for i in items):
        basis = (f"{', '.join(years)}년 자료에서, 품목마다 최근 {RECENT_DAYS}일 각각의 "
                 f"같은 달력 시기 ±{NORMAL_WINDOW_DAYS}일에 해당하는 다른 해 기록"
                 f"(총 {peers:,}건)을 평균")
    else:
        basis = f"평년 비교 불가 — 수집 연도가 {len(years)}개뿐입니다({', '.join(years)})"

    # 장바구니 = 12품목을 한 번씩 담았을 때의 합계. 헤드라인 용도.
    latest_date = dates[-1]
    basket_today = sum(r["value"] for r in rows if r["date"] == latest_date)
    basket_recent = [
        sum(r["value"] for r in rows if r["date"] == d) for d in dates[-RECENT_DAYS:]
    ]
    basket_prev = [
        sum(r["value"] for r in rows if r["date"] == d)
        for d in dates[-RECENT_DAYS * 2:-RECENT_DAYS]
    ]
    b_recent = sum(basket_recent) / len(basket_recent) if basket_recent else None
    b_prev = sum(basket_prev) / len(basket_prev) if basket_prev else None
    b_wow = ((b_recent - b_prev) / b_prev * 100) if b_recent and b_prev else None

    # 전체 판정 = 품목별 평년 대비의 중앙값. 평균은 대하·무화과처럼 값이 큰
    # 품목에 끌려가므로, 품목 하나를 한 표로 세는 중앙값이 더 공정하다.
    yoys = [i["vs_normal_pct"] for i in items if i["vs_normal_pct"] is not None]
    overall_yoy = statistics.median(yoys) if yoys else None
    overall_verdict, overall_short, overall_tone = _verdict(overall_yoy)

    good, bad = len(buy_now), len(avoid)
    if overall_yoy is None:
        overall_reason = "평년 비교가 불가능해 전체 판정을 낼 수 없습니다."
    else:
        overall_reason = (
            f"{len(items)}개 품목 중 {good}개가 사기 좋고 {bad}개는 미루는 편이 낫습니다. "
            f"품목별 평년 대비의 중앙값은 {overall_yoy:+.1f}%입니다."
        )
        if buy_now:
            overall_reason += f" 지금 담을 만한 것: {', '.join(buy_now[:4])}."

    values = [r["value"] for r in rows]
    peak = max(rows, key=lambda r: r["value"])
    trough = min(rows, key=lambda r: r["value"])
    monthly: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        monthly[r["date"][:7]].append(r["value"])

    return {
        "period": f"{dates[0]} ~ {dates[-1]}",
        "count": len(rows),
        "item_count": len(items),
        "subject": SUBJECT,
        "subject_detail": SUBJECT_DETAIL,
        "unit": UNIT,

        "items": items,
        "buy_now": buy_now,
        "avoid": avoid,

        "basket": {
            "today": basket_today,
            "recent_avg": round(b_recent, 1) if b_recent else None,
            "prev_avg": round(b_prev, 1) if b_prev else None,
            "change_rate_pct": round(b_wow, 1) if b_wow is not None else None,
            "note": f"{len(items)}개 품목을 1kg 씩 담았을 때의 합계",
        },

        "trend": _describe_trend(b_wow),
        "verdict": overall_verdict,
        "verdict_short": overall_short,
        "verdict_tone": overall_tone,
        "verdict_reason": overall_reason,
        "vs_normal_median_pct": round(overall_yoy, 1) if overall_yoy is not None else None,
        "normal_basis": basis,

        # 전체 통계 (기존 화면·문서 호환용)
        "metrics": {
            "total": round(sum(values), 1),
            "average": round(sum(values) / len(values), 1),
            "max": max(values),
            "min": min(values),
            "std_dev": round(statistics.pstdev(values), 1) if len(values) > 1 else 0.0,
        },
        "monthly_average": {m: round(sum(v) / len(v), 1) for m, v in sorted(monthly.items())},
        "peak_date": f"{peak['date']} ({peak['memo']})",
        "trough_date": f"{trough['date']} ({trough['memo']})",
    }


# ---------------------------------------------------------------- 프롬프트
def build_system_prompt(summary: dict[str, Any]) -> str:
    """요약을 사람이 읽는 문장으로 바꿔 시스템 프롬프트에 주입한다 (컨텍스트 주입)."""
    if summary["count"] == 0:
        return (
            "당신은 '제철밥상 플래너'의 데이터 분석 비서입니다.\n"
            "현재 등록된 데이터가 없습니다. 사용자에게 데이터를 먼저 추가하도록 안내하고, "
            "없는 수치를 지어내지 마세요."
        )

    def line(i: dict) -> str:
        vs = f"{i['vs_normal_pct']:+.0f}%" if i["vs_normal_pct"] is not None else "  —  "
        wow = f"{i['change_rate_pct']:+.0f}%" if i["change_rate_pct"] is not None else "  —  "
        return (f"  {i['item']:<5} {i['recent_avg']:>8,.0f}원  "
                f"평년대비 {vs:>6}  전주대비 {wow:>6}  → {i['verdict']}")

    item_lines = "\n".join(line(i) for i in summary["items"])
    b = summary["basket"]

    return f"""당신은 '제철밥상 플래너'의 데이터 분석 비서입니다.

[무엇에 대한 값인가]
- 대상: {summary['subject']} — {summary['subject_detail']}
- 단위: {summary['unit']}
- 기간: {summary['period']} / 총 {summary['count']:,}건 / {summary['item_count']}개 품목

[품목별 현황]  ※ 평년 대비가 낮은(= 사기 좋은) 순서
{item_lines}

[장바구니 전체]
- {b['note']}: 최근 7일 평균 {b['recent_avg']:,.0f}원 (직전 주 {b['prev_avg']:,.0f}원, {b['change_rate_pct']:+.1f}%)

[서버가 내린 판정]  ※ 아래 판정을 그대로 근거로 쓰세요
- 전체: {summary['verdict']}
- 이유: {summary['verdict_reason']}
- 지금 사기 좋은 품목: {', '.join(summary['buy_now']) or '없음'}
- 미루는 편이 나은 품목: {', '.join(summary['avoid']) or '없음'}

[평년 산출 근거]
{summary['normal_basis']}

[답변 규칙]
1. 위 표에 있는 수치만 근거로 사용하고, 없는 수치는 절대 지어내지 마세요.
2. 특정 품목을 물으면 **그 품목의 행**을 근거로 답하세요. 전체 평균으로 얼버무리지 마세요.
3. "뭘 사야 하나" 류의 질문에는 [지금 사기 좋은 품목]을 먼저 제시하세요.
4. 판정을 뒤집거나 다른 결론을 내리지 마세요. 말투만 자연스럽게 바꾸면 됩니다.
5. 값을 이야기할 때는 평년 대비와 전주 대비를 함께 언급하세요. 하나만 말하면 판단할 수 없습니다.
6. 표에 없는 품목을 물으면 "기록에 없다"고 솔직히 말하세요.
7. 숫자는 천 단위 쉼표를 넣고 단위(원/kg)를 붙이세요.
8. 한국어로, 3~5문장 이내로 간결하게 답하세요.

[도구를 쓸 때의 규칙]  ※ 도구 호출이 켜져 있을 때만 해당
9.  get_price_forecast 의 결과는 **예언이 아니라 과거 계절 패턴에서 뽑은 계산**입니다.
    "~할 것입니다" 대신 "지금까지의 패턴대로라면 ~쯤으로 계산됩니다"처럼 말하고,
    결과의 caveat(작황 급변·명절 수요는 반영 안 됨)를 반드시 함께 전하세요.
    환율·날씨·운송비 값은 실제 관측치가 아니라 사용자가 넣은 **가정**입니다.
    가정을 넣지 않았다면(모두 0) 그 얘기를 꺼내지 마세요.
10. get_item_scores 의 축은 두 종류입니다. source 가 measured 인 축(계절성·가격·신선도)은
    실제 가격에서 계산한 값이고, reference 인 축(기호도·편의성·쉬움)은 사람이 적어 둔
    참고값입니다. 참고값을 데이터인 것처럼 말하지 마세요.
11. recommend_dishes 로 음식을 추천할 때는 재료값 판정을 함께 말하고,
    비싼 재료에는 결과에 담긴 대체재를 알려주세요."""
