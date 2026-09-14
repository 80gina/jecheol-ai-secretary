# =============================================================
#  제철밥상 플래너 AI 비서 — 로컬 실행 (Windows PowerShell)
#
#  쓰는 법: 이 파일을 마우스 오른쪽 클릭 → "PowerShell에서 실행"
#          또는 터미널에서:  .\시작하기.ps1
#
#  하는 일
#    1) backend\.env 가 없으면 만들어 준다 (Firebase 없이 도는 설정)
#    2) 가상환경이 없으면 만들고 패키지를 설치한다
#    3) 백엔드(8000)와 프론트엔드(5500)를 각각 새 창에서 띄운다
#    4) 브라우저를 연다
# =============================================================

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

Write-Host ""
Write-Host "  제철밥상 플래너 AI 비서 — 로컬 실행" -ForegroundColor Green
Write-Host "  ====================================" -ForegroundColor Green
Write-Host ""

# --- 파이썬 확인 -------------------------------------------------
try {
    $pyver = (python --version) 2>&1
    Write-Host "  [1/5] $pyver" -ForegroundColor Gray
} catch {
    Write-Host "  X 파이썬을 찾을 수 없습니다. python.org 에서 설치한 뒤 다시 실행하세요." -ForegroundColor Red
    Read-Host "  엔터를 누르면 닫힙니다"
    exit 1
}

# --- .env 준비 ---------------------------------------------------
$envFile = Join-Path $backend ".env"
if (-not (Test-Path $envFile)) {
@"
# 로컬에서 Firebase 없이 돌리기 위한 최소 설정입니다.
# 실제 Firestore 를 쓰려면 USE_MEMORY_DB 를 false 로 바꾸고
# GOOGLE_APPLICATION_CREDENTIALS 에 서비스 계정 키 경로를 넣으세요.
USE_MEMORY_DB=true
APP_ENV=local
ALLOWED_ORIGINS=http://localhost:5500,http://127.0.0.1:5500

# AI 채팅을 쓰려면 아래에 본인 키를 넣으세요. 비워두면 채팅만 동작하지 않고
# 나머지 화면(요약·판정·데이터 관리)은 전부 정상 동작합니다.
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
OPENAI_MAX_TOKENS=600
"@ | Set-Content -Path $envFile -Encoding UTF8
    Write-Host "  [2/5] backend\.env 를 새로 만들었습니다." -ForegroundColor Yellow
} else {
    Write-Host "  [2/5] backend\.env 확인" -ForegroundColor Gray
}

# --- 가상환경 ----------------------------------------------------
$venvPy = Join-Path $backend "venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "  [3/5] 가상환경을 만드는 중... (1분쯤)" -ForegroundColor Yellow
    python -m venv (Join-Path $backend "venv")
    & $venvPy -m pip install --quiet --upgrade pip
    Write-Host "        패키지를 설치하는 중... (2~3분)" -ForegroundColor Yellow
    & $venvPy -m pip install --quiet -r (Join-Path $backend "requirements.txt")
} else {
    Write-Host "  [3/5] 가상환경 확인" -ForegroundColor Gray
}

# --- 서버 두 개 띄우기 -------------------------------------------
Write-Host "  [4/5] 서버를 켜는 중..." -ForegroundColor Gray

Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$backend'; " +
    "Write-Host '=== 백엔드 (닫지 마세요) ===' -ForegroundColor Green; " +
    "& '$venvPy' -m uvicorn app.main:app --reload --port 8000"
)

Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$frontend'; " +
    "Write-Host '=== 프론트엔드 (닫지 마세요) ===' -ForegroundColor Green; " +
    "python -m http.server 5500"
)

# --- 백엔드가 응답할 때까지 기다렸다가 브라우저 열기 --------------
Write-Host "  [5/5] 백엔드가 준비될 때까지 기다리는 중..." -ForegroundColor Gray
$ready = $false
foreach ($i in 1..30) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2 -UseBasicParsing
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
}

Write-Host ""
if ($ready) {
    Write-Host "  준비 완료" -ForegroundColor Green
    Write-Host "    화면    : http://127.0.0.1:5500" -ForegroundColor White
    Write-Host "    Swagger : http://127.0.0.1:8000/docs" -ForegroundColor White
    Start-Process "http://127.0.0.1:5500"
} else {
    Write-Host "  백엔드가 30초 안에 응답하지 않았습니다." -ForegroundColor Red
    Write-Host "  방금 열린 '백엔드' 창의 빨간 글씨를 확인해 주세요." -ForegroundColor Red
}
Write-Host ""
Write-Host "  끝낼 때는 새로 열린 창 두 개를 닫으면 됩니다." -ForegroundColor Gray
Write-Host ""
Read-Host "  엔터를 누르면 이 창만 닫힙니다"
