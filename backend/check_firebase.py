"""
Firebase 연결 점검 — 키를 넣은 뒤 이것부터 돌린다.

    python check_firebase.py

왜 따로 만들었나
    Firebase 연결은 실패하는 방식이 여러 가지인데, 서버를 그냥 띄우면
    "DB 초기화 실패" 한 줄만 나오고 원인을 알 수 없다.
    이 스크립트는 단계별로 끊어 확인하고, 각 실패마다 무엇을 하면 되는지 알려준다.

읽기만 하고 쓰기도 한 번 해본다
    읽기 권한만 있고 쓰기가 막힌 경우가 실제로 흔하다.
    그래서 임시 문서를 하나 썼다가 지운다. 기존 데이터는 건드리지 않는다.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
OK, NG, WARN = "  ✅", "  ❌", "  ⚠️ "


def fail(msg: str, *how: str) -> None:
    print(f"{NG} {msg}")
    for line in how:
        print(f"     → {line}")
    print("\n점검 중단. 위 내용을 해결한 뒤 다시 실행하세요.")
    sys.exit(1)


print("\nFirebase 연결 점검")
print("=" * 46)

# ── 1. .env -----------------------------------------------------------------
print("\n[1/5] .env 확인")
env_path = BASE / ".env"
if not env_path.exists():
    fail(".env 파일이 없습니다.",
         "시작하기.ps1 을 한 번 실행하면 자동으로 만들어집니다.")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(env_path)

use_memory = os.getenv("USE_MEMORY_DB", "false").strip().lower() == "true"
if use_memory:
    print(f"{WARN} USE_MEMORY_DB=true 입니다 — 지금은 Firestore 대신 메모리 저장소를 씁니다.")
    print("     → 실제 Firestore 를 쓰려면 .env 에서 USE_MEMORY_DB=false 로 바꾸세요.")
    print("     → (이 점검은 계속 진행합니다)")
else:
    print(f"{OK} USE_MEMORY_DB=false — Firestore 를 사용합니다.")

# ── 2. 자격증명 찾기 ---------------------------------------------------------
print("\n[2/5] 서비스 계정 키 찾기")
b64 = os.getenv("FIREBASE_SERVICE_ACCOUNT_B64", "").strip()
raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
default_file = BASE / "serviceAccountKey.json"

info = None
source = None

if b64:
    import base64
    try:
        info = json.loads(base64.b64decode(b64).decode("utf-8"))
        source = "FIREBASE_SERVICE_ACCOUNT_B64"
    except Exception as e:
        fail(f"FIREBASE_SERVICE_ACCOUNT_B64 를 해석하지 못했습니다: {e}",
             "base64 문자열이 한 줄로 온전히 들어갔는지 확인하세요.")
elif raw:
    try:
        info = json.loads(raw)
        source = "FIREBASE_SERVICE_ACCOUNT_JSON"
    except json.JSONDecodeError as e:
        fail(f"FIREBASE_SERVICE_ACCOUNT_JSON 이 올바른 JSON 이 아닙니다: {e}",
             "개행이 깨졌을 가능성이 큽니다. base64 방식을 쓰는 편이 안전합니다.")
else:
    target = Path(path) if path else default_file
    if not target.is_absolute():
        target = (BASE / target).resolve()
    if not target.exists():
        fail(f"키 파일을 찾을 수 없습니다: {target}",
             "Firebase 콘솔 → 프로젝트 설정 → 서비스 계정 → 새 비공개 키 생성",
             f"받은 .json 을 '{default_file}' 로 이름을 바꿔 저장하세요.")
    try:
        info = json.loads(target.read_text(encoding="utf-8"))
        source = str(target.name)
    except json.JSONDecodeError as e:
        fail(f"{target.name} 이 올바른 JSON 이 아닙니다: {e}",
             "다운로드가 중간에 끊겼을 수 있습니다. 키를 다시 받아보세요.")

print(f"{OK} 키를 찾았습니다 ({source})")

# ── 3. 키 내용 확인 ----------------------------------------------------------
print("\n[3/5] 키 내용 확인")
need = ["type", "project_id", "private_key", "client_email"]
missing = [k for k in need if not info.get(k)]
if missing:
    fail(f"키에 필요한 항목이 없습니다: {', '.join(missing)}",
         "'서비스 계정' 키가 맞는지 확인하세요. 웹 앱 설정(apiKey…)은 다른 것입니다.")

if info.get("type") != "service_account":
    fail(f"키 종류가 service_account 가 아닙니다 (현재: {info.get('type')})",
         "Firebase 콘솔 → 프로젝트 설정 → **서비스 계정** 탭에서 받은 키여야 합니다.")

print(f"{OK} 형식 정상")
print(f"     프로젝트 : {info['project_id']}")
print(f"     계정     : {info['client_email']}")

# ── 4. 연결 ------------------------------------------------------------------
print("\n[4/5] Firestore 연결")
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except ImportError:
    fail("firebase-admin 패키지가 없습니다.",
         "pip install -r requirements.txt 를 먼저 실행하세요.")

try:
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(info))
    db = firestore.client()
except Exception as e:  # noqa: BLE001
    msg = str(e)
    hints = ["인터넷 연결을 확인하세요."]
    if "invalid_grant" in msg or "JWT" in msg:
        hints = ["컴퓨터 시각이 실제 시각과 크게 다르면 인증이 실패합니다. 시간 동기화를 확인하세요.",
                 "키가 삭제되었을 수도 있습니다. Firebase 콘솔에서 새 키를 받아보세요."]
    fail(f"Firestore 클라이언트를 만들지 못했습니다: {msg[:200]}", *hints)

print(f"{OK} 클라이언트 생성 성공")

# 앱과 같은 경로로도 되는지 확인.
#   이 점검만 통과하고 앱은 실패하는 상황이 실제로 있었다. 점검 도구가 앱보다
#   관대하면 아무 소용이 없으므로, 앱이 쓰는 init_db() 를 그대로 한 번 호출한다.
if not use_memory:
    try:
        sys.path.insert(0, str(BASE))
        from app.db import init_db  # noqa: E402
        backend_name = init_db()
        if backend_name != "firestore":
            fail(f"앱은 '{backend_name}' 백엔드로 뜹니다 (firestore 가 아님).",
                 ".env 의 USE_MEMORY_DB 를 false 로 바꾸세요.")
        print(f"{OK} 앱과 같은 경로로도 연결됨 (app.db.init_db)")
    except RuntimeError as e:
        fail(f"이 점검은 통과했지만 앱은 키를 못 찾습니다:\n     {e}")

# ── 5. 읽기·쓰기 실제 확인 ---------------------------------------------------
print("\n[5/5] 읽기·쓰기 권한 확인")
try:
    n = sum(1 for _ in db.collection("data").limit(5).stream())
    print(f"{OK} 읽기 성공 (data 컬렉션에서 {n}건 확인)")
except Exception as e:  # noqa: BLE001
    msg = str(e)
    hints = ["Firestore Database 를 아직 만들지 않았을 수 있습니다.",
             "Firebase 콘솔 → 빌드 → Firestore Database → 데이터베이스 만들기"]
    if "PERMISSION_DENIED" in msg:
        hints = ["서비스 계정에 권한이 없습니다. 키를 다시 발급받아 보세요."]
    fail(f"읽기 실패: {msg[:200]}", *hints)

try:
    ref = db.collection("_connection_check").document("probe")
    ref.set({"ok": True})
    ref.delete()
    print(f"{OK} 쓰기 성공 (임시 문서를 만들었다 지웠습니다)")
except Exception as e:  # noqa: BLE001
    fail(f"쓰기 실패: {str(e)[:200]}",
         "읽기는 되는데 쓰기가 안 됩니다. 보안 규칙이나 계정 권한을 확인하세요.")

# ── 결과 ---------------------------------------------------------------------
print("\n" + "=" * 46)
print("  Firestore 연결 정상")
print("=" * 46)

total = sum(1 for _ in db.collection("data").stream())
print(f"\n현재 data 컬렉션: {total}건")
if total == 0:
    print("\n다음 단계 — 데이터를 올리세요:")
    print("  python scripts/seed_firestore.py --wipe")
else:
    print("\n데이터가 이미 있습니다. 새로 올리려면:")
    print("  python scripts/seed_firestore.py --wipe   (기존 삭제 후 재업로드)")

if use_memory:
    print("\n⚠️  .env 의 USE_MEMORY_DB 가 아직 true 입니다.")
    print("   false 로 바꿔야 서버가 실제 Firestore 를 씁니다.")
print()
