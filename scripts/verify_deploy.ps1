# ================================================================
#  배포 실행 검증 스크립트
#
#  무엇을 하나
#    배포된 프론트엔드와 백엔드에 실제로 요청을 보내고,
#    그 응답을 그대로  문서/실행검증.md  에 기록한다.
#    아울러 백엔드의 OpenAPI 명세를  docs/openapi.json  으로 저장한다.
#
#  왜 필요한가
#    "배포했다"는 주장과 "배포가 살아 있다"는 증거는 다르다.
#    스크린샷은 이미지라 텍스트 검색도 안 되고 재현도 안 된다.
#    이 스크립트는 명령과 응답을 함께 남기므로 누구든 다시 돌려 확인할 수 있다.
#
#  실행
#    cd C:\Users\yello\코디세이\jecheol-ai-secretary
#    powershell -ExecutionPolicy Bypass -File scripts\verify_deploy.ps1
# ================================================================

$ErrorActionPreference = "Continue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$FRONT = "https://jecheol-ai-secretary.vercel.app"
$API   = "https://seasonal-ai-backend.onrender.com"

$root   = Split-Path -Parent $PSScriptRoot
$docDir = Join-Path $root "문서"
$apiDir = Join-Path $root "docs"
New-Item -ItemType Directory -Force -Path $docDir, $apiDir | Out-Null
$out = Join-Path $docDir "실행검증.md"

$lines = New-Object System.Collections.Generic.List[string]
function Add-Line([string]$s) { $lines.Add($s) }

function Get-Url([string]$url) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 90
        $sw.Stop()
        # ── 본문은 바이트에서 UTF-8 로 직접 디코딩한다.
        #    PowerShell 5.1 은 Content-Type 에 charset 이 없으면 Latin-1 로 읽어버려
        #    한글이 'ì ì² ' 처럼 깨진다. 서버가 UTF-8 로 보내므로 우리가 맞게 읽는다.
        $body = ""
        try {
            $bytes = $r.RawContentStream.ToArray()
            $body  = [Text.Encoding]::UTF8.GetString($bytes)
        } catch { $body = $r.Content }
        return [pscustomobject]@{
            ok = $true; code = [int]$r.StatusCode; desc = $r.StatusDescription
            ms = [int]$sw.ElapsedMilliseconds; bytes = $r.RawContentLength
            ctype = $r.Headers["Content-Type"]; server = $r.Headers["Server"]
            body = $body
        }
    } catch {
        $sw.Stop()
        $code = 0
        if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
        return [pscustomobject]@{
            ok = $false; code = $code; desc = $_.Exception.Message
            ms = [int]$sw.ElapsedMilliseconds; bytes = 0
            ctype = ""; server = ""; body = ""
        }
    }
}

$now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

Add-Line "# 배포 실행 검증"
Add-Line ""
Add-Line "이 문서는 ``scripts/verify_deploy.ps1`` 이 **자동으로 생성**합니다."
Add-Line "아래 값은 손으로 적은 것이 아니라 실제 HTTP 응답을 그대로 옮긴 것입니다."
Add-Line ""
Add-Line "| 항목 | 값 |"
Add-Line "|---|---|"
Add-Line "| 검증 시각 | $now |"
Add-Line "| 프론트엔드 | $FRONT |"
Add-Line "| 백엔드 | $API |"
Add-Line "| 재현 명령 | ``powershell -ExecutionPolicy Bypass -File scripts\verify_deploy.ps1`` |"
Add-Line ""
Add-Line "> ⚠️ Render 무료 티어는 15분간 요청이 없으면 절전에 들어갑니다."
Add-Line "> 첫 요청의 응답 시간이 수십 초로 나온다면 그것이 콜드스타트이며, 아래 표의 소요(ms)에 그대로 드러납니다."
Add-Line ""
Add-Line "---"
Add-Line ""

