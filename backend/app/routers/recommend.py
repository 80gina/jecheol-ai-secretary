"""
추천 API 라우터.

화면의 조건 손잡이가 여기로 온다. 라우터는 값을 받아 넘기고
결과를 HTTP 로 바꾸는 일만 한다 — 고르는 규칙은 recommend_service 에 있다.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..models.schemas import RecommendRequest
from ..services import recommend_service

router = APIRouter(prefix="/api", tags=["recommend"])


@router.post("/recommend", summary="[보너스] 조건에 맞는 음식과 장바구니 추천")
def post_recommend(req: RecommendRequest) -> dict:
    """
    조리법·목적·계절감·신선도·난이도·편의성을 받아
    음식을 고르고, 그 재료를 지금 값으로 판정해 함께 돌려준다.
    """
    return recommend_service.recommend(
        prep=req.prep,
        purpose=req.purpose,
        season_weight=req.season_weight,
        freshness_weight=req.freshness_weight,
        difficulty=req.difficulty,
        convenience=req.convenience,
        limit=req.limit,
    )
