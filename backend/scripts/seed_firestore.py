"""
생성한 시드 데이터를 Firestore 에 업로드한다.

사용법 (backend 폴더에서):
    python scripts/generate_data.py                       # 1) 데이터 생성
    python scripts/seed_firestore.py --collection data2   # 2) 새 컬렉션에 업로드
    python scripts/seed_firestore.py --resume             # 3) 끊겼으면 이어서

── 무료 요금제의 벽: 삭제도 '쓰기'다 ─────────────────────────
    Firestore Spark(무료) 요금제의 하루 한도는 **쓰기 2만 건**이다.
    그리고 삭제는 읽기가 아니라 **쓰기로 계산된다.**

        기존 33,580건 삭제  +  신규 19,710건 업로드  =  53,290 쓰기
                                                        ↑ 하루 한도의 2.7배

    그래서 --wipe 로 갈아끼우려다 절반쯤에서 429 Quota exceeded 로 막힌다.
    (실제로 겪었다)

    해결은 **지우지 않는 것**이다. 새 컬렉션에 담으면 쓰기는 업로드 몫만 남는다.
    옛 컬렉션은 그대로 두었다가 나중에 Firebase 콘솔에서 지우면 된다 —
    콘솔 삭제는 이 스크립트의 하루 한도와 무관하고, 저장 용량은 1GB 까지 무료다.

── 문서 ID 를 날짜+품목으로 정하는 이유 ──────────────────────
    자동 생성 ID 를 쓰면 같은 스크립트를 두 번 돌렸을 때 전부 중복이 된다.
    "2026-09-07__배추" 처럼 내용에서 ID 를 만들면 두 번 올려도 덮어쓰기라
    개수가 늘지 않는다. 중간에 끊겨서 다시 돌려도 안전하다.

── 끊겼을 때 이어서 올리기 ───────────────────────────────────
    한도에 걸리면 어디까지 올렸는지 .seed_progress 에 적고 멈춘다.
    다음 날 --resume 을 붙이면 그 다음부터 이어서 올린다.
    (Firestore 를 다시 읽어 확인하지 않는다 — 그것도 읽기 한도를 쓰기 때문)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db as db_module  # noqa: E402
from app.db import get_db, init_db, utc_now_iso  # noqa: E402

BATCH_LIMIT = 500          # Firestore 배치 1회 최대 작업 수
DAILY_WRITE_LIMIT = 20_000  # Spark(무료) 요금제 하루 쓰기 한도
PROGRESS_FILE = Path("data/.seed_progress")


class QuotaExceeded(Exception):
    """하루 쓰기 한도에 걸림 — 오류가 아니라 '오늘은 여기까지'라는 뜻"""


def doc_id(record: dict) -> str:
    """날짜 + 품목으로 ID 를 만든다. 두 번 올려도 덮어쓰기가 되도록."""
    memo = (record.get("memo") or "전체").replace("/", "_")
    return f"{record['date']}__{memo}"


def is_quota_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}"
    return "429" in text or "Quota exceeded" in text or "ResourceExhausted" in text


def upload(db, records: list[dict], collection: str, start_at: int = 0) -> int:
    """start_at 번째부터 올린다. 한도에 걸리면 QuotaExceeded 를 올린다."""
    now = utc_now_iso()
    total = len(records)
    done = start_at
    started = time.time()

    for i in range(start_at, total, BATCH_LIMIT):
        chunk = records[i:i + BATCH_LIMIT]
        batch = db.batch()
        for r in chunk:
            ref = db.collection(collection).document(doc_id(r))
            batch.set(ref, {
                "date": r["date"],
                "value": float(r["value"]),
                "memo": r.get("memo", ""),
                "created_at": now,
                "updated_at": now,
            })

        try:
            batch.commit()
        except Exception as exc:  # noqa: BLE001
            if is_quota_error(exc):
                PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
                PROGRESS_FILE.write_text(
                    json.dumps({"collection": collection, "done": done}),
                    encoding="utf-8")
                raise QuotaExceeded(done) from exc
            raise

        done += len(chunk)
        pct = done / total * 100
        elapsed = time.time() - started
        print(f"  업로드 {done:,}/{total:,} ({pct:.0f}%)  {elapsed:.0f}초", flush=True)

    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()
    return done


def main() -> None:
    parser = argparse.ArgumentParser(
        description="시드 데이터를 Firestore 에 업로드 (무료 한도를 넘지 않게)")
    parser.add_argument("--file", default="data/seed_data.json")
    parser.add_argument("--collection", default=None,
                        help="담을 컬렉션 이름. 새 이름을 주면 기존 것을 지울 필요가 없다")
    parser.add_argument("--resume", action="store_true",
                        help="한도에 걸려 멈춘 지점부터 이어서 올린다")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        raise SystemExit(f"{path} 가 없습니다. 먼저 generate_data.py 를 실행하세요.")

    backend = init_db()
    print(f"DB 백엔드: {backend}")
    if backend == "memory":
        raise SystemExit(
            "USE_MEMORY_DB=true 상태입니다. 메모리 저장소는 프로세스가 끝나면 사라지므로 "
            "시드 업로드가 의미가 없습니다. .env 에서 USE_MEMORY_DB=false 로 바꾸세요."
        )

    db = get_db()
    records = json.loads(path.read_text(encoding="utf-8"))

    start_at = 0
    collection = args.collection or db_module.DATA_COLLECTION

    if args.resume and PROGRESS_FILE.exists():
        saved = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        collection = args.collection or saved["collection"]
        start_at = saved["done"]
        print(f"이어서 올립니다: '{collection}' 컬렉션의 {start_at:,}번째부터")

    remaining = len(records) - start_at
    print(f"\n대상 컬렉션 : {collection}")
    print(f"올릴 건수   : {remaining:,}건  (= 쓰기 {remaining:,}회)")
    if remaining > DAILY_WRITE_LIMIT:
        print(f"\n⚠️  무료 요금제 하루 쓰기 한도는 {DAILY_WRITE_LIMIT:,}건입니다.")
        print("    오늘 한도까지만 올라가고 멈춥니다. 내일 --resume 으로 이어서 올리세요.")
        print("    한 번에 끝내려면 generate_data.py --profile 로 품목을 줄이세요.\n")

    started = time.time()
    try:
        uploaded = upload(db, records, collection, start_at)
    except QuotaExceeded as e:
        done = e.args[0]
        print(f"\n⏸  오늘 쓰기 한도에 걸려 {done:,}건까지 올리고 멈췄습니다.")
        print("    이건 고장이 아니라 무료 요금제의 하루 한도입니다.")
        print("    한도는 태평양 시간 자정(한국 시간 오후 4~5시)에 초기화됩니다.")
        print("\n    이어서 올리려면:")
        print("      python scripts/seed_firestore.py --resume")
        raise SystemExit(1)

    elapsed = time.time() - started
    print(f"\n완료: {uploaded:,}건을 '{collection}' 컬렉션에 올렸습니다. ({elapsed:.0f}초)")

    if collection != "data":
        print("\n📌 앱이 이 컬렉션을 보게 하려면 backend/.env 에 한 줄 추가하세요:")
        print(f"      DATA_COLLECTION={collection}")

    print("\n다음 단계:")
    print("  uvicorn app.main:app --reload")


if __name__ == "__main__":
    main()
