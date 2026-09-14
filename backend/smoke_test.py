"""
로컬 스모크 테스트 - Firebase/OpenAI 없이 API 흐름 전체를 검증한다.

    USE_MEMORY_DB=true python smoke_test.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("USE_MEMORY_DB", "true")
# 자동 시드를 꺼야 한다. 켜져 있으면 서버가 뜰 때 730건이 들어가고,
# 이 테스트가 넣는 730건과 겹쳐 1,460건이 된다. (실제로 겪은 문제)
os.environ["SEED_ON_START"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.models.schemas import DataCreate  # noqa: E402

client = TestClient(app)
fails: list[str] = []


def check(label: str, cond: bool, extra: str = "") -> None:
    print(f"{'✅' if cond else '❌'} {label}{(' — ' + extra) if extra and not cond else ''}")
    if not cond:
        fails.append(label)


with client:
    # 0. health
    r = client.get("/health")
    check("GET /health", r.status_code == 200 and r.json()["status"] == "ok", r.text)

    # 자동 시드가 정말 꺼졌는지 — 켜져 있으면 아래 개수 검사가 전부 틀어진다
    n0 = client.get("/api/data").json()["count"]
    check("자동 시드 꺼짐 확인 (시작 시 0건)", n0 == 0, f"{n0}건이 이미 있음")

    # 1. 시드 데이터 일괄 업로드
    seed = json.loads(Path("data/seed_data.json").read_text(encoding="utf-8"))
    # bulk 는 한 번에 1000건까지 — 큰 요청 하나가 서버를 오래 붙잡지 않도록 건 제한이다.
    # 8,760건이면 9번에 나눠 보낸다.
    CHUNK = 1000
    ok = all(
        client.post("/api/data/bulk", json=seed[i:i + CHUNK]).status_code == 201
        for i in range(0, len(seed), CHUNK)
    )
    check(f"POST /api/data/bulk ({len(seed):,}건, {CHUNK}건씩 {-(-len(seed)//CHUNK)}회)", ok)
    check("bulk 는 1000건 초과를 거부", 
          client.post("/api/data/bulk", json=seed[:1001]).status_code == 400)

    # 2. 목록 조회
    r = client.get("/api/data")
    body = r.json()
    check("GET /api/data", r.status_code == 200 and body["count"] == len(seed), r.text)
    check("데이터 100개 이상 요건", body["count"] >= 100, f"count={body['count']}")
    check("날짜 오름차순 정렬", [i["date"] for i in body["items"]] == sorted(i["date"] for i in body["items"]))
    first_id = body["items"][0]["id"]

    # 3. 요약 (경로 충돌 여부까지 확인)
    r = client.get("/api/data/summary")
    s = r.json()
    check("GET /api/data/summary", r.status_code == 200 and s["count"] == len(seed), r.text)
    check("요약에 기간·통계·추세 포함", all(k in s for k in ("period", "metrics", "trend")))
    check("전체 통계(표준편차·월별평균) 포함", s["metrics"]["std_dev"] > 0 and len(s["monthly_average"]) > 0)
    print(f"   └ {s['period']} / 평균 {s['metrics']['average']:,.0f}원 / {s['trend']}")

    # --- 품목별 두 축 + 판정
    check("품목이 여러 개로 분석됨", s["item_count"] >= 2, f"item_count={s['item_count']}")
    check("품목 목록이 평년 대비 낮은 순", 
          [i["vs_normal_pct"] for i in s["items"]] ==
          sorted(i["vs_normal_pct"] for i in s["items"]))

    first = s["items"][0]
    check("품목마다 장기 축(평년 대비)", first["vs_normal_pct"] is not None)
    check("품목마다 단기 축(전주 대비)", first["change_rate_pct"] is not None)
    check("두 축이 서로 다른 값", first["vs_normal_pct"] != first["change_rate_pct"])
    check("품목마다 판정·이유", bool(first["verdict"]) and len(first["verdict_reason"]) > 20)
    check("표에 쓸 짧은 판정 있음", bool(first["verdict_short"]))
    check("짧은 판정이 문장형보다 짧거나 같음",
          all(len(i["verdict_short"]) <= len(i["verdict"]) for i in s["items"]))
    check("품목마다 제철(최저가) 달 계산", all(i["cheapest_month"] for i in s["items"]))

    check("전체 판정 5단계 중 하나", s["verdict"] in
          ("지금 사세요", "사도 좋습니다", "평년 수준", "조금 비쌉니다", "미루는 편이 낫습니다"), s["verdict"])
    check("전체 판정은 품목 중앙값 기반", s["vs_normal_median_pct"] is not None)
    check("사기 좋은/미룰 품목 분류", isinstance(s["buy_now"], list) and isinstance(s["avoid"], list))
    check("장바구니 합계 계산됨", s["basket"]["recent_avg"] is not None)
    check("평년 산출 근거를 밝힘", "평균" in s["normal_basis"] or "불가" in s["normal_basis"])
    check("측정 대상(subject) 포함", bool(s["subject"]) and bool(s["subject_detail"]))
    print(f"   └ {s['item_count']}품목 · 전체 {s['verdict']} (중앙값 {s['vs_normal_median_pct']:+.1f}%)")
    print(f"   └ 사기 좋음: {', '.join(s['buy_now']) or '없음'} / 미룰 것: {', '.join(s['avoid']) or '없음'}")
    print(f"   └ 예: {first['item']} {first['recent_avg']:,.0f}원 "
          f"평년 {first['vs_normal_pct']:+.0f}% 전주 {first['change_rate_pct']:+.0f}% → {first['verdict_short']}")

    # --- 판정 밴드 경계값 단위 테스트
    from app.services.summary_service import _verdict
    band_cases = [(-20, "지금 사세요"), (-12, "지금 사세요"), (-11.9, "사도 좋습니다"),
                  (-4, "사도 좋습니다"), (0, "평년 수준"), (4.9, "평년 수준"),
                  (5, "평년 수준"), (5.1, "조금 비쌉니다"), (12, "조금 비쌉니다"),
                  (12.1, "미루는 편이 낫습니다"), (None, "판단 불가")]
    bad = [(v, _verdict(v)[0], want) for v, want in band_cases if _verdict(v)[0] != want]
    check(f"판정 밴드 경계 {len(band_cases)}개 케이스", not bad, str(bad))

    # --- 시스템 프롬프트
    from app.services.summary_service import build_system_prompt
    prompt = build_system_prompt(s)
    check("프롬프트에 품목별 표 포함", all(i["item"] in prompt for i in s["items"]))
    check("프롬프트에 전체 판정 포함", s["verdict"] in prompt)
    check("프롬프트에 '사기 좋은 품목' 안내", "지금 사기 좋은 품목" in prompt)
    check("프롬프트에 판정 뒤집기 금지 규칙", "뒤집" in prompt)
    check("프롬프트에 '전체 평균으로 얼버무리지 말라' 규칙", "얼버무리지" in prompt)

    # --- 읽기 캐시 (Firestore 무료 한도 대응)
    from app.services import data_service
    before = data_service.cache_info()
    data_service.list_data(); data_service.list_data()
    after = data_service.cache_info()
    check("반복 조회가 캐시에 적중", after["hit"] > before["hit"], str(after))
    data_service.create_data(DataCreate(date="2026-09-08", value=1234, memo="배추"))
    check("쓰기 후 캐시 무효화", data_service.cache_info()["cached"] is False)
    n_after = client.get("/api/data").json()["count"]
    check("쓰기가 즉시 조회에 반영", n_after == len(seed) + 1, f"{n_after} vs {len(seed)+1}")
    # 방금 넣은 것 되돌리기
    added = [i for i in client.get("/api/data?limit=5").json()["items"] if i["value"] == 1234]
    client.delete(f"/api/data/{added[0]['id']}")

    # --- 구간 E: 확장 통계 + 내보내기 (보너스 ②)
    r = client.get("/api/data/statistics?window=90")
    st = r.json()
    check("GET /api/data/statistics", r.status_code == 200 and st["count"] == 90, r.text[:120])
    check("이동평균 7·30일 포함", all(k in st["series"][0] for k in ("ma7", "ma30")))
    check("이동평균 앞부분은 None", st["series"][0]["ma7"] is None)
    check("7일째부터 ma7 값이 있음", st["series"][6]["ma7"] is not None)
    check("ma30 은 30일째부터", st["series"][28]["ma30"] is None and st["series"][29]["ma30"] is not None)
    check("요일별 평균 7개", len(st["weekday_average"]) == 7, str(st["weekday_average"]))
    check("사분위 q1<=중앙<=q3", st["distribution"]["q1"] <= st["distribution"]["median"] <= st["distribution"]["q3"])
    check("최장 연속 상승/하락 계산됨", st["runs"]["longest_rise_days"] > 0 and st["runs"]["longest_fall_days"] > 0)
    print(f"   └ 분포 q1={st['distribution']['q1']:,.0f} 중앙={st['distribution']['median']:,.0f} q3={st['distribution']['q3']:,.0f}")
    print(f"   └ 최장 상승 {st['runs']['longest_rise_days']}일 / 최장 하락 {st['runs']['longest_fall_days']}일")

    r = client.get("/api/data/export?format=csv")
    check("GET /api/data/export?format=csv", r.status_code == 200, r.text[:80])
    check("CSV 에 BOM 있음 (엑셀 한글 깨짐 방지)", r.content.startswith(b"\xef\xbb\xbf"),
          str(r.content[:6]))
    check("CSV 헤더가 date,value,memo", r.content.decode("utf-8-sig").splitlines()[0] == "date,value,memo")
    check("CSV 줄 수 = 데이터 + 헤더",
          len(r.content.decode("utf-8-sig").strip().splitlines()) == len(seed) + 1)
    check("첨부파일 이름 지정됨", "attachment" in r.headers.get("content-disposition", ""))

    r = client.get("/api/data/export?format=json")
    check("GET /api/data/export?format=json", r.status_code == 200 and len(r.json()) == len(seed))
    check("잘못된 format -> 422", client.get("/api/data/export?format=xml").status_code == 422)

    # 경로 순서 — 이 셋이 {data_id} 로 먹히면 전부 404 가 된다
    for p in ("summary", "statistics", "export"):
        check(f"/api/data/{p} 가 경로 변수에 안 먹힘", client.get(f"/api/data/{p}").status_code == 200)

    # 4. 생성
    r = client.post("/api/data", json={"date": "2026-09-08", "value": 5100, "memo": "전어"})
    check("POST /api/data", r.status_code == 201, r.text)
    new_id = r.json()["id"]

    # 5. 검증 실패 케이스 (Pydantic)
    r = client.post("/api/data", json={"date": "날짜아님", "value": -5})
    check("잘못된 입력 -> 422", r.status_code == 422, f"got {r.status_code}")

    # 6. 수정
    r = client.put(f"/api/data/{new_id}", json={"value": 5300, "memo": "전어(수정)"})
    check("PUT /api/data/{id}", r.status_code == 200 and r.json()["value"] == 5300, r.text)

    # 7. 삭제
    r = client.delete(f"/api/data/{new_id}")
    check("DELETE /api/data/{id}", r.status_code == 200, r.text)
    check("삭제 후 404", client.get(f"/api/data/{new_id}").status_code == 404)

    # 8. 대화 저장 / 목록 / 단건 / 삭제
    r = client.post(
        "/api/conversations",
        json={"messages": [
            {"role": "user", "content": "요즘 값이 어때?"},
            {"role": "assistant", "content": "최근 7일 평균은 4,900원/kg 입니다."},
        ]},
    )
    check("POST /api/conversations", r.status_code == 201, r.text)
    conv_id = r.json()["id"]

    r = client.get("/api/conversations")
    check("GET /api/conversations", r.status_code == 200 and r.json()["count"] == 1, r.text)
    check("목록에 messages 미포함", "messages" not in r.json()["items"][0])

    r = client.get(f"/api/conversations/{conv_id}")
    check("GET /api/conversations/{id} (불러오기)", r.status_code == 200 and len(r.json()["messages"]) == 2, r.text)

    # 9. 보너스: 도구 스키마 + 실제 실행
    r = client.get("/api/tools")
    # 개수를 못 박으면 도구를 늘릴 때마다 여기가 깨진다. 개수 대신 '스키마와
    # 구현이 일치하는가'를 아래 13번에서 검사한다.
    check("GET /api/tools (도구 스키마)",
          r.status_code == 200 and r.json()["count"] >= 6
          and all("parameters" in t for t in r.json()["tools"]), r.text[:160])

    from app.services.tools import run_tool
    res = run_tool("find_extreme", {"mode": "min", "item": "배추", "start": "2026-06-01", "end": "2026-06-30"})
    check("도구 실행: find_extreme (품목 지정)", res.get("found") is True, str(res))
    print(f"   └ 배추 6월 최저 {res.get('value'):,.0f}원/kg ({res.get('date')})")
    check("모르는 품목 -> found=False",
          run_tool("find_extreme", {"mode": "min", "item": "없는것"}).get("found") is False)

    res = run_tool("get_item_verdict", {"item": "배추"})
    check("도구 실행: get_item_verdict", res.get("found") is True and res.get("item") == "배추", str(res)[:150])
    check("품목 판정에 두 축이 함께 옴",
          res.get("vs_normal_pct") is not None and res.get("change_rate_pct") is not None)
    print(f"   └ 배추 판정: {res.get('verdict')} (평년 {res.get('vs_normal_pct'):+.0f}%)")

    res = run_tool("query_data", {"start": "2026-09-01", "limit": 5})
    check("도구 실행: query_data", res["count"] > 0, str(res))
    res = run_tool("get_data_summary", {})
    check("도구 실행: get_data_summary", res["count"] >= 100)
    res = run_tool("list_past_conversations", {})
    check("도구 실행: list_past_conversations", res["count"] == 1)
    check("알 수 없는 도구 -> 에러 반환", "error" in run_tool("없는도구", {}))

    # --- 구간 C: 대체재 도구
    res = run_tool("suggest_alternative", {"item": "배추"})
    check("도구 실행: suggest_alternative(배추)", res.get("found") is True, str(res)[:200])
    check("대체재에 조리 이유가 붙음", all(a.get("why") for a in res["alternatives"]))
    priced = [a for a in res["alternatives"] if "avg_price" in a]
    check("기록에 있는 대체재는 값 비교까지", len(priced) > 0,
          "표의 대체재가 데이터 memo 에 하나도 없음")
    if priced:
        p = priced[0]
        print(f"   └ 배추 → {p['item']}: {p['why'][:34]}…")
        print(f"      {p.get('price_note', '')}")

    res = run_tool("suggest_alternative", {"item": "없는품목xyz"})
    check("모르는 품목 -> 지어내지 않고 found=False", res.get("found") is False)
    check("모르는 품목에도 데이터 기반 대안은 제시", "cheapest_in_data" in res)
    check("빈 품목명 처리", run_tool("suggest_alternative", {"item": "  "}).get("found") is False)

    # 도메인 지식(표)과 사실(데이터)을 섞지 않았는지 — 표에는 '원' 단위 가격이 없어야 한다
    from app.services.alternatives import ALT_TABLE
    # "시원하다" 같은 낱말에 걸리지 않도록 '숫자 + 원' 형태만 잡는다
    import re as _re
    _price_pat = _re.compile(r"\d[\d,]*\s*원")
    with_price = [f"{k}->{alt}" for k, v in ALT_TABLE.items()
                  for alt, why in v if _price_pat.search(why)]
    check("대체재 표에 가격이 섞여 있지 않음", not with_price, str(with_price[:3]))
    check("대체재 표 품목 수 30개 이상", len(ALT_TABLE) >= 30, str(len(ALT_TABLE)))

    # 데이터의 memo 품목 중 대체재 표가 없는 것 = GPT 가 답을 못 하는 구멍
    memos = {i["memo"] for i in client.get("/api/data").json()["items"] if i["memo"]}
    uncovered = sorted(memos - set(ALT_TABLE))
    check(f"데이터의 품목 {len(memos)}개가 모두 대체재 표에 있음", not uncovered, str(uncovered))

    # 12. 분류 · 평가 · SWOT · 예측 · 추천 (이번에 늘린 화면들)
    r = client.get("/api/data/categories")
    cat = r.json()
    check("GET /api/data/categories", r.status_code == 200 and cat["count"] > 0, r.text[:120])
    check("분류가 3단(대·중·소)으로 옴",
          all("children" in m and "children" in m["children"][0]
              and "items" in m["children"][0]["children"][0] for m in cat["tree"]))
    tree_items = {n for m in cat["tree"] for x in m["children"]
                  for y in x["children"] for n in y["items"]}
    check("분류 나무의 품목 = 데이터의 품목", tree_items == memos,
          str(sorted(tree_items ^ memos))[:120])
    check("손잡이 어휘(조리법·목적) 제공",
          bool(cat["vocabulary"]["prep"]) and bool(cat["vocabulary"]["purpose"]))

    r = client.get("/api/data/scores")
    sc = r.json()
    check("GET /api/data/scores", r.status_code == 200 and sc["count"] > 0, r.text[:120])
    one = sc["items"][0]
    check("평가 축 6개", len(one["axes"]) == 6, str(len(one["axes"])))
    check("모든 축이 0~100", all(0 <= a["value"] <= 100 for a in one["axes"]))
    srcs = {a["source"] for a in one["axes"]}
    check("측정값과 참고값을 구분해 표시", srcs == {"measured", "reference"}, str(srcs))
    check("측정 축은 계절성·가격·신선도",
          {a["label"] for a in one["axes"] if a["source"] == "measured"}
          == {"계절성", "가격", "신선도"})

    r = client.get("/api/data/swot")
    sw = r.json()
    check("GET /api/data/swot", r.status_code == 200, r.text[:120])
    check("SWOT 네 칸이 모두 있음",
          all(k in sw for k in ("strength", "weakness", "opportunity", "threat")))
    rows = [x for k in ("strength", "weakness", "opportunity", "threat") for x in sw[k]]
    check("SWOT 항목마다 근거가 붙음", rows and all(len(x["why"]) > 4 for x in rows))
    check("SWOT 항목이 실제 품목만 가리킴", all(x["item"] in memos for x in rows))

    r = client.get("/api/data/monthly")
    mo = r.json()
    check("GET /api/data/monthly", r.status_code == 200 and mo["count"] > 0, r.text[:120])
    check("히트맵 값은 연평균 대비(%) — 절대 가격이 아님",
          all(abs(v) < 200 for d in mo["relative"].values() for v in d.values()))

    item0 = sorted(memos)[0]
    r = client.get(f"/api/data/forecast?item={item0}&days=60")
    fc = r.json()
    check(f"GET /api/data/forecast ({item0})", r.status_code == 200 and fc["ok"], r.text[:160])
    check("예측 60일치", len(fc["forecast"]) == 60, str(len(fc["forecast"])))
    check("예측마다 불확실성 띠(low<=value<=high)",
          all(p["low"] <= p["value"] <= p["high"] for p in fc["forecast"]))
    check("띠가 갈수록 넓어짐",
          (fc["forecast"][-1]["high"] - fc["forecast"][-1]["low"])
          > (fc["forecast"][0]["high"] - fc["forecast"][0]["low"]))
    check("계산 방법과 한계를 밝힘",
          len(fc["method"]) > 20 and "반영되지 않" in fc["caveat"])

    # 가정값은 실제 데이터가 아니다 — 넣은 만큼만, 민감도 비율대로 움직여야 한다
    base = fc["forecast"][0]["value"]
    r2 = client.get(f"/api/data/forecast?item={item0}&days=60&weather=20")
    fc2 = r2.json()
    check("가정값을 넣으면 예측선이 올라감", fc2["forecast"][0]["value"] > base,
          f"{base} -> {fc2['forecast'][0]['value']}")
    check("가정 없는 기본 호출은 조정 0%", fc["adjust_pct"] == 0, str(fc["adjust_pct"]))
    check("응답이 어떤 가정을 썼는지 되돌려줌",
          fc2["assumptions"]["weather_pct"] == 20, str(fc2["assumptions"]))

    r = client.post("/api/recommend", json={"prep": ["국·찌개"], "season_weight": 0.9})
    rec = r.json()
    check("POST /api/recommend", r.status_code == 200 and rec["ok"], r.text[:160])
    check("추천이 1가지 이상", len(rec["dishes"]) > 0)
    check("고른 조리법이 1위에 반영됨", rec["dishes"][0]["prep"] == "국·찌개",
          rec["dishes"][0]["prep"])
    d0 = rec["dishes"][0]
    check("추천마다 이유가 붙음", len(d0["why"]) > 4, d0["why"])
    known = [i for i in d0["ingredients"] if i["known"]]
    check("재료에 지금 값과 판정이 붙음",
          known and all(i["recent_avg"] is not None and i["verdict_short"] for i in known))
    check("합계는 아는 재료의 합",
          abs(d0["cost"] - round(sum(i["recent_avg"] for i in known))) <= 1,
          f"{d0['cost']} vs {sum(i['recent_avg'] for i in known):.0f}")

    r = client.post("/api/recommend", json={"purpose": ["없는목적"]})
    check("모르는 조건에도 500 이 아니라 결과를 돌려줌", r.status_code == 200, r.text[:120])

    # 13. 도구 스키마와 구현이 어긋나지 않는가
    #     스키마만 늘리고 구현을 빠뜨리면 GPT 가 부른 뒤에야 실패한다 — 토큰을 쓴 뒤다.
    from app.services.tools import TOOL_IMPLS, TOOL_SPECS
    spec_names = {t["name"] for t in TOOL_SPECS}
    check(f"도구 {len(spec_names)}종의 스키마 ↔ 구현 일치",
          spec_names == set(TOOL_IMPLS), str(spec_names ^ set(TOOL_IMPLS)))
    check("도구마다 호출 근거(description) 있음",
          all(len(t["description"]) > 20 for t in TOOL_SPECS))
    check("판단이 필요한 도구가 섞여 있음",
          {"suggest_alternative", "get_swot_analysis", "recommend_dishes"} <= spec_names)

    from app.services import tools as _tools
    out = _tools.run_tool("get_price_forecast", {"item": item0, "days": 30})
    check("도구: get_price_forecast 는 caveat 를 함께 돌려줌",
          out.get("ok") and "caveat" in out, str(out)[:120])
    out = _tools.run_tool("get_item_scores", {"item": "이런품목없음"})
    check("도구: 모르는 품목이면 아는 품목 목록을 안내",
          out["found"] is False and out["known_items"], str(out)[:120])
    out = _tools.run_tool("browse_by_category", {})
    check("도구: 인자 없이 부르면 분류 목록", bool(out.get("categories")), str(out)[:120])

    # 14. 프롬프트가 '계산을 예언처럼 말하지 말라'고 지시하는가
    check("프롬프트에 예측 단정 금지 규칙", "예언이 아니라" in prompt)
    check("프롬프트에 참고값 구분 규칙", "참고값" in prompt)

    r = client.delete(f"/api/conversations/{conv_id}")
    check("DELETE /api/conversations/{id}", r.status_code == 200, r.text)

    # 10. OpenAI 키 없이 /api/chat -> 503 (친절한 안내)
    r = client.post("/api/chat", json={"message": "테스트"})
    check("POST /api/chat (키 없음) -> 503", r.status_code == 503, f"got {r.status_code}: {r.text[:120]}")

    # 11. Swagger 문서
    r = client.get("/openapi.json")
    paths = r.json()["paths"]
    required = [
        "/api/data", "/api/data/{data_id}", "/api/data/summary",
        "/api/conversations", "/api/conversations/{conversation_id}", "/api/chat",
        "/api/data/categories", "/api/data/scores", "/api/data/swot",
        "/api/data/forecast", "/api/recommend",
    ]
    check("Swagger 문서에 필수 엔드포인트 전부 등록", all(p in paths for p in required),
          str([p for p in required if p not in paths]))

print()
if fails:
    print(f"❌ 실패 {len(fails)}건: {fails}")
    sys.exit(1)
print("🎉 전체 통과")
