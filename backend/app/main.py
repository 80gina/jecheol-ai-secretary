"""
제철밥상 플래너 AI 비서 - FastAPI 진입점.

실행:
    uvicorn app.main:app --reload
문서:
    http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from .config import settings
from .db import get_backend, init_db
from .routers import chat, conversations, data, recommend
from .services import data_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seasonal-ai")


def _autoseed() -> None:
    """
    데이터가 하나도 없으면 data/seed_data.json 을 넣어 준다.

    왜 필요한가
        메모리 저장소는 서버를 끌 때마다 비워진다. 그때마다 사용자가 시드 업로드
        명령을 따로 쳐야 한다면 "켜면 바로 보인다"가 되지 않는다.

    안전장치
        - 이미 데이터가 있으면 아무것도 하지 않는다 (중복 저장 방지)
        - Firestore 를 쓰는 경우에는 SEED_ON_START=true 를 명시해야만 동작한다.
          실제 DB 에 730건이 소리 없이 들어가면 곤란하기 때문이다.
    """
    from pathlib import Path

    if not settings.should_autoseed():
        logger.info("자동 시드 꺼짐 (SEED_ON_START=%s)", settings.SEED_ON_START)
        return

    from .models.schemas import DataCreate
    from .services import data_service

    if data_service.list_data(limit=1):
        logger.info("이미 데이터가 있어 자동 시드를 건너뜁니다.")
        return

    path = Path(__file__).resolve().parents[1] / "data" / "seed_data.json"
    if not path.exists():
        logger.warning("자동 시드할 %s 가 없습니다. scripts/generate_data.py 를 먼저 실행하세요.", path.name)
        return

    import json

    records = json.loads(path.read_text(encoding="utf-8"))
    for r in records:
        data_service.create_data(DataCreate(**r))
    logger.info("자동 시드 완료: %d건 (%s ~ %s)",
                len(records), records[0]["date"], records[-1]["date"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        backend = init_db()
        logger.info("DB 초기화 완료: %s", backend)
        try:
            _autoseed()
        except Exception as exc:  # noqa: BLE001
            logger.error("자동 시드 실패(서버는 계속 뜹니다): %s", exc)
    except Exception as exc:  # noqa: BLE001
        # DB 초기화에 실패해도 앱은 뜨게 한다. /health 에서 원인을 확인할 수 있다.
        logger.error("DB 초기화 실패: %s", exc)
    yield


app = FastAPI(
    title="제철밥상 플래너 AI 비서 API",
    description=(
        "제철 식재료 가격 시계열 데이터를 저장·요약하고, 그 요약을 시스템 프롬프트에 "
        "주입해 GPT 가 '내 데이터를 아는' 답변을 하도록 만드는 서비스입니다.\n\n"
        "⚠️ Render 무료 티어는 15분간 요청이 없으면 잠들기 때문에, "
        "첫 요청은 응답까지 최대 60초가 걸릴 수 있습니다."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# 프론트(Vercel)와 백엔드(Render)는 서로 다른 도메인이라 브라우저가 기본적으로
# 요청을 차단한다. 허용할 출처를 환경 변수로 관리한다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(data.router)
app.include_router(conversations.router)
app.include_router(chat.router)
app.include_router(recommend.router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


def _llm_host() -> str:
    """접속 중인 LLM 호스트 이름. 주소가 비어 있으면 라이브러리 기본값(OpenAI)."""
    if not settings.OPENAI_BASE_URL:
        return "api.openai.com"
    try:
        from urllib.parse import urlparse

        return urlparse(settings.OPENAI_BASE_URL).hostname or settings.OPENAI_BASE_URL
    except Exception:  # noqa: BLE001
        return settings.OPENAI_BASE_URL


@app.get("/health", tags=["system"], summary="헬스체크 / 콜드스타트 깨우기")
def health() -> dict:
    """
    프론트는 페이지 로드 직후 이 엔드포인트를 먼저 때려서 Render 인스턴스를 깨운다.
    (무료 티어 콜드스타트 대응)
    """
    return {
        "status": "ok",
        "env": settings.APP_ENV,
        "db_backend": get_backend(),
        "openai_configured": bool(settings.OPENAI_API_KEY),
        # 어디로, 무엇으로 붙어 있는지 알린다. 키 자체는 절대 내보내지 않는다.
        #
        # 공급자 이름을 추측해서 붙이지 않고 '접속하는 호스트'를 그대로 보여준다.
        # 중계 게이트웨이를 거치면 주소와 실제 모델 제작사가 다를 수 있어
        # ("copa.codyssey.kr 를 거쳐 gpt-5-mini 를 쓴다") 이름을 지어내면
        # 오히려 사실과 어긋난다. 호스트와 모델 두 가지면 상황이 정확히 드러난다.
        "llm_host": _llm_host(),
        "llm_model": settings.OPENAI_MODEL,
        # 읽기 캐시 상태. 이 값이 보이면 "왜 갑자기 느려졌나 / 왜 한도를 넘겼나"를
        # 로그를 뒤지지 않고 바로 판단할 수 있다. hit 대비 miss 가 많으면
        # 캐시가 자꾸 비고 있다는 뜻이고, 그만큼 Firestore 를 읽고 있다는 뜻이다.
        "data_cache": data_service.cache_info(),
        "allowed_origins": settings.ALLOWED_ORIGINS,
    }
