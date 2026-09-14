"""환경 변수 로딩 - 키는 절대 코드에 하드코딩하지 않는다."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _split_origins(raw: str) -> list[str]:
    return [o.strip() for o in raw.split(",") if o.strip()]


class Settings:
    """앱 전역 설정. 모든 값은 환경 변수에서만 읽는다."""

    # --- OpenAI ---
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    # 과금 방지: 응답 토큰 상한을 반드시 둔다
    OPENAI_MAX_TOKENS: int = int(os.getenv("OPENAI_MAX_TOKENS", "600"))

    # --- Firebase ---
    # 아래 셋 중 하나만 있으면 된다 (우선순위 순)
    #   1) FIREBASE_SERVICE_ACCOUNT_B64  : 서비스 계정 JSON 을 base64 로 인코딩한 문자열 (배포용 권장)
    #   2) FIREBASE_SERVICE_ACCOUNT_JSON : 서비스 계정 JSON 원문 문자열
    #   3) GOOGLE_APPLICATION_CREDENTIALS: 키 파일 경로 (로컬 개발용)
    FIREBASE_SERVICE_ACCOUNT_B64: str = os.getenv("FIREBASE_SERVICE_ACCOUNT_B64", "")
    FIREBASE_SERVICE_ACCOUNT_JSON: str = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "")
    GOOGLE_APPLICATION_CREDENTIALS: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")

    # --- CORS ---
    # 프론트(Vercel)와 백엔드(Render)가 서로 다른 도메인이므로 반드시 필요하다.
    ALLOWED_ORIGINS: list[str] = _split_origins(
        os.getenv("ALLOWED_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500")
    )

    # --- 개발 편의 ---
    # true 이면 Firestore 대신 메모리 저장소를 쓴다. Firebase 설정 전에 API 흐름만
    # 먼저 확인할 때 사용하며, 제출/배포 시에는 반드시 false 여야 한다.
    USE_MEMORY_DB: bool = os.getenv("USE_MEMORY_DB", "false").lower() == "true"

    # 서버가 뜰 때 데이터가 비어 있으면 data/seed_data.json 을 자동으로 넣을지.
    #   auto (기본) : 메모리 모드일 때만 넣는다 (끌 때마다 비워지므로)
    #   true        : Firestore 를 써도 넣는다
    #   false       : 절대 넣지 않는다  ← 테스트가 이 값을 쓴다.
    #                 끄는 수단이 없으면 테스트가 직접 넣은 데이터와 겹쳐 두 배가 된다.
    SEED_ON_START: str = os.getenv("SEED_ON_START", "auto").lower()

    def should_autoseed(self) -> bool:
        if self.SEED_ON_START == "false":
            return False
        if self.SEED_ON_START == "true":
            return True
        return self.USE_MEMORY_DB  # auto

    APP_ENV: str = os.getenv("APP_ENV", "local")


settings = Settings()
