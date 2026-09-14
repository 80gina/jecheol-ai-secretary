"""
Firestore 연결 담당 모듈.

- 서비스 계정 키는 환경 변수에서만 읽는다 (코드/저장소에 하드코딩 금지).
- USE_MEMORY_DB=true 이면 Firestore 대신 메모리 저장소를 사용한다.
  (Firebase 설정 전에 API 흐름을 먼저 확인하기 위한 개발용 장치)

컬렉션 구조
    data          : 시계열 분석 데이터   {date, value, memo, created_at, updated_at}
    conversations : 대화 기록           {title, messages[], created_at}
"""

from __future__ import annotations

import os

import base64
import binascii
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import settings

# 컬렉션 이름을 환경 변수로 뺀 이유 —
# Firestore 무료 요금제는 **삭제도 쓰기로 센다.** 기존 3만 건을 지우고 2만 건을
# 새로 올리면 5만 3천 쓰기가 되어 하루 한도(2만)를 훌쩍 넘는다.
# 지우는 대신 **새 컬렉션에 담으면** 쓰기가 업로드 몫만 남는다.
# 옛 컬렉션은 그냥 두었다가 나중에 콘솔에서 지우면 된다 (저장 용량은 1GB 무료).
DATA_COLLECTION = os.getenv("DATA_COLLECTION", "data").strip() or "data"
CONVERSATIONS_COLLECTION = "conversations"


# --------------------------------------------------------------------------
# 메모리 저장소 (개발용 대체 구현) - Firestore 클라이언트와 같은 모양으로 흉내낸다
# --------------------------------------------------------------------------
class _MemoryDocument:
    def __init__(self, store: dict[str, dict], doc_id: str) -> None:
        self._store = store
        self.id = doc_id

    def get(self) -> "_MemorySnapshot":
        return _MemorySnapshot(self.id, self._store.get(self.id))

    def set(self, payload: dict[str, Any]) -> None:
        self._store[self.id] = dict(payload)

    def update(self, payload: dict[str, Any]) -> None:
        if self.id not in self._store:
            raise KeyError(self.id)
        self._store[self.id].update(payload)

    def delete(self) -> None:
        self._store.pop(self.id, None)


class _MemorySnapshot:
    def __init__(self, doc_id: str, data: dict | None) -> None:
        self.id = doc_id
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data or {})


class _MemoryCollection:
    def __init__(self, store: dict[str, dict]) -> None:
        self._store = store
        self._lock = threading.Lock()

    def document(self, doc_id: str | None = None) -> _MemoryDocument:
        return _MemoryDocument(self._store, doc_id or uuid.uuid4().hex[:20])

    def add(self, payload: dict[str, Any]) -> tuple[Any, _MemoryDocument]:
        with self._lock:
            doc = self.document()
            doc.set(payload)
        return None, doc

    def stream(self):
        for doc_id, data in list(self._store.items()):
            yield _MemorySnapshot(doc_id, data)


class _MemoryClient:
    def __init__(self) -> None:
        self._collections: dict[str, dict[str, dict]] = {}

    def collection(self, name: str) -> _MemoryCollection:
        self._collections.setdefault(name, {})
        return _MemoryCollection(self._collections[name])


# --------------------------------------------------------------------------
# 초기화
# --------------------------------------------------------------------------
_client: Any = None
_backend: str = "uninitialized"


def _load_credentials():
    """환경 변수에서 서비스 계정 자격증명을 만들어 반환한다."""
    from firebase_admin import credentials

    if settings.FIREBASE_SERVICE_ACCOUNT_B64:
        try:
            raw = base64.b64decode(settings.FIREBASE_SERVICE_ACCOUNT_B64).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise RuntimeError(
                "FIREBASE_SERVICE_ACCOUNT_B64 를 base64 로 디코딩하지 못했습니다."
            ) from exc
        return credentials.Certificate(json.loads(raw))

    if settings.FIREBASE_SERVICE_ACCOUNT_JSON:
        return credentials.Certificate(json.loads(settings.FIREBASE_SERVICE_ACCOUNT_JSON))

    if settings.GOOGLE_APPLICATION_CREDENTIALS:
        return credentials.Certificate(settings.GOOGLE_APPLICATION_CREDENTIALS)

    # 마지막 수단 — backend/serviceAccountKey.json 이 그냥 놓여 있으면 그것을 쓴다.
    #
    # 왜 이 폴백이 필요한가
    #   환경 변수만 보게 해두면, 키 파일을 제자리에 잘 두고도 .env 에 경로 한 줄을
    #   안 적었다는 이유로 "자격증명이 없습니다" 가 뜬다. 실제로 그렇게 막혔다.
    #   로컬에서는 파일이 놓인 것 자체가 의도의 표현이므로 그대로 받아들인다.
    #   (배포 환경에는 이 파일이 없고 FIREBASE_SERVICE_ACCOUNT_B64 를 쓰므로 영향 없다)
    default_key = Path(__file__).resolve().parents[1] / "serviceAccountKey.json"
    if default_key.exists():
        return credentials.Certificate(str(default_key))

    raise RuntimeError(
        "Firebase 자격증명을 찾지 못했습니다.\n"
        "  다음 중 하나면 됩니다 —\n"
        f"  1) 키 파일을 여기에 두기: {default_key}\n"
        "  2) .env 에 GOOGLE_APPLICATION_CREDENTIALS=./serviceAccountKey.json\n"
        "  3) 배포 환경이라면 FIREBASE_SERVICE_ACCOUNT_B64 환경 변수\n"
        "  (Firebase 없이 돌려보려면 .env 에서 USE_MEMORY_DB=true)"
    )


def init_db() -> str:
    """앱 시작 시 1회 호출. 사용 중인 백엔드 이름을 돌려준다."""
    global _client, _backend

    if _client is not None:
        return _backend

    if settings.USE_MEMORY_DB:
        _client = _MemoryClient()
        _backend = "memory"
        return _backend

    import firebase_admin
    from firebase_admin import firestore

    if not firebase_admin._apps:
        firebase_admin.initialize_app(_load_credentials())
    _client = firestore.client()
    _backend = "firestore"
    return _backend


def get_db():
    if _client is None:
        init_db()
    return _client


def get_backend() -> str:
    return _backend


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
