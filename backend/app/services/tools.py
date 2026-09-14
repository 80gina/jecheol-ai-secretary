"""
[보너스 ①] Function Calling 도구 정의 및 실행기.

컨텍스트 주입(요약 문장을 시스템 프롬프트에 넣기)만으로는 요약에 없는 질문
— 예: "6월 중에서 제일 쌌던 날이 언제야?", "지난주 기록 보여줘" — 에 답할 수 없다.
그래서 내부 API 를 '도구'로 노출해 GPT 가 필요할 때 스스로 호출하게 한다.

여기에 정의한 TOOL_SPECS 는 그대로
  - OpenAI Chat Completions 의 tools 파라미터
  - MCP Server 의 tool 목록  (mcp_server/server.py)
양쪽에서 재사용된다. 정의를 한 곳에만 두기 위해서다.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from . import (
    alternatives,
    catalog,
    conversation_service,
    data_service,
    forecast_service,
    recommend_service,
    scoring_service,
    summary_service,
)

# --------------------------------------------------------------------------
# 도구 스키마 (JSON Schema)
# --------------------------------------------------------------------------
TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "get_data_summary",
        "description": (
            "제철 식재료 가격 데이터 전체의 요약 통계를 가져온다. "
            "기간, 레코드 수, 평균/최대/최소, 최근 추세, 월별 평균을 포함한다. "
            "전반적인 흐름·평균·추세를 묻는 질문에 사용한다."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "query_data",
        "description": (
            "특정 품목·기간의 개별 가격 레코드를 조회한다. 요약만으로는 답할 수 없는 "
            "'그 품목의 특정 날짜/특정 달/최근 며칠' 실제 값을 물을 때 사용한다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "item": {"type": "string", "description": "품목명 (예: 배추, 전어). 생략하면 전 품목"},
                "start": {"type": "string", "description": "시작일 YYYY-MM-DD (포함)"},
                "end": {"type": "string", "description": "종료일 YYYY-MM-DD (포함)"},
                "limit": {
                    "type": "integer",
                    "description": "가져올 최대 개수 (최신 순). 기본 30, 최대 100",
                    "default": 30,
                },
            },
            "required": [],
        },
    },
    {
        "name": "find_extreme",
        "description": (
            "지정한 품목·기간 안에서 가격이 가장 높았던/낮았던 날을 찾는다. "
            "'배추가 제일 쌌던 날', '전어 최고가는 언제' 같은 질문에 사용한다. "
            "품목을 지정하지 않으면 전 품목을 통틀어 찾는다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["max", "min"],
                    "description": "max=최고가, min=최저가",
                },
                "item": {"type": "string", "description": "품목명. 생략하면 전 품목 통틀어"},
                "start": {"type": "string", "description": "시작일 YYYY-MM-DD"},
                "end": {"type": "string", "description": "종료일 YYYY-MM-DD"},
            },
            "required": ["mode"],
        },
    },
    {
        "name": "get_item_verdict",
        "description": (
            "특정 품목의 지금 판정을 가져온다. 평년 대비·전주 대비 두 축과 "
            "'지금 사세요 / 미루세요' 판정, 그 이유 문장이 함께 온다. "
            "'배추 지금 사도 돼?', '전어 값 어때?' 처럼 품목 하나를 물을 때 사용한다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "item": {"type": "string", "description": "품목명 (예: 배추, 전어, 시금치)"},
            },
            "required": ["item"],
        },
    },
    {
        "name": "suggest_alternative",
        "description": (
            "특정 제철 품목이 비쌀 때, 같은 요리에서 자리를 대신할 수 있는 대체 재료를 "
            "추천한다. 기록에 있는 품목이면 실제 평균가 비교까지 함께 돌려준다. "
            "'배추가 비싼데 뭘 대신 쓰지?', '이거 말고 다른 거 없나?' 같은 질문에 사용한다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "item": {
                    "type": "string",
                    "description": "대체하려는 품목 이름 (예: 배추, 전어, 애호박)",
                },
            },
            "required": ["item"],
        },
    },
    {
        "name": "browse_by_category",
        "description": (
            "대분류·중분류·소분류로 품목을 훑는다. '채소는 지금 뭐가 싸?', "
            "'수산물 중에 살 만한 거 있어?' 처럼 갈래로 묻는 질문에 사용한다. "
            "아무 인자도 주지 않으면 어떤 분류가 있는지 목록을 돌려준다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "major": {"type": "string", "description": "대분류 (채소·수산·과일·곡물)"},
                "mid": {"type": "string", "description": "중분류 (엽경채류·근채류·생선류 등)"},
                "minor": {"type": "string", "description": "소분류"},
            },
            "required": [],
        },
    },
    {
        "name": "get_item_scores",
        "description": (
            "품목 하나의 여섯 축 평가(계절성·가격·신선도·기호도·편의성·쉬움)를 가져온다. "
            "'지금 배추 어때?'처럼 값 말고 전반적인 평가를 물을 때 사용한다. "
            "각 축의 source 가 measured 면 실제 가격에서 계산한 값이고 "
            "reference 면 카탈로그의 참고값이다. 답할 때 이 구분을 지켜라."
        ),
        "parameters": {
            "type": "object",
            "properties": {"item": {"type": "string", "description": "품목명"}},
            "required": ["item"],
        },
    },
    {
        "name": "get_swot_analysis",
        "description": (
            "지금 장바구니(또는 지정한 품목들)의 강점·약점·기회·위협을 가져온다. "
            "'이번 주 장보기 어떻게 짜야 해?', '뭘 미루고 뭘 지금 사?' 같은 "
            "판단이 필요한 질문에 사용한다. 각 항목에 계산된 근거가 붙어 있다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array", "items": {"type": "string"},
                    "description": "품목 이름 목록. 생략하면 전 품목",
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_price_forecast",
        "description": (
            "앞으로의 가격 흐름을 계산한다. '다음 달에 사는 게 나아?', "
            "'김장철에 배추값 어떻게 될까?' 같은 질문에 사용한다. "
            "⚠️ 이것은 예언이 아니라 과거 계절 패턴 기반 계산이다. "
            "답할 때 반드시 method 와 caveat 를 함께 전하고, 단정하지 마라."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "item": {"type": "string", "description": "품목명. 생략하면 장바구니 합계"},
                "days": {"type": "integer", "description": "며칠 앞까지. 기본 60", "default": 60},
                "fx_pct": {"type": "number", "description": "환율이 몇 % 오른다는 가정. 기본 0"},
                "weather_pct": {"type": "number", "description": "작황이 몇 % 나빠진다는 가정. 기본 0"},
                "fuel_pct": {"type": "number", "description": "운송비가 몇 % 오른다는 가정. 기본 0"},
            },
            "required": [],
        },
    },
    {
        "name": "recommend_dishes",
        "description": (
            "조리법·목적·계절감·난이도 조건에 맞는 음식과 그 재료값을 추천받는다. "
            "'국물 요리 뭐 할까?', '도시락 반찬 추천해줘', '손님상 차릴 건데' 같은 "
            "질문에 사용한다. 재료마다 지금 값과 판정, 비싸면 대체재까지 함께 온다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prep": {
                    "type": "array", "items": {"type": "string"},
                    "description": "조리법. 국·찌개 / 구이 / 볶음 / 무침·생채 / 조림 / 찜 / 전·튀김 / 절임·저장 / 생것",
                },
                "purpose": {
                    "type": "array", "items": {"type": "string"},
                    "description": "식사 목적. 밥반찬 / 국물 / 손님상 / 도시락 / 간식·후식 / 술안주 / 저장·김장",
                },
                "season_weight": {
                    "type": "number",
                    "description": "제철을 얼마나 중시할지 0~1. 기본 0.7", "default": 0.7,
                },
                "difficulty": {"type": "integer", "description": "원하는 난이도 1~5"},
                "convenience": {"type": "integer", "description": "원하는 편의성 1~5"},
                "limit": {"type": "integer", "description": "몇 가지. 기본 5", "default": 5},
            },
            "required": [],
        },
    },
    {
        "name": "list_past_conversations",
        "description": (
            "저장된 이전 대화 목록(제목, 시각, 미리보기)을 조회한다. "
            "'전에 무슨 얘기 했지?' 같은 질문에 사용한다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "최대 개수. 기본 10", "default": 10}
            },
            "required": [],
        },
    },
]


# --------------------------------------------------------------------------
# 실제 구현
# --------------------------------------------------------------------------
def _get_data_summary() -> dict[str, Any]:
    return summary_service.build_summary()


def _query_data(
    item: str | None = None, start: str | None = None,
    end: str | None = None, limit: int = 30
) -> dict[str, Any]:
    limit = max(1, min(int(limit or 30), 100))
    item = (item or "").strip() or None
    if item and item not in data_service.list_item_names():
        return {
            "found": False,
            "reason": f"'{item}' 은(는) 기록에 없는 품목입니다.",
            "known_items": data_service.list_item_names(),
        }
    rows = data_service.list_data(limit=limit, start=start, end=end, item=item)
    return {
        "found": True,
        "item": item or "전 품목",
        "count": len(rows),
        "items": [
            {"date": r["date"], "item": r["memo"], "value": r["value"]} for r in rows
        ],
    }


def _find_extreme(
    mode: str, item: str | None = None,
    start: str | None = None, end: str | None = None
) -> dict[str, Any]:
    item = (item or "").strip() or None
    if item and item not in data_service.list_item_names():
        return {
            "found": False,
            "reason": f"'{item}' 은(는) 기록에 없는 품목입니다.",
            "known_items": data_service.list_item_names(),
        }
    rows = data_service.list_data(start=start, end=end, item=item)
    if not rows:
        return {"found": False, "reason": "해당 조건에 맞는 데이터가 없습니다."}

    picker = max if mode == "max" else min
    target = picker(rows, key=lambda x: x["value"])
    return {
        "found": True,
        "mode": mode,
        "item": target["memo"],
        "scope": item or "전 품목",
        "date": target["date"],
        "value": target["value"],
        "scanned": len(rows),
    }


def _item_averages() -> dict[str, dict[str, float]]:
    """기록에 남은 품목(memo)별 평균가. 대체재의 값 비교에 쓴다."""
    from collections import defaultdict

    bucket: dict[str, list[float]] = defaultdict(list)
    for it in data_service.list_data():
        if it["memo"]:
            bucket[it["memo"]].append(it["value"])
    return {
        k: {"avg": round(sum(v) / len(v), 1), "count": len(v)}
        for k, v in bucket.items()
    }


def _get_item_verdict(item: str) -> dict[str, Any]:
    """품목 하나의 판정. summary 의 items 에서 그 품목만 꺼내 온다."""
    item = (item or "").strip()
    known = data_service.list_item_names()
    if item not in known:
        return {
            "found": False,
            "reason": f"'{item}' 은(는) 기록에 없는 품목입니다.",
            "known_items": known,
        }
    for row in summary_service.build_summary()["items"]:
        if row["item"] == item:
            return {"found": True, **row}
    return {"found": False, "reason": f"'{item}' 의 판정을 계산하지 못했습니다."}


def _suggest_alternative(item: str) -> dict[str, Any]:
    """
    대체재 추천.

    도메인 지식(대체 가능한가)과 실제 데이터(값이 어떤가)를 나눠서 다룬다.
      - 조리에서 자리를 대신할 수 있는지 -> alternatives.ALT_TABLE
      - 그래서 얼마나 싼지               -> 기록된 데이터의 품목별 평균

    두 가지를 합쳐야 "얼갈이배추로 바꾸세요, 국거리로 거의 같고 12% 쌉니다"가 된다.
    """
    item = (item or "").strip()
    if not item:
        return {"found": False, "reason": "품목 이름이 비어 있습니다."}

    alts = alternatives.alternatives_for(item)
    stats = _item_averages()
    base = stats.get(item)

    if not alts:
        # 표에 없는 품목 — 지어내지 말고, 데이터에서 싼 품목만 사실대로 돌려준다
        cheap = sorted(
            ({"item": k, "avg": v["avg"], "count": v["count"]}
             for k, v in stats.items() if v["count"] >= 3 and k != item),
            key=lambda x: x["avg"],
        )[:3]
        return {
            "found": False,
            "item": item,
            "reason": f"'{item}'에 대해 등록된 대체 재료 정보가 없습니다.",
            "note": "아래는 조리 적합성과 무관하게, 기록상 평균가가 낮은 품목입니다.",
            "cheapest_in_data": cheap,
            "known_items": alternatives.known_items()[:40],
        }

    out = []
    for a in alts:
        row = {"item": a["item"], "why": a["why"]}
        st = stats.get(a["item"])
        if st:
            row["avg_price"] = st["avg"]
            row["record_count"] = st["count"]
            if base:
                diff = (st["avg"] - base["avg"]) / base["avg"] * 100
                row["vs_target_pct"] = round(diff, 1)
                row["price_note"] = (
                    f"기록상 평균 {st['avg']:,.0f}원으로 {item}보다 "
                    f"{abs(diff):.0f}% {'쌉니다' if diff < 0 else '비쌉니다'}"
                )
        else:
            row["price_note"] = "이 품목은 기록에 없어 값을 비교할 수 없습니다."
        out.append(row)

    return {
        "found": True,
        "item": item,
        "target_avg_price": base["avg"] if base else None,
        "alternatives": out,
        "basis": "조리 적합성은 등록된 대체재 표, 가격은 기록된 데이터에서 각각 가져왔습니다.",
    }


def _browse_by_category(major: str | None = None, mid: str | None = None,
                        minor: str | None = None) -> dict[str, Any]:
    names = data_service.list_item_names()
    tree = catalog.tree(names)
    if not major:
        return {
            "categories": [
                {"major": m["name"], "count": m["count"],
                 "mids": [{"mid": x["name"], "count": x["count"]} for x in m["children"]]}
                for m in tree
            ],
            "hint": "major 를 지정하면 그 갈래의 품목별 판정을 돌려준다.",
        }

    picked: list[str] = []
    for m in tree:
        if m["name"] != major:
            continue
        for x in m["children"]:
            if mid and x["name"] != mid:
                continue
            for y in x["children"]:
                if minor and y["name"] != minor:
                    continue
                picked.extend(y["items"])

    if not picked:
        return {"found": False, "known_categories": [m["name"] for m in tree]}

    summary = summary_service.build_summary()
    rows = [i for i in summary["items"] if i["item"] in picked]
    return {
        "found": True,
        "category": " > ".join(x for x in (major, mid, minor) if x),
        "count": len(rows),
        "items": [
            {"item": r["item"], "recent_avg": r["recent_avg"],
             "vs_normal_pct": r["vs_normal_pct"], "verdict": r["verdict"]}
            for r in rows
        ],
    }


def _get_item_scores(item: str) -> dict[str, Any]:
    summary = summary_service.build_summary()
    row = next((i for i in summary["items"] if i["item"] == item.strip()), None)
    if row is None:
        return {"found": False, "item": item,
                "known_items": data_service.list_item_names()}
    sc = scoring_service.scores_for(row)
    return {
        "found": True, **sc,
        "note": ("axes 의 source 가 measured 인 축(계절성·가격·신선도)은 실제 가격에서 "
                 "계산한 값이고, reference 인 축(기호도·편의성·쉬움)은 사람이 적어 둔 "
                 "참고값이다. 두 가지를 같은 근거인 것처럼 말하지 마라."),
    }


def _get_swot_analysis(items: list[str] | None = None) -> dict[str, Any]:
    summary = summary_service.build_summary()
    rows = summary["items"]
    if items:
        want = {s.strip() for s in items}
        rows = [r for r in rows if r["item"] in want]
    if not rows:
        return {"found": False, "known_items": data_service.list_item_names()}

    monthly: dict[str, dict[str, float]] = {}
    for r in rows:
        buckets: dict[str, list[float]] = {}
        for x in data_service.list_data(item=r["item"]):
            buckets.setdefault(x["date"][5:7], []).append(x["value"])
        monthly[r["item"]] = {m: sum(v) / len(v) for m, v in buckets.items()}

    return {"found": True, "count": len(rows),
            "items": [r["item"] for r in rows],
            **scoring_service.swot(rows, monthly)}


def _get_price_forecast(item: str | None = None, days: int = 60,
                        fx_pct: float = 0.0, weather_pct: float = 0.0,
                        fuel_pct: float = 0.0) -> dict[str, Any]:
    f = forecast_service.build_forecast(item, int(days or 60), fx_pct, weather_pct, fuel_pct)
    if not f.get("ok"):
        return {"ok": False, "reason": f.get("reason")}

    # 60일치 점을 전부 보내면 토큰만 먹고 GPT 가 요약하지도 못한다.
    # 지금 · 한 달 뒤 · 끝점, 그리고 가장 싼 날만 추려 보낸다.
    pts = f["forecast"]
    cheapest = min(pts, key=lambda p: p["value"])
    marks = [pts[0], pts[min(29, len(pts) - 1)], pts[-1]]
    now = f["history"][-1]["value"] if f["history"] else None
    return {
        "ok": True,
        "item": f["item"],
        "today": now,
        "milestones": [
            {"date": p["date"], "expected": p["value"],
             "range": [p["low"], p["high"]],
             "vs_today_pct": (round((p["value"] - now) / now * 100, 1) if now else None)}
            for p in marks
        ],
        "cheapest_ahead": {"date": cheapest["date"], "expected": cheapest["value"]},
        "assumptions": f["assumptions"],
        "method": f["method"],
        "caveat": f["caveat"],
    }


def _recommend_dishes(prep: list[str] | None = None, purpose: list[str] | None = None,
                      season_weight: float = 0.7, difficulty: int | None = None,
                      convenience: int | None = None, limit: int = 5) -> dict[str, Any]:
    r = recommend_service.recommend(
        prep=prep, purpose=purpose, season_weight=season_weight,
        difficulty=difficulty, convenience=convenience, limit=int(limit or 5))
    if not r.get("ok"):
        return r
    # 화면용 전체 구조를 그대로 넘기면 길다. 말로 옮길 만큼만 추린다.
    return {
        "ok": True, "month": r["month"],
        "dishes": [
            {"dish": d["dish"], "prep": d["prep"], "cost": d["cost"], "why": d["why"],
             "ingredients": [
                 {"item": i["item"], "price": i.get("recent_avg"),
                  "verdict": i.get("verdict_short"),
                  "alternatives": [a["item"] for a in (i.get("alternatives") or [])]}
                 for i in d["ingredients"]
             ]}
            for d in r["dishes"]
        ],
        "vocabulary": r["vocabulary"],
    }


def _list_past_conversations(limit: int = 10) -> dict[str, Any]:
    limit = max(1, min(int(limit or 10), 50))
    items = conversation_service.list_conversations(limit=limit)
    return {
        "count": len(items),
        "items": [
            {
                "id": c["id"],
                "title": c["title"],
                "updated_at": c["updated_at"],
                "preview": c["preview"],
            }
            for c in items
        ],
    }


TOOL_IMPLS: dict[str, Callable[..., Any]] = {
    "get_data_summary": _get_data_summary,
    "query_data": _query_data,
    "find_extreme": _find_extreme,
    "get_item_verdict": _get_item_verdict,
    "suggest_alternative": _suggest_alternative,
    "browse_by_category": _browse_by_category,
    "get_item_scores": _get_item_scores,
    "get_swot_analysis": _get_swot_analysis,
    "get_price_forecast": _get_price_forecast,
    "recommend_dishes": _recommend_dishes,
    "list_past_conversations": _list_past_conversations,
}


def openai_tool_params() -> list[dict[str, Any]]:
    """TOOL_SPECS 를 OpenAI tools 파라미터 형식으로 변환."""
    return [{"type": "function", "function": spec} for spec in TOOL_SPECS]


def run_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    impl = TOOL_IMPLS.get(name)
    if impl is None:
        return {"error": f"알 수 없는 도구: {name}"}
    try:
        return impl(**(arguments or {}))
    except TypeError as exc:
        return {"error": f"인자가 올바르지 않습니다: {exc}"}
    except Exception as exc:  # noqa: BLE001 - 도구 실패가 대화 전체를 죽이면 안 된다
        return {"error": f"도구 실행 실패: {exc}"}


def run_tool_json(name: str, raw_arguments: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """OpenAI 가 넘겨준 JSON 문자열 인자를 파싱해 실행. (인자, 결과) 를 돌려준다."""
    try:
        args = json.loads(raw_arguments) if raw_arguments else {}
    except json.JSONDecodeError:
        args = {}
    return args, run_tool(name, args)
