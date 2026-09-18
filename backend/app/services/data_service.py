"""
데이터 도메인 로직 (Firestore CRUD).

라우터는 HTTP 관심사만 담당하고, Firestore 를 직접 만지는 코드는 전부 여기 모은다.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Optional

from ..db import DATA_COLLECTION, get_db, utc_now_iso
from ..models.schemas import DataCreate, DataUpdate


class DataNotFound(Exception):
    """해당 id 의 데이터가 없을 때"""


# ---------------------------------------------------------------- 읽기 캐시
#
# 왜 필요한가
#   품목별 데이터로 바꾸면서 레코드가 8,760건이 됐다. 화면 한 번 여는 데
#   summary / 목록 / statistics 세 번을 호출하므로 26,000건을 읽는다.
#   Firestore 무료 한도가 하루 50,000 읽기라 두 번만 새로고침해도 한도에 닿는다.
#
# 무엇을 캐시하나
#   컬렉션 전체를 한 덩어리로. 이 서비스의 조회는 거의 전부 "전체를 읽어
#   앱에서 걸러내기" 형태라, 통째로 들고 있는 편이 단순하고 정확하다.
#
# 언제 버리나
#   ① TTL 이 지나면  ② 쓰기(추가·수정·삭제)가 일어나면 즉시.
#   ②가 없으면 데이터를 고쳐도 화면이 안 바뀌어서, 캐시가 버그처럼 보인다.
#
# TTL 을 왜 6시간으로 두나
#   처음에는 5분이었는데 그것으로는 모자랐다. 원본은 일별 가격이라 하루에 한 번
#   바뀌는데, 5분마다 다시 읽으면 하루 최대 288회 × 8,760건 = 250만 건이 된다.
#   게다가 캐시는 프로세스 메모리에 있어서 재배포·절전 복귀 때마다 비므로,
#   실제로는 그보다 더 자주 읽는다. 실제로 하루 한도 50,000건을 넘겨
#   Firestore 가 429 를 돌려줬고, 그러면 AI 응답까지 함께 막힌다.
#
#   6시간이면 하루 4회 + 재시작 몇 번 = 수만 건이 아니라 수천 건으로 끝난다.
#   '얼마나 최신이어야 하는가'를 데이터의 갱신 주기에 맞춘 것이지,
#   숫자를 크게 잡아 문제를 덮은 것이 아니다.
#   쓰기가 나면 ②로 즉시 버리므로, 값을 고쳤을 때 6시간 기다릴 일은 없다.
CACHE_TTL_SEC = int(os.getenv("DATA_CACHE_TTL_SEC", "21600"))

_cache: list[dict[str, Any]] | None = None
_cache_at: float = 0.0
_cache_lock = threading.Lock()
_cache_stats = {"hit": 0, "miss": 0}


def invalidate_cache() -> None:
    """쓰기가 일어나면 호출. 다음 조회 때 Firestore 에서 다시 읽는다."""
    global _cache
    with _cache_lock:
        _cache = None


def cache_info() -> dict[str, Any]:
    age = time.time() - _cache_at if _cache is not None else None
    return {
        "cached": _cache is not None,
        "records": len(_cache) if _cache is not None else 0,
        "age_sec": round(age, 1) if age is not None else None,
        "ttl_sec": CACHE_TTL_SEC,
        **_cache_stats,
    }


def _all_rows() -> list[dict[str, Any]]:
    """컬렉션 전체를 (캐시를 거쳐) 날짜 오름차순으로 돌려준다."""
    global _cache, _cache_at

    with _cache_lock:
        if _cache is not None and (time.time() - _cache_at) < CACHE_TTL_SEC:
            _cache_stats["hit"] += 1
            return _cache

    db = get_db()
    rows = [_to_out(d.id, d.to_dict()) for d in db.collection(DATA_COLLECTION).stream()]
    rows.sort(key=lambda x: (x["date"], x["memo"], x["id"]))

    with _cache_lock:
        _cache = rows
        _cache_at = time.time()
        _cache_stats["miss"] += 1
    return rows


def _to_out(doc_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": doc_id,
        "date": str(raw.get("date", "")),
        "value": float(raw.get("value", 0)),
        "memo": raw.get("memo", "") or "",
        "created_at": raw.get("created_at"),
        "updated_at": raw.get("updated_at"),
    }


def list_data(
    limit: Optional[int] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    item: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    조회 후 (날짜, 품목) 오름차순. 기간·품목·개수로 거를 수 있다.

    item 을 주면 그 품목만 돌려준다. 품목별 판정이 이 필터 위에서 돈다.
    """
    items = _all_rows()

    if start:
        items = [i for i in items if i["date"] >= start]
    if end:
        items = [i for i in items if i["date"] <= end]
    if item:
        items = [i for i in items if i["memo"] == item]

    if limit is not None and limit > 0:
        items = items[-limit:]
    return items


def list_item_names() -> list[str]:
    """기록에 등장하는 품목 이름 목록."""
    return sorted({i["memo"] for i in _all_rows() if i["memo"]})


def get_data(doc_id: str) -> dict[str, Any]:
    db = get_db()
    snap = db.collection(DATA_COLLECTION).document(doc_id).get()
    if not snap.exists:
        raise DataNotFound(doc_id)
    return _to_out(snap.id, snap.to_dict())


def create_data(payload: DataCreate) -> dict[str, Any]:
    db = get_db()
    now = utc_now_iso()
    body = {
        "date": payload.date.isoformat(),
        "value": float(payload.value),
        "memo": payload.memo,
        "created_at": now,
        "updated_at": now,
    }
    _, doc = db.collection(DATA_COLLECTION).add(body)
    invalidate_cache()
    return _to_out(doc.id, body)


def create_many(payloads: list[DataCreate]) -> int:
    """시드 업로드용 일괄 생성. 캐시는 마지막에 한 번만 버린다."""
    for p in payloads:
        create_data(p)
    invalidate_cache()
    return len(payloads)


def update_data(doc_id: str, payload: DataUpdate) -> dict[str, Any]:
    db = get_db()
    ref = db.collection(DATA_COLLECTION).document(doc_id)
    snap = ref.get()
    if not snap.exists:
        raise DataNotFound(doc_id)

    patch: dict[str, Any] = {}
    if payload.date is not None:
        patch["date"] = payload.date.isoformat()
    if payload.value is not None:
        patch["value"] = float(payload.value)
    if payload.memo is not None:
        patch["memo"] = payload.memo

    if not patch:
        return _to_out(snap.id, snap.to_dict())

    patch["updated_at"] = utc_now_iso()
    ref.update(patch)
    invalidate_cache()

    merged = snap.to_dict()
    merged.update(patch)
    return _to_out(doc_id, merged)


def delete_data(doc_id: str) -> None:
    db = get_db()
    ref = db.collection(DATA_COLLECTION).document(doc_id)
    if not ref.get().exists:
        raise DataNotFound(doc_id)
    ref.delete()
    invalidate_cache()
