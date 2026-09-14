"""
jecheol-planner 가 수집한 KAMIS 실측 가격을 이 과제의 seed_data.json 으로 바꾼다.

전제
    ../jecheol-planner 에서 아래를 먼저 돌려 CSV 가 있어야 한다.
        python main.py codes
        python main.py collect --years 2
        python main.py analyze          # (선택) prices_clean.csv 가 생긴다

    prices_clean.csv 가 있으면 그것을, 없으면 prices_raw.csv 를 쓴다.
    두 파일 모두 컬럼은 date, key, item, kind, category, role, price 다.

무엇으로 바꾸나
    KAMIS 는 '품목별' 가격을 준다. 이 과제의 데이터는 '하루 한 줄'이어야 하므로
    9개 품목을 하나의 숫자로 합쳐야 한다. 합치는 방식은 두 가지를 둔다.

        basket (기본) : 그날 9품목 가격의 합계 = "제철 밥상 한 상 재료비(원)"
                        품목마다 단위가 달라도(1포기 / 1kg / 100g) 더하는 것은 말이 된다.
        avg           : 단순 평균. 단위가 섞여 있으면 의미가 흐려지므로,
                        collect 를 kg 환산(convert_kg=Y)으로 돌렸을 때만 쓴다.

    memo 에는 그날 '가장 싼 품목'의 이름을 넣는다. 나중에 AI 가
    "지금은 무가 싸니 무생채를 해보세요" 같은 답을 할 근거가 된다.

결측 처리
    수집이 빠진 날이 3일 이하로 연속되면 앞뒤 값으로 선형 보간한다.
    (jecheol-planner/analyze.py 의 GAP_FILL_MAX 와 같은 기준)
    4일 이상 비면 메우지 않고 빼며, 몇 건을 뺐는지 보고한다.

사용법:
    python scripts/import_kamis.py
    python scripts/import_kamis.py --mode avg
    python scripts/import_kamis.py --planner ../../jecheol-planner
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

GAP_FILL_MAX = 3  # analyze.py 와 같은 기준


def find_source(planner_dir: Path) -> Path:
    for name in ("prices_clean.csv", "prices_raw.csv"):
        p = planner_dir / "data" / name
        if p.exists():
            return p
    raise SystemExit(
        f"{planner_dir / 'data'} 에 prices_clean.csv 도 prices_raw.csv 도 없습니다.\n"
        "  jecheol-planner 폴더에서 먼저 실행하세요:\n"
        "    python main.py codes\n"
        "    python main.py collect --years 2"
    )


def load_rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit(f"{path.name} 이 비어 있습니다. collect 가 실제로 데이터를 받았는지 확인하세요.")
    need = {"date", "item", "price"}
    missing = need - set(rows[0])
    if missing:
        raise SystemExit(f"{path.name} 에 필요한 컬럼이 없습니다: {sorted(missing)}")
    return rows


def to_daily(rows: list[dict], mode: str) -> list[dict]:
    """품목별 여러 줄 -> 하루 한 줄."""
    by_date: dict[str, list[tuple[str, float]]] = defaultdict(list)
    skipped = 0
    for r in rows:
        d = (r.get("date") or "").strip()[:10]
        try:
            price = float(str(r.get("price", "")).replace(",", ""))
        except ValueError:
            skipped += 1
            continue
        if not d or price <= 0:
            skipped += 1
            continue
        by_date[d].append((r.get("item", "").strip() or r.get("key", ""), price))

    if skipped:
        print(f"  · 값이 없거나 0 이하인 {skipped}행은 건너뛰었습니다.")

    daily = []
    for d in sorted(by_date):
        pairs = by_date[d]
        prices = [p for _, p in pairs]
        value = sum(prices) if mode == "basket" else sum(prices) / len(prices)
        cheapest = min(pairs, key=lambda x: x[1])[0]
        daily.append({"date": d, "value": round(value), "memo": cheapest, "_n": len(pairs)})
    return daily


def fill_gaps(daily: list[dict]) -> tuple[list[dict], int, int]:
    """3일 이하 결측은 선형 보간, 그보다 길면 그대로 둔다."""
    if not daily:
        return [], 0, 0

    have = {d["date"]: d for d in daily}
    start = date.fromisoformat(daily[0]["date"])
    end = date.fromisoformat(daily[-1]["date"])

    out: list[dict] = []
    filled = long_gaps = 0
    cur = start
    while cur <= end:
        key = cur.isoformat()
        if key in have:
            out.append(have[key])
            cur += timedelta(days=1)
            continue

        # 빈 구간의 길이를 잰다
        gap = []
        probe = cur
        while probe <= end and probe.isoformat() not in have:
            gap.append(probe)
            probe += timedelta(days=1)

        prev_rec = out[-1] if out else None
        next_rec = have.get(probe.isoformat())

        if prev_rec and next_rec and len(gap) <= GAP_FILL_MAX:
            step = (next_rec["value"] - prev_rec["value"]) / (len(gap) + 1)
            for i, g in enumerate(gap, 1):
                out.append({
                    "date": g.isoformat(),
                    "value": round(prev_rec["value"] + step * i),
                    "memo": prev_rec["memo"],
                    "_filled": True,
                })
            filled += len(gap)
        else:
            long_gaps += len(gap)

        cur = probe

    return out, filled, long_gaps


def main() -> None:
    parser = argparse.ArgumentParser(description="KAMIS 실측 데이터를 seed_data.json 으로 변환")
    parser.add_argument("--planner", default="../jecheol-planner",
                        help="jecheol-planner 폴더 경로 (기본: ../jecheol-planner)")
    parser.add_argument("--mode", default="basket", choices=["basket", "avg"],
                        help="basket=9품목 합계(기본), avg=단순 평균(kg 환산 수집일 때만)")
    parser.add_argument("--out", default="data/seed_data.json")
    args = parser.parse_args()

    planner = Path(args.planner).resolve()
    src = find_source(planner)
    print(f"원본: {src}")

    rows = load_rows(src)
    print(f"  · 원본 {len(rows):,}행")

    daily = to_daily(rows, args.mode)
    print(f"  · 하루 한 줄로 합침 -> {len(daily):,}일 (방식: {args.mode})")

    counts = {d["_n"] for d in daily}
    if len(counts) > 1:
        print(f"  ⚠️ 날마다 품목 수가 다릅니다({min(counts)}~{max(counts)}개). "
              f"합계 방식은 품목 수가 같아야 공정합니다 — --mode avg 를 고려하세요.")

    daily, filled, long_gaps = fill_gaps(daily)
    if filled:
        print(f"  · 3일 이하 결측 {filled}일을 앞뒤 값으로 보간했습니다.")
    if long_gaps:
        print(f"  ⚠️ 4일 이상 이어진 결측 {long_gaps}일은 메우지 않고 뺐습니다.")

    records = [{"date": d["date"], "value": float(d["value"]), "memo": d["memo"]} for d in daily]

    if len(records) < 100:
        print(f"\n❌ {len(records)}건뿐입니다. 과제 요건은 100건 이상입니다.")
        print("   collect --years 2 로 다시 수집하거나, 생성 데이터를 쓰세요.")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    values = [r["value"] for r in records]
    print(f"\n변환 완료: {len(records):,}건 -> {out}")
    if records:
        print(f"  기간     : {records[0]['date']} ~ {records[-1]['date']}")
        print(f"  평균     : {sum(values) / len(values):,.0f}원")
        print(f"  최고/최저: {max(values):,.0f} / {min(values):,.0f}원")
    print("\n다음: python scripts/seed_firestore.py --wipe")


if __name__ == "__main__":
    main()