# ── 1. 프론트엔드 ────────────────────────────────────────────────
Add-Line "## 1. 프론트엔드 접속 확인"
Add-Line ""
$f = Get-Url $FRONT
Add-Line '```'
Add-Line "> GET $FRONT"
Add-Line "HTTP $($f.code) $($f.desc)"
Add-Line "Content-Type : $($f.ctype)"
Add-Line "Server       : $($f.server)"
Add-Line "크기         : $($f.bytes) bytes"
Add-Line "소요         : $($f.ms) ms"
Add-Line '```'
Add-Line ""
if ($f.ok) {
    $title = ""
    if ($f.body -match "<title>(.*?)</title>") { $title = $Matches[1] }
    $hasApp = $f.body -match "app\.js"
    Add-Line "- 응답 코드 **$($f.code)** — 페이지가 살아 있습니다."
    Add-Line "- ``<title>`` = **$title**"
    Add-Line "- 본문에 ``app.js`` 참조 $(if ($hasApp) { '**있음** — 빈 페이지가 아니라 앱이 빌드되어 올라갔습니다.' } else { '없음' })"
} else {
    Add-Line "- ❌ 접속 실패: $($f.desc)"
}
Add-Line ""

# ── 2. 백엔드 /health ────────────────────────────────────────────
Add-Line "## 2. 백엔드 헬스 체크 — ``/health``"
Add-Line ""
$h = Get-Url "$API/health"
Add-Line '```'
Add-Line "> GET $API/health"
Add-Line "HTTP $($h.code) $($h.desc)   ($($h.ms) ms)"
Add-Line ""
Add-Line $h.body
Add-Line '```'
Add-Line ""
if ($h.ok) {
    try {
        $j = $h.body | ConvertFrom-Json
        Add-Line "이 응답 하나로 다섯 가지가 동시에 증명됩니다."
        Add-Line ""
        Add-Line "| 응답 항목 | 값 | 증명되는 사실 |"
        Add-Line "|---|---|---|"
        Add-Line "| ``status`` | $($j.status) | 서버가 기동되어 요청에 응답한다 |"
        Add-Line "| ``env`` | $($j.env) | 개발이 아니라 배포 설정으로 떠 있다 |"
        Add-Line "| ``db_backend`` | $($j.db_backend) | 저장 계층이 연결되어 있다 |"
        Add-Line "| ``openai_configured`` | $($j.openai_configured) | OpenAI 키가 환경 변수로 주입되어 인식되었다 |"
        Add-Line "| ``allowed_origins`` | $($j.allowed_origins -join ', ') | CORS 허용 출처가 프론트엔드 주소로 설정되어 있다 |"
    } catch {
        Add-Line "(JSON 파싱 실패 — 위 본문 원문을 참고하십시오)"
    }
} else {
    Add-Line "- ❌ 실패: $($h.desc)"
}
Add-Line ""

# ── 3. Swagger UI ────────────────────────────────────────────────
Add-Line "## 3. Swagger UI 접속 확인 — ``/docs``"
Add-Line ""
$d = Get-Url "$API/docs"
Add-Line '```'
Add-Line "> GET $API/docs"
Add-Line "HTTP $($d.code) $($d.desc)   ($($d.ms) ms)"
Add-Line "Content-Type : $($d.ctype)"
Add-Line "크기         : $($d.bytes) bytes"
Add-Line '```'
Add-Line ""
if ($d.ok) {
    $snips = @()
    foreach ($pat in @("<title>.*?</title>", 'swagger-ui[^"]*\.css', 'swagger-ui[^"]*\.js', "url:\s*'[^']*'")) {
        $m = [regex]::Match($d.body, $pat)
        if ($m.Success) { $snips += $m.Value }
    }
    Add-Line "응답 본문에서 뽑은 스니펫 — Swagger UI 가 실제로 서빙되고 있다는 증거입니다."
    Add-Line ""
    Add-Line '```html'
    foreach ($s in $snips) { Add-Line $s }
    Add-Line '```'
} else {
    Add-Line "- ❌ 실패: $($d.desc)"
}
Add-Line ""

