"""
데이터 API 라우터.

라우터는 HTTP 관심사만 담당한다: 경로, 상태 코드, 검증(Pydantic), 예외 -> HTTP 변환.
Firestore 나 통계 계산은 services 계층이 한다.

⚠️ 경로 순서 주의:
   /api/data/summary 는 /api/data/{data_id} 보다 반드시 위에 있어야 한다.
   아래에 두면 FastAPI 가 "summary" 를 data_id 로 인식해 요약 API 가 동작하지 않는다.
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Response, status

from ..models.schemas import (
    DataCreate,
    DataListOut,
    DataOut,
    DataUpdate,
    MessageOut,
    SummaryOut,
)
from ..services import (
    alternatives,
    catalog,
    data_service,
    forecast_service,
    scoring_service,
    statistics_service,
    summary_service,
)

router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("/summary", response_model=SummaryOut, summary="데이터 요약 (프롬프트 주입용)")
def get_summary() -> dict:
    return summary_service.build_summary()


@router.get("/items", summary="품목 목록")
def get_items() -> dict:
    names = data_service.list_item_names()
    return {"count": len(names), "items": names}


@router.get("/statistics", summary="[보너스] 확장 통계 (이동평균·요일별·분포)")
def get_statistics(
    window: int | None = Query(None, ge=7, le=3650, description="최근 N일만 집계"),
    item: str | None = Query(None, description="품목명. 생략하면 12품목 장바구니 합계"),
) -> dict:
    """
    /summary 와 목적이 다르다.
      summary    : AI 프롬프트에 넣을 짧은 요약 (지표를 늘리면 안 됨)
      statistics : 화면에 그릴 자세한 지표 (이동평균 배열 등 길어도 됨)
    """
    return statistics_service.build_statistics(window, item)


@router.get("/categories", summary="품목 분류 나무 (대·중·소)")
def get_categories() -> dict:
    """
    실제로 데이터가 있는 품목만으로 분류를 만든다.
    카탈로그 전체를 내려주면, 가격이 없는 가지를 눌렀을 때 빈 화면이 나온다.
    """
    names = data_service.list_item_names()
    return {"count": len(names), "tree": catalog.tree(names),
            "vocabulary": catalog.vocabulary()}


@router.get("/monthly", summary="품목별 월평균 (히트맵용)")
def get_monthly() -> dict:
    """
    품목마다 12칸씩 한 번에 내려준다.

    품목별로 따로 부르게 두면 46품목에 46번 호출이 되고, Firestore 무료 한도의
    읽기를 그만큼 더 쓴다. 화면 한 장을 위한 데이터는 한 번에 보내는 편이 낫다.
    """
    out: dict[str, dict[str, float]] = {}
    rel: dict[str, dict[str, float]] = {}
    for name in data_service.list_item_names():
        buckets: dict[str, list[float]] = {}
        vals: list[float] = []
        for r in data_service.list_data(item=name):
            buckets.setdefault(r["date"][5:7], []).append(r["value"])
            vals.append(r["value"])
        if not vals:
            continue
        mean = sum(vals) / len(vals)
        out[name] = {m: round(sum(v) / len(v), 1) for m, v in buckets.items()}
        # 연평균 대비 %. 절대 가격으로 칠하면 비싼 한 품목이 표 전체를 덮는다.
        rel[name] = {m: round((sum(v) / len(v) - mean) / mean * 100, 1)
                     for m, v in buckets.items()}
    return {"count": len(out), "monthly": out, "relative": rel}


@router.get("/alternatives", summary="대체 식재료")
def get_alternatives(item: str = Query(..., description="품목명")) -> dict:
    alts = alternatives.alternatives_for(item)
    return {"item": item, "count": len(alts), "alternatives": alts}


@router.get("/scores", summary="[보너스] 품목별 평가 지표 (레이더용)")
def get_scores(
    item: str | None = Query(None, description="한 품목만. 생략하면 전 품목"),
) -> dict:
    """
    여섯 축 중 계절성·가격·신선도는 측정값, 기호도·편의성·쉬움은 참고값이다.
    응답의 axes[].source 가 어느 쪽인지 알려주므로 화면에서 구분해 표시한다.
    """
    summary = summary_service.build_summary()
    items = summary.get("items", [])
    if item:
        items = [i for i in items if i["item"] == item]
        if not items:
            raise HTTPException(status_code=404, detail=f"'{item}' 품목의 데이터가 없습니다.")
    return {"count": len(items),
            "axes": [{"key": k, "label": l, "source": s} for k, l, s in scoring_service.AXES],
            "items": [scoring_service.scores_for(i) for i in items]}


@router.get("/swot", summary="[보너스] 장바구니 SWOT")
def get_swot(
    items: str | None = Query(None, description="쉼표로 구분한 품목. 생략하면 전체"),
) -> dict:
    summary = summary_service.build_summary()
    rows = summary.get("items", [])
    if items:
        want = {s.strip() for s in items.split(",") if s.strip()}
        rows = [r for r in rows if r["item"] in want]

    monthly: dict[str, dict[str, float]] = {}
    for r in rows:
        series = data_service.list_data(item=r["item"])
        buckets: dict[str, list[float]] = {}
        for x in series:
            buckets.setdefault(x["date"][5:7], []).append(x["value"])
        monthly[r["item"]] = {m: sum(v) / len(v) for m, v in buckets.items()}

    return {"count": len(rows), "subject": ", ".join(r["item"] for r in rows[:5]),
            **scoring_service.swot(rows, monthly)}


@router.get("/forecast", summary="[보너스] 향후 가격 추이선 (가정값 반영)")
def get_forecast(
    item: str | None = Query(None, description="품목명. 생략하면 장바구니 합계"),
    days: int = Query(60, ge=7, le=180, description="며칠 앞까지"),
    fx: float = Query(0, ge=-50, le=50, description="환율이 몇 % 오른다고 가정할지"),
    weather: float = Query(0, ge=-50, le=50, description="작황이 몇 % 나빠진다고 가정할지"),
    fuel: float = Query(0, ge=-50, le=50, description="운송비가 몇 % 오른다고 가정할지"),
) -> dict:
    """
    예언이 아니라 계산이다. 환율·날씨·운송비는 실제 데이터가 아니라
    사용자가 넣는 **가정값**이며, 품목별 민감도로 환산해 선을 움직인다.
    응답의 method 와 caveat 를 화면에 그대로 보여줄 것.
    """
    return forecast_service.build_forecast(item, days, fx, weather, fuel)


@router.get("/export", summary="[보너스] 데이터 내보내기 (CSV / JSON)")
def export_data(
    format: str = Query("csv", pattern="^(csv|json)$", description="csv 또는 json"),
    start: str | None = Query(None, description="시작일 YYYY-MM-DD"),
    end: str | None = Query(None, description="종료일 YYYY-MM-DD"),
):
    items = data_service.list_data(start=start, end=end)
    stamp = datetime.now().strftime("%Y%m%d")

    if format == "json":
        payload = [{"date": i["date"], "value": i["value"], "memo": i["memo"]} for i in items]
        return Response(
            content=json.dumps(payload, ensure_ascii=False, indent=2),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="jecheol_{stamp}.json"'},
        )

    return Response(
        content=statistics_service.to_csv(items),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="jecheol_{stamp}.csv"'},
    )


@router.get("", response_model=DataListOut, summary="데이터 목록 조회")
def get_data_list(
    limit: int | None = Query(None, ge=1, le=1000, description="최근 N건만 조회"),
    start: str | None = Query(None, description="시작일 YYYY-MM-DD"),
    end: str | None = Query(None, description="종료일 YYYY-MM-DD"),
    item: str | None = Query(None, description="품목명으로 거르기"),
) -> dict:
    items = data_service.list_data(limit=limit, start=start, end=end, item=item)
    return {"count": len(items), "items": items}


@router.post(
    "", response_model=DataOut, status_code=status.HTTP_201_CREATED, summary="새 데이터 추가"
)
def post_data(payload: DataCreate) -> dict:
    return data_service.create_data(payload)


@router.post(
    "/bulk",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
    summary="데이터 일괄 추가 (시드 업로드용)",
)
def post_data_bulk(payloads: list[DataCreate]) -> dict:
    if not payloads:
        raise HTTPException(status_code=400, detail="빈 배열은 저장할 수 없습니다.")
    if len(payloads) > 1000:
        raise HTTPException(status_code=400, detail="한 번에 1000건까지만 저장할 수 있습니다.")
    n = data_service.create_many(payloads)
    return {"ok": True, "message": f"{n}건 저장 완료"}


@router.get("/{data_id}", response_model=DataOut, summary="데이터 단건 조회")
def get_data_one(data_id: str) -> dict:
    try:
        return data_service.get_data(data_id)
    except data_service.DataNotFound:
        raise HTTPException(status_code=404, detail=f"데이터를 찾을 수 없습니다: {data_id}")


@router.put("/{data_id}", response_model=DataOut, summary="데이터 수정")
def put_data(data_id: str, payload: DataUpdate) -> dict:
    try:
        return data_service.update_data(data_id, payload)
    except data_service.DataNotFound:
        raise HTTPException(status_code=404, detail=f"데이터를 찾을 수 없습니다: {data_id}")


@router.delete("/{data_id}", response_model=MessageOut, summary="데이터 삭제")
def delete_data(data_id: str) -> dict:
    try:
        data_service.delete_data(data_id)
    except data_service.DataNotFound:
        raise HTTPException(status_code=404, detail=f"데이터를 찾을 수 없습니다: {data_id}")
    return {"ok": True, "message": f"삭제 완료: {data_id}"}