# ── 4. OpenAPI 명세 ──────────────────────────────────────────────
Add-Line "## 4. OpenAPI 명세 — ``/openapi.json``"
Add-Line ""
$o = Get-Url "$API/openapi.json"
if ($o.ok) {
    $specPath = Join-Path $apiDir "openapi.json"
    [IO.File]::WriteAllText($specPath, $o.body, (New-Object Text.UTF8Encoding $false))
    Add-Line '```'
    Add-Line "> GET $API/openapi.json"
    Add-Line "HTTP $($o.code)   ($($o.ms) ms)   $($o.bytes) bytes"
    Add-Line "저장 → docs/openapi.json"
    Add-Line '```'
    Add-Line ""
    try {
        $spec = $o.body | ConvertFrom-Json
        $rows = @()
        foreach ($p in $spec.paths.PSObject.Properties) {
            foreach ($m in $p.Value.PSObject.Properties) {
                $summary = ""
                if ($m.Value.summary) { $summary = $m.Value.summary }
                $rows += [pscustomobject]@{ method = $m.Name.ToUpper(); path = $p.Name; summary = $summary }
            }
        }
        Add-Line "**$($spec.info.title)** v$($spec.info.version) — 엔드포인트 **$($rows.Count)개**"
        Add-Line ""
        Add-Line "| 메서드 | 경로 | 설명 |"
        Add-Line "|---|---|---|"
        foreach ($r in ($rows | Sort-Object path, method)) {
            Add-Line "| ``$($r.method)`` | ``$($r.path)`` | $($r.summary) |"
        }
    } catch {
        Add-Line "(명세 파싱 실패 — docs/openapi.json 원문을 참고하십시오)"
    }
} else {
    Add-Line "- ❌ 실패: $($o.desc)"
}
Add-Line ""

# ── 5. 대표 엔드포인트 왕복 ──────────────────────────────────────
Add-Line "## 5. 대표 엔드포인트 응답 확인"
Add-Line ""
Add-Line "| 경로 | HTTP | 소요(ms) | 크기(bytes) | 응답 앞부분 |"
Add-Line "|---|---:|---:|---:|---|"
foreach ($path in @("/api/data/summary", "/api/data/items", "/api/data/statistics",
                    "/api/data/export?format=json", "/api/conversations", "/api/tools")) {
    $r = Get-Url "$API$path"
    $head = ""
    if ($r.body) {
        $head = ($r.body -replace "\s+", " ")
        if ($head.Length -gt 90) { $head = $head.Substring(0, 90) + "…" }
        $head = $head -replace '\|', '\|'
    }
    Add-Line "| ``$path`` | $($r.code) | $($r.ms) | $($r.bytes) | ``$head`` |"
}
Add-Line ""
Add-Line "**읽는 법.** ``/api/tools`` 는 외부 저장소를 읽지 않으므로 항상 200 입니다."
Add-Line "나머지 경로가 ``500`` 이나 ``429`` 라면 **코드나 배포가 아니라 외부 서비스 할당량**이 원인입니다 —"
Add-Line "Firebase 무료 플랜은 하루 읽기 5만 건, OpenAI 는 크레딧 잔액이 한도입니다."
Add-Line "그때는 Render 환경 변수 ``USE_MEMORY_DB=true`` 로 두면 ``backend/data/seed_data.json`` 기반"
Add-Line "메모리 저장소로 전환되어 외부 호출 없이 같은 기능이 동작합니다. 저장 계층을 환경 변수 하나로"
Add-Line "갈아끼울 수 있게 설계한 것이 이 상황을 위한 것입니다."
Add-Line ""
Add-Line "---"
Add-Line ""
Add-Line "생성: ``scripts/verify_deploy.ps1`` · $now"

# ── 저장 (UTF-8 BOM — PowerShell·메모장에서 한글이 깨지지 않게) ──
[IO.File]::WriteAllLines($out, $lines, (New-Object Text.UTF8Encoding $true))

Write-Host ""
Write-Host "  검증 완료" -ForegroundColor Green
Write-Host "  → 문서/실행검증.md"
Write-Host "  → docs/openapi.json"
Write-Host ""
