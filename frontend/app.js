/* ==========================================================================
   제철밥상 플래너 AI 비서 - 프론트엔드 (바닐라 JS, 프레임워크 없음)
   ========================================================================== */

const API = (window.APP_CONFIG && window.APP_CONFIG.API_BASE_URL) || "http://127.0.0.1:8000";

const state = {
  conversationId: null,
  dataItems: [],
  itemNames: [],
  sending: false,
  summary: null,
  focusItems: [],      // 대화에서 뽑힌 품목 — 시세판 맨 위로 올린다
  focusReason: "",
  sort: "verdict",
};

/* ---------------------------------------------------------------- helpers */
const $ = (id) => document.getElementById(id);
const won = (n) => Number(n).toLocaleString("ko-KR");

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

let toastTimer;
function toast(msg, isError = false) {
  const el = $("toast");
  el.textContent = msg;
  el.style.background = isError ? "#b4483c" : "#22271f";
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 2600);
}

/* --------------------------------------------------- 오류를 한국어로 옮기는 표

   서버가 주는 영어 메시지나 상태 코드를 그대로 화면에 띄우면
   "422 Unprocessable Entity" 같은 글자만 보이고, 사용자는 무엇을 해야 할지
   알 수 없다. 그래서 코드마다 '무슨 일이 있었고 무엇을 하면 되는지'를 적어 둔다.
   과제 요건의 "최소한의 예외 처리"가 가리키는 것이 이 부분이다.                */
const ERR_BY_STATUS = {
  400: "요청 형식이 잘못됐습니다. 입력값을 확인해 주세요.",
  404: "해당 항목을 찾을 수 없습니다. 다른 창에서 이미 지워졌을 수 있습니다.",
  422: "입력값이 올바르지 않습니다. 날짜 형식(YYYY-MM-DD)과 0 이상의 숫자인지 확인해 주세요.",
  429: "요청이 너무 잦습니다. 잠시 뒤 다시 시도해 주세요.",
  500: "서버 안에서 오류가 났습니다. 잠시 뒤 다시 시도해 주세요.",
  502: "AI 응답을 만들지 못했습니다. OpenAI 키가 유효한지, 잔액이 남아 있는지 확인해 주세요.",
  503: "AI 기능이 아직 준비되지 않았습니다. 서버에 OPENAI_API_KEY 를 설정해 주세요.",
  504: "서버 응답이 너무 늦습니다. 무료 서버가 깨어나는 중일 수 있으니 잠시 뒤 다시 시도해 주세요.",
};

const ERR_NETWORK =
  "서버에 연결하지 못했습니다. 셋 중 하나입니다 — ① 백엔드가 꺼져 있음 " +
  "② 무료 서버가 절전에서 깨는 중 ③ 백엔드의 ALLOWED_ORIGINS 에 이 주소가 빠짐(CORS).";

class ApiError extends Error {
  constructor(message, status, raw) {
    super(message);
    this.status = status;
    this.raw = raw;
  }
}

async function api(path, options = {}) {
  let res;
  try {
    res = await fetch(`${API}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch (e) {
    // fetch 자체가 실패 = 네트워크/CORS. 브라우저는 둘을 구분해 알려주지 않는다.
    throw new ApiError(ERR_NETWORK, 0, e.message);
  }

  if (!res.ok) {
    let raw = `${res.status} ${res.statusText}`;
    let serverText = null; // 서버가 사람에게 하는 말일 때만 채운다

    try {
      const body = await res.json();
      if (body.detail !== undefined) {
        raw = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
        // FastAPI 의 검증 실패(422)는 detail 이 '배열'로 온다. 그건 개발자용 구조체이지
        // 사용자에게 보여줄 문장이 아니다. 문자열일 때만 그대로 쓴다.
        // (입력값에 한글이 섞여 있으면 한글 검사만으로는 걸러지지 않는다 — 실제로 겪음)
        if (typeof body.detail === "string") serverText = body.detail;
      }
    } catch (_) { /* 본문이 JSON 이 아닐 수 있다 */ }

    const friendly =
      serverText || ERR_BY_STATUS[res.status] || `요청이 실패했습니다 (${res.status}).`;
    throw new ApiError(friendly, res.status, raw);
  }
  return res.status === 204 ? null : res.json();
}

/* ------------------------------------------------- 콜드스타트 대응 / 헬스체크 */
async function wakeServer() {
  const conn = $("conn");
  const cold = $("coldstart");
  const slowTimer = setTimeout(() => (cold.hidden = false), 2500);

  try {
    const h = await api("/health");
    conn.className = "conn conn--ok";
    conn.textContent = h.openai_configured
      ? `연결됨 · ${h.db_backend}`
      : `연결됨 · OPENAI_API_KEY 미설정`;
  } catch (err) {
    conn.className = "conn conn--err";
    conn.textContent = "서버 연결 실패";
    toast(`백엔드에 연결할 수 없습니다: ${err.message}`, true);
  } finally {
    clearTimeout(slowTimer);
    cold.hidden = true;
  }
}

/* ------------------------------------------------------------ 판정 + 요약 */

/** 평년 대비 %를 0을 가운데 둔 막대로 그린다. ±30%를 양끝으로 본다. */
function meterHtml(pct) {
  if (pct === null || pct === undefined) {
    return `<p class="muted" style="margin-top:12px">평년 비교 자료가 아직 없습니다.</p>`;
  }
  const clamped = Math.max(-30, Math.min(30, pct));
  const left = 50 + (clamped < 0 ? clamped : 0) * (50 / 30);
  const width = Math.abs(clamped) * (50 / 30);
  const color = pct < 0 ? "var(--accent)" : "var(--danger)";
  return `
    <div class="meter">
      <i style="left:${left}%;width:${width}%;background:${color}"></i>
      <span class="zero"></span>
    </div>
    <div class="meter-labels">
      <span>평년보다 쌈</span><span>평년</span><span>평년보다 비쌈</span>
    </div>`;
}

function renderVerdict(s) {
  const box = $("verdictBox");
  if (!s.count) {
    box.innerHTML = `<div class="empty">
      <b>아직 판정할 데이터가 없습니다</b>
      오른쪽 <em>데이터 관리</em>에서 기록을 먼저 추가해 주세요.</div>`;
    return;
  }
  const b = s.basket || {};
  const chips = (arr, cls) =>
    arr.map((n) => `<span class="chip chip--${cls}">${escapeHtml(n)}</span>`).join("");

  box.innerHTML = `
    <div class="subject">
      <b>${escapeHtml(s.subject)}</b>
      <span>${escapeHtml(s.subject_detail)} · ${s.item_count}개 품목</span>
    </div>
    <div class="verdict-head">
      <span class="verdict-label tone-${escapeHtml(s.verdict_tone)}">${escapeHtml(s.verdict)}</span>
      <span class="verdict-price">${s.vs_normal_median_pct > 0 ? "+" : ""}${(s.vs_normal_median_pct ?? 0).toFixed(1)}%</span>
    </div>
    ${meterHtml(s.vs_normal_median_pct)}
    ${s.buy_now.length ? `<div class="pick-row"><span class="pick-label good">지금 사세요</span>${chips(s.buy_now, "good")}</div>` : ""}
    ${s.avoid.length ? `<div class="pick-row"><span class="pick-label bad">미루세요</span>${chips(s.avoid, "bad")}</div>` : ""}
    <p class="verdict-reason">${escapeHtml(s.verdict_reason)}</p>
    <div class="basket-line">
      🧺 ${escapeHtml(b.note || "")} —
      <b>${won(Math.round(b.recent_avg ?? 0))}원</b>
      <span class="${(b.change_rate_pct ?? 0) < 0 ? "tone-good" : "tone-warn"}">
        (전주 대비 ${(b.change_rate_pct ?? 0) > 0 ? "+" : ""}${(b.change_rate_pct ?? 0).toFixed(1)}%)
      </span>
    </div>
    <p class="basis-note">📐 ${escapeHtml(s.normal_basis)}</p>`;
}

/* 품목별 시세판 — 이 서비스의 핵심 화면.
   평균 하나로는 "뭘 사야 하나"에 답할 수 없어서 품목마다 한 줄씩 보여준다. */
const MONTH_KO = ["", "1월", "2월", "3월", "4월", "5월", "6월",
                  "7월", "8월", "9월", "10월", "11월", "12월"];

function boardRowsHtml(items) {
  const pct = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(0)}%`);
  return items.map((i) => `
    <button type="button" class="board-row tone-border-${escapeHtml(i.verdict_tone)}"
            data-item="${escapeHtml(i.item)}" aria-expanded="false">
      <span class="bi-name">${escapeHtml(i.item)}
        <em>제철 ${MONTH_KO[i.cheapest_month] || "—"}</em></span>
      <span class="bi-price">${won(Math.round(i.recent_avg ?? 0))}<em>원/kg</em></span>
      <span class="bi-pct tone-${i.vs_normal_pct == null ? "mid" : i.vs_normal_pct < 0 ? "good" : "warn"}">${pct(i.vs_normal_pct)}<em>평년</em></span>
      <span class="bi-pct tone-${i.change_rate_pct == null ? "mid" : i.change_rate_pct < 0 ? "good" : "warn"}">${pct(i.change_rate_pct)}<em>전주</em></span>
      <span class="bi-verdict tone-${escapeHtml(i.verdict_tone)}">${escapeHtml(i.verdict_short || i.verdict)}</span>
    </button>
    <div class="board-detail" data-detail="${escapeHtml(i.item)}">
      <p>${escapeHtml(i.verdict_reason)}</p>
      <p class="muted">기록 ${won(i.count)}건 · 평균 ${won(Math.round(i.average))}원 ·
         최저 ${won(i.min)}원 ~ 최고 ${won(i.max)}원 ·
         평년 ${i.normal_avg ? won(Math.round(i.normal_avg)) + "원" : "산출 불가"}</p>
      <div class="detail-actions">
        <button type="button" class="btn btn--ghost btn--sm" data-chart="${escapeHtml(i.item)}">📈 그래프</button>
        <button type="button" class="btn btn--ghost btn--sm" data-alt="${escapeHtml(i.item)}">🔄 대체 재료 물어보기</button>
      </div>
    </div>`).join("");
}

function wireBoard(box) {
  box.querySelectorAll("[data-item]").forEach((btn) => {
    btn.onclick = () => {
      const open = btn.getAttribute("aria-expanded") === "true";
      box.querySelectorAll("[data-item]").forEach((b) => b.setAttribute("aria-expanded", "false"));
      box.querySelectorAll(".board-detail").forEach((d) => d.classList.remove("open"));
      if (!open) {
        btn.setAttribute("aria-expanded", "true");
        box.querySelector(`[data-detail="${CSS.escape(btn.dataset.item)}"]`).classList.add("open");
      }
    };
  });
  box.querySelectorAll("[data-chart]").forEach((b) => {
    b.onclick = (e) => { e.stopPropagation(); selectChartItem(b.dataset.chart); };
  });
  box.querySelectorAll("[data-alt]").forEach((b) => {
    b.onclick = (e) => { e.stopPropagation(); askQuick(`${b.dataset.alt}가 비싼데 뭘 대신 쓸까?`); };
  });
}

function sortItems(items) {
  const arr = [...items];
  if (state.sort === "name") return arr.sort((a, b) => a.item.localeCompare(b.item, "ko"));
  if (state.sort === "price") return arr.sort((a, b) => (b.recent_avg ?? 0) - (a.recent_avg ?? 0));
  return arr; // verdict = 서버가 준 순서(평년 대비 낮은 순)
}

/* 대화에서 뽑힌 재료를 맨 위 카드에 따로 보여준다.
   시세판 전체를 재정렬하지 않고 별도 카드로 뽑는 이유 —
   "지금 필요한 것"과 "전체 시세"는 보는 목적이 다르기 때문이다. */
function renderCart() {
  const card = $("cartCard");
  const s = state.summary;
  if (!s || !state.focusItems.length) { card.hidden = true; return; }

  const picked = state.focusItems
    .map((name) => s.items.find((i) => i.item === name))
    .filter(Boolean);
  if (!picked.length) { card.hidden = true; return; }

  card.hidden = false;
  $("cartReason").textContent = state.focusReason
    ? `${state.focusReason} — 이 재료들을 지금 사도 되는지 봤습니다`
    : "대화에 나온 재료입니다";

  const total = picked.reduce((t, i) => t + (i.recent_avg ?? 0), 0);
  const good = picked.filter((i) => i.verdict_tone === "good").map((i) => i.item);
  const bad = picked.filter((i) => i.verdict_tone === "bad").map((i) => i.item);

  const box = $("cartBoard");
  box.innerHTML = `
    <div class="board-head">
      <span>품목</span><span>최근 7일</span><span>평년 대비</span><span>전주</span><span>판정</span>
    </div>
    ${boardRowsHtml(picked)}
    <div class="cart-total">
      <span>${picked.length}가지 1kg씩 합계</span>
      <b>${won(Math.round(total))}원</b>
    </div>
    ${good.length || bad.length ? `<p class="cart-advice">
      ${good.length ? `✅ <b>${escapeHtml(good.join(", "))}</b> 는 지금이 좋습니다.` : ""}
      ${bad.length ? ` ⚠️ <b>${escapeHtml(bad.join(", "))}</b> 는 미루거나 대체를 고려하세요.` : ""}
    </p>` : ""}`;
  wireBoard(box);
}

function renderItemBoard(s) {
  const box = $("itemBoard");
  // 분류 막대에서 고른 갈래만 남긴다 (viz.js 가 관리한다)
  const only = (window.VIZ && catItems(VIZ.cat)) || null;
  const shown = only ? s.items.filter((i) => only.includes(i.item)) : s.items;
  if (!shown.length && only) {
    $("boardTitle").textContent = "🥬 품목별 시세";
    box.innerHTML = `<div class="empty"><b>이 분류에는 데이터가 없습니다</b>
      위에서 '전체'를 눌러 되돌릴 수 있습니다.</div>`;
    return;
  }
  if (!s.items || !s.items.length) {
    box.innerHTML = `<div class="empty"><b>품목 정보가 없습니다</b>
      데이터의 품목 칸에 이름을 넣으면 품목별로 분석합니다.</div>`;
    return;
  }
  $("boardTitle").textContent = only
    ? `🥬 품목별 시세 (${shown.length}개 / 전체 ${s.item_count}개)`
    : `🥬 품목별 시세 (${s.item_count}개)`;
  box.innerHTML = `
    <div class="board-head">
      <span>품목</span><span>최근 7일</span><span>평년 대비</span><span>전주</span><span>판정</span>
    </div>
    ${boardRowsHtml(sortItems(shown))}`;
  wireBoard(box);
}

async function loadSummary() {
  const box = $("summaryBox");
  try {
    const s = await api("/api/data/summary");
    state.summary = s;
    renderVerdict(s);
    renderItemBoard(s);
    renderCart();
    if (window.refreshViz) refreshViz();

    if (!s.count) {
      box.innerHTML = `<div class="empty">
        <b>등록된 데이터가 없습니다</b>
        데이터를 추가하면 여기에 기간·평균·추세가 나타납니다.</div>`;
      CHART.series = [];
      drawChart();
      return;
    }
    const m = s.metrics;
    const dir = s.trend.startsWith("상승") ? "up" : s.trend.startsWith("하락") ? "down" : "";
    const cheap = (s.items || []).slice(0, 3)
      .map((t) => `${escapeHtml(t.item)} ${won(Math.round(t.recent_avg))}`).join(" · ");
    box.innerHTML = `
      <dl>
        <dt>기간</dt><dd>${escapeHtml(s.period)}</dd>
        <dt>레코드</dt><dd>${won(s.count)}개</dd>
        <dt>평균</dt><dd>${won(Math.round(m.average))} ${escapeHtml(s.unit)}</dd>
        <dt>최고</dt><dd>${won(m.max)} (${escapeHtml(s.peak_date)})</dd>
        <dt>최저</dt><dd>${won(m.min)} (${escapeHtml(s.trough_date)})</dd>
        <dt>품목 수</dt><dd>${s.item_count}개</dd>
        <dt>변동성</dt><dd>±${won(Math.round(m.std_dev))}</dd>
      </dl>
      <span class="trend-pill ${dir}">${escapeHtml(s.trend)}</span>
      ${cheap ? `<p class="basis-note">🥬 지금 값이 좋은 품목 — ${cheap}</p>` : ""}`;
  } catch (err) {
    const msg = escapeHtml(err.message);
    box.innerHTML = `<div class="empty"><b>요약을 불러오지 못했습니다</b>${msg}</div>`;
    $("verdictBox").innerHTML = `<div class="empty"><b>판정할 수 없습니다</b>${msg}</div>`;
  }
}

/* ==========================================================================
   차트 — 라이브러리 없이 SVG 로 직접 그린다 (프레임워크 사용 금지 요건)

   canvas 가 아니라 SVG 를 쓰는 이유
     - 화면 크기가 바뀌어도 다시 그릴 필요 없이 선명하다
     - 색을 CSS 변수로 줄 수 있어 다크 모드가 저절로 따라온다
     - 각 점이 요소라서 마우스 위치를 찾기 쉽다
   ========================================================================== */
const CHART = { series: [], show: { value: true, ma7: true, ma30: true }, range: 90, item: null };
const SERIES_DEF = [
  { key: "value", name: "일별", color: "var(--accent)", width: 1.4, opacity: 0.55 },
  { key: "ma7", name: "7일 평균", color: "var(--accent)", width: 2.2, opacity: 1 },
  { key: "ma30", name: "30일 평균", color: "var(--warn)", width: 2, opacity: 1 },
];

function renderLegend() {
  $("legend").innerHTML = SERIES_DEF.map(
    (s) => `<label>
      <input type="checkbox" data-series="${s.key}" ${CHART.show[s.key] ? "checked" : ""}>
      <span class="sw" style="background:${s.color};opacity:${s.opacity}"></span>${s.name}
    </label>`
  ).join("");
  $("legend").querySelectorAll("[data-series]").forEach((el) => {
    el.onchange = () => { CHART.show[el.dataset.series] = el.checked; drawChart(); };
  });
}

function drawChart() {
  const box = $("chart");
  const hist = CHART.series;

  /* 예측이 켜져 있으면 과거 뒤에 이어 붙인다.
     예측 구간은 is_fc 로 표시해 두고, 선을 점선으로 그리고 띠를 깐다.
     같은 굵기의 실선으로 이어 버리면 사용자가 예측을 측정값으로 읽는다. */
  const fc = (window.VIZ && VIZ.forecast && VIZ.forecast.ok) ? VIZ.forecast.forecast : [];
  const rows = fc.length
    ? hist.concat(fc.map((f) => ({ date: f.date, value: f.value, low: f.low, high: f.high, is_fc: true })))
    : hist;

  if (rows.length < 2) {
    box.innerHTML = `<div class="empty"><b>그릴 데이터가 부족합니다</b>최소 2건 이상 필요합니다.</div>`;
    return;
  }

  const W = 620, H = 210, PL = 44, PR = 10, PT = 12, PB = 24;
  const iw = W - PL - PR, ih = H - PT - PB;

  const active = SERIES_DEF.filter((s) => CHART.show[s.key]);
  const nums = rows
    .flatMap((r) => active.map((s) => r[s.key]).concat([r.low, r.high]))
    .filter((v) => v != null);
  if (!nums.length) {
    box.innerHTML = `<div class="empty"><b>표시할 선이 없습니다</b>아래에서 하나 이상 체크해 주세요.</div>`;
    return;
  }
  const lo = Math.min(...nums), hi = Math.max(...nums);
  const pad = (hi - lo) * 0.12 || 100;
  const min = lo - pad, max = hi + pad;

  const x = (i) => PL + (i * iw) / (rows.length - 1);
  const y = (v) => PT + ih - ((v - min) / (max - min)) * ih;

  // y축 눈금 4개
  const ticks = [0, 1, 2, 3].map((k) => min + ((max - min) * k) / 3);
  const grid = ticks
    .map((t) => `<line class="gridline" x1="${PL}" y1="${y(t).toFixed(1)}" x2="${W - PR}" y2="${y(t).toFixed(1)}"/>
      <text class="axis-text" x="${PL - 6}" y="${(y(t) + 3.5).toFixed(1)}" text-anchor="end">${won(Math.round(t))}</text>`)
    .join("");

  // x축 라벨 — 양끝과 가운데만. 촘촘하면 읽을 수 없다.
  const xlab = [0, Math.floor((rows.length - 1) / 2), rows.length - 1]
    .map((i, k) => `<text class="axis-text" x="${x(i).toFixed(1)}" y="${H - 6}"
      text-anchor="${k === 0 ? "start" : k === 2 ? "end" : "middle"}">${rows[i].date.slice(2)}</text>`)
    .join("");

  const paths = active
    .map((s) => {
      let d = "", pen = false;
      rows.forEach((r, i) => {
        // 예측 구간은 아래에서 점선으로 따로 그린다 — 실측선은 여기서 끊는다
        const v = r.is_fc ? null : r[s.key];
        if (v == null) { pen = false; return; }      // 이동평균 앞부분은 값이 없다
        d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
        pen = true;
      });
      return `<path class="series-line" d="${d}" stroke="${s.color}" stroke-width="${s.width}" opacity="${s.opacity}"/>`;
    })
    .join("");

  // 예측: 불확실성 띠 + 점선. 마지막 실측점에서 이어지게 시작점을 하나 겹친다.
  let fcLayer = "";
  if (fc.length) {
    const s0 = hist.length - 1;
    const idx = rows.map((_, i) => i).filter((i) => i >= s0);
    const up = idx.map((i) => `${x(i).toFixed(1)},${y(rows[i].high ?? rows[i].value).toFixed(1)}`);
    const dn = idx.slice().reverse().map((i) => `${x(i).toFixed(1)},${y(rows[i].low ?? rows[i].value).toFixed(1)}`);
    const line = idx.map((i, k) => `${k ? "L" : "M"}${x(i).toFixed(1)},${y(rows[i].value).toFixed(1)}`).join("");
    fcLayer = `
      <polygon class="fc-band" points="${up.concat(dn).join(" ")}"/>
      <line class="fc-split" x1="${x(s0).toFixed(1)}" y1="${PT}" x2="${x(s0).toFixed(1)}" y2="${PT + ih}"/>
      <text class="axis-text fc-tag" x="${(x(s0) + 4).toFixed(1)}" y="${PT + 10}">여기부터 예측</text>
      <path class="fc-line" d="${line}"/>`;
  }

  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img"
      aria-label="가격 추이 선그래프, ${rows[0].date}부터 ${rows[rows.length - 1].date}까지">
    ${grid}${xlab}${fcLayer}${paths}
    <g id="cursor" style="display:none">
      <line class="cursor-line" y1="${PT}" y2="${PT + ih}"/>
      <circle class="cursor-dot" r="3.5"/>
    </g>
    <rect class="hit" x="${PL}" y="${PT}" width="${iw}" height="${ih}"/>
  </svg>`;

  // --- 마우스를 따라다니는 툴팁
  const svg = box.querySelector("svg");
  const hit = box.querySelector(".hit");
  const cursor = box.querySelector("#cursor");
  const tip = $("tip");

  hit.addEventListener("mousemove", (e) => {
    const r = svg.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    const i = Math.max(0, Math.min(rows.length - 1, Math.round(((px - PL) / iw) * (rows.length - 1))));
    const row = rows[i];

    cursor.style.display = "";
    cursor.querySelector("line").setAttribute("x1", x(i));
    cursor.querySelector("line").setAttribute("x2", x(i));
    const dot = cursor.querySelector("circle");
    dot.setAttribute("cx", x(i));
    dot.setAttribute("cy", y(row.value));
    dot.setAttribute("fill", "var(--accent)");

    tip.hidden = false;
    tip.innerHTML =
      `<b>${escapeHtml(row.date)}</b>${row.is_fc ? ' <em class="fc-mark">예측</em>' : ""}<br>` +
      (row.is_fc
        ? `<i style="background:var(--warn)"></i>예상 <b>${won(Math.round(row.value))}</b>` +
          `<br><span class="muted">${won(Math.round(row.low))} ~ ${won(Math.round(row.high))}</span>`
        : "") +
      (row.is_fc ? [] : active)
        .filter((s) => row[s.key] != null)
        .map((s) => `<i style="background:${s.color}"></i>${s.name} <b>${won(Math.round(row[s.key]))}</b>`)
        .join("<br>") +
      (row.memo ? `<br>${escapeHtml(row.memo)}` : "");

    // 오른쪽 끝에서 툴팁이 잘리지 않게 왼쪽으로 넘긴다
    const relX = (x(i) / W) * r.width;
    const flip = relX > r.width - 130;
    tip.style.left = `${flip ? relX - 12 : relX + 12}px`;
    tip.style.transform = flip ? "translateX(-100%)" : "none";
    tip.style.top = `${Math.max(0, (y(row.value) / H) * r.height - 44)}px`;
  });

  hit.addEventListener("mouseleave", () => {
    cursor.style.display = "none";
    tip.hidden = true;
  });
}

function renderStatGrid(st) {
  const d = st.distribution || {};
  const cells = [
    ["1사분위", d.q1], ["중앙값", d.median], ["3사분위", d.q3],
    ["평균", d.mean], ["표준편차", d.std_dev],
  ].map(([k, v]) => `<div><div class="k">${k}</div><div class="v">${v == null ? "—" : won(Math.round(v))}</div></div>`);
  cells.push(
    `<div><div class="k">최장 상승</div><div class="v">${st.runs?.longest_rise_days ?? "—"}일</div></div>`,
    `<div><div class="k">최장 하락</div><div class="v">${st.runs?.longest_fall_days ?? "—"}일</div></div>`
  );
  $("statGrid").innerHTML = cells.join("");
}

/** 그래프에서 볼 품목을 고르는 버튼 줄. '장바구니 합계' + 품목 12개 */
function renderItemPicker() {
  const box = $("itemPicker");
  const only = (window.VIZ && catItems(VIZ.chartCat)) || null;
  const names = only ? state.itemNames.filter((n) => only.includes(n)) : state.itemNames;
  const all = [null, ...names];
  box.innerHTML = all.map((name) => {
    const on = CHART.item === name;
    const label = name === null ? "장바구니 합계" : name;
    return `<button type="button" class="pick-chip" data-pick="${name === null ? "" : escapeHtml(name)}"
              aria-pressed="${on}">${escapeHtml(label)}</button>`;
  }).join("");
  box.querySelectorAll("[data-pick]").forEach((b) => {
    b.onclick = () => selectChartItem(b.dataset.pick || null);
  });
}

function selectChartItem(name) {
  CHART.item = name;
  renderItemPicker();
  $("chartSubject").textContent = `(${name || "장바구니 합계"})`;
  loadChart();
  if (window.renderAlts) renderAlts();          // 대체재는 바로
  if (window.loadForecast) loadForecast();      // 예측은 펼쳐져 있을 때만
  $("itemPicker").scrollIntoView({ behavior: "smooth", block: "center" });
}

async function loadChart() {
  try {
    const qs = new URLSearchParams();
    if (CHART.range > 0) qs.set("window", String(CHART.range));
    if (CHART.item) qs.set("item", CHART.item);
    const st = await api(`/api/data/statistics?${qs}`);
    CHART.series = st.series.map((r) => ({ ...r, memo: st.item }));
    drawChart();
    renderStatGrid(st);
  } catch (err) {
    $("chart").innerHTML = `<div class="empty"><b>그래프를 그리지 못했습니다</b>${escapeHtml(err.message)}</div>`;
    $("statGrid").innerHTML = "";
  }
}

/* ------------------------------------------------------------ 내보내기 */
function exportData(format) {
  // 서버가 Content-Disposition 을 붙여 주므로 링크를 열기만 하면 저장된다.
  const url = `${API}/api/data/export?format=${format}`;
  const a = document.createElement("a");
  a.href = url;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  toast(`${format.toUpperCase()} 파일을 내려받습니다.`);
}

/* ------------------------------------------------------------ 화면 모드 */
function applyTheme(mode) {
  // mode: "light" | "dark" | null(=OS 설정 따라감)
  const root = document.documentElement;
  if (mode) root.setAttribute("data-theme", mode);
  else root.removeAttribute("data-theme");

  const osDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const isDark = mode === "dark" || (!mode && osDark);
  $("themeBtn").textContent = isDark ? "☀️ 밝게" : "🌙 어둡게";

  try { mode ? localStorage.setItem("theme", mode) : localStorage.removeItem("theme"); }
  catch (_) { /* 사생활 보호 모드에서는 저장이 막힐 수 있다 */ }
}

function toggleTheme() {
  const osDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const cur = document.documentElement.getAttribute("data-theme") || (osDark ? "dark" : "light");
  applyTheme(cur === "dark" ? "light" : "dark");
  drawChart(); // 색이 CSS 변수라 다시 그릴 필요는 없지만, 안전하게 한 번 더
}

/* ------------------------------------------------------------ 데이터 CRUD */
async function loadData() {
  const list = $("dataList");
  try {
    const res = await api("/api/data?limit=60");
    state.dataItems = res.items;

    if (!res.items.length) {
      list.innerHTML = `<li><div class="empty" style="width:100%">
        <b>기록이 없습니다</b>위 칸에 날짜와 가격을 넣고 <em>추가</em>를 눌러보세요.</div></li>`;
      return;
    }
    list.innerHTML = res.items
      .slice()
      .reverse()
      .map(
        (it) => `
      <li>
        <div class="row-main">
          <span class="row-date">${escapeHtml(it.date)}</span><br />
          <span class="row-value">${won(it.value)}원/kg</span>
          ${it.memo ? `<span class="row-memo"> · ${escapeHtml(it.memo)}</span>` : ""}
        </div>
        <div class="row-actions">
          <button class="icon-btn" data-edit="${it.id}" title="수정">✏️</button>
          <button class="icon-btn del" data-del="${it.id}" title="삭제">🗑️</button>
        </div>
      </li>`
      )
      .join("");
  } catch (err) {
    list.innerHTML = `<li><div class="empty" style="width:100%">
      <b>목록을 불러오지 못했습니다</b>${escapeHtml(err.message)}</div></li>`;
  }
}

function startEdit(id) {
  const item = state.dataItems.find((i) => i.id === id);
  if (!item) return;
  $("editingId").value = id;
  $("fDate").value = item.date;
  $("fValue").value = item.value;
  $("fMemo").value = item.memo || "";
  $("dataSubmitBtn").textContent = "수정 저장";
  $("cancelEditBtn").hidden = false;
  $("fValue").focus();
}

function cancelEdit() {
  $("dataForm").reset();
  $("editingId").value = "";
  $("dataSubmitBtn").textContent = "추가";
  $("cancelEditBtn").hidden = true;
}

async function submitData(e) {
  e.preventDefault();
  const id = $("editingId").value;
  const payload = {
    date: $("fDate").value,
    value: Number($("fValue").value),
    memo: $("fMemo").value.trim(),
  };
  if (!payload.date || Number.isNaN(payload.value) || payload.value < 0) {
    return toast("날짜와 0 이상의 가격을 입력하세요.", true);
  }

  try {
    if (id) {
      await api(`/api/data/${id}`, { method: "PUT", body: JSON.stringify(payload) });
      toast("수정했습니다.");
    } else {
      await api("/api/data", { method: "POST", body: JSON.stringify(payload) });
      toast("추가했습니다.");
    }
    cancelEdit();
    await refreshAll();
  } catch (err) {
    toast(`저장 실패: ${err.message}`, true);
  }
}

async function deleteData(id) {
  if (!confirm("이 기록을 삭제할까요?")) return;
  try {
    await api(`/api/data/${id}`, { method: "DELETE" });
    toast("삭제했습니다.");
    if ($("editingId").value === id) cancelEdit();
    await refreshAll();
  } catch (err) {
    toast(`삭제 실패: ${err.message}`, true);
  }
}

/* ------------------------------------------------------------ 대화 기록 */
async function loadConversations() {
  const list = $("convList");
  try {
    const res = await api("/api/conversations?limit=30");
    if (!res.items.length) {
      list.innerHTML = `<li><div class="empty" style="width:100%">
        <b>저장된 대화가 없습니다</b>가운데 채팅창에서 한 번 물어보면 자동으로 저장됩니다.</div></li>`;
      return;
    }
    list.innerHTML = res.items
      .map(
        (c) => `
      <li data-conv="${c.id}" class="${c.id === state.conversationId ? "active" : ""}">
        <div class="row-main">
          <span class="title">${escapeHtml(c.title)}</span>
          <span class="preview">${escapeHtml(c.preview || `${c.message_count}개 메시지`)}</span>
        </div>
        <div class="row-actions">
          <button class="icon-btn del" data-convdel="${c.id}" title="삭제">🗑️</button>
        </div>
      </li>`
      )
      .join("");
  } catch (err) {
    list.innerHTML = `<li><div class="empty" style="width:100%">
      <b>대화 목록을 불러오지 못했습니다</b>${escapeHtml(err.message)}</div></li>`;
  }
}

/* 대화 불러오기: GET /api/conversations/{id} 로 전체 messages 를 받아 다시 그린다 */
async function openConversation(id) {
  try {
    const conv = await api(`/api/conversations/${id}`);
    state.conversationId = id;
    $("messages").innerHTML = "";
    conv.messages.forEach((m) => addMessage(m.role, m.content));
    $("toolTrace").hidden = true;
    await loadConversations();
    toast(`대화를 불러왔습니다: ${conv.title}`);
  } catch (err) {
    toast(`불러오기 실패: ${err.message}`, true);
  }
}

async function deleteConversation(id) {
  if (!confirm("이 대화를 삭제할까요?")) return;
  try {
    await api(`/api/conversations/${id}`, { method: "DELETE" });
    if (state.conversationId === id) newChat();
    toast("대화를 삭제했습니다.");
    await loadConversations();
  } catch (err) {
    toast(`삭제 실패: ${err.message}`, true);
  }
}

function newChat() {
  state.conversationId = null;
  $("messages").innerHTML = `
    <div class="msg msg--assistant"><div class="bubble">새 대화를 시작합니다. 무엇이 궁금하세요?</div></div>`;
  $("toolTrace").hidden = true;
  loadConversations();
}

/* ------------------------------------------------------------ 채팅 */
function addMessage(role, content) {
  const wrap = document.createElement("div");
  wrap.className = `msg msg--${role === "user" ? "user" : "assistant"}`;
  wrap.innerHTML = `<div class="bubble">${escapeHtml(content)}</div>`;
  const box = $("messages");
  box.appendChild(wrap);
  box.scrollTop = box.scrollHeight;
  return wrap;
}

function addLoading() {
  const wrap = document.createElement("div");
  wrap.className = "msg msg--assistant";
  wrap.innerHTML = `<div class="bubble loading-dots"><span></span><span></span><span></span></div>`;
  const box = $("messages");
  box.appendChild(wrap);
  box.scrollTop = box.scrollHeight;
  return wrap;
}

function renderToolTrace(calls) {
  const el = $("toolTrace");
  if (!calls || !calls.length) {
    el.hidden = true;
    return;
  }
  el.hidden = false;
  el.innerHTML =
    `🔧 GPT가 호출한 도구 ${calls.length}건<br />` +
    calls
      .map(
        (c) =>
          `→ ${escapeHtml(c.name)}(${escapeHtml(JSON.stringify(c.arguments))})`
      )
      .join("<br />");
}

/* 미리 준비된 질문 버튼 · 대체재 버튼이 쓴다.
   입력칸을 채우고 폼을 제출한다 — 사용자가 직접 친 것과 똑같은 경로로 보내야
   나중에 채팅 처리를 고쳐도 이쪽이 따로 어긋나지 않는다. */
function askQuick(text) {
  if (state.sending) return;
  const input = $("chatInput");
  input.value = text;
  document.querySelector(".hero").scrollIntoView({ behavior: "smooth", block: "start" });
  $("chatForm").requestSubmit();
}

async function sendChat(e) {
  e.preventDefault();
  if (state.sending) return;

  const input = $("chatInput");
  const text = input.value.trim();
  if (!text) return;

  state.sending = true;
  $("sendBtn").disabled = true;
  input.value = "";
  addMessage("user", text);
  const loader = addLoading();
  $("toolTrace").hidden = true;

  try {
    const res = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        message: text,
        conversation_id: state.conversationId,
        use_tools: $("useTools").checked,
        // 조건 손잡이로 물었을 때만 실린다. 서버는 이 조건을 프롬프트에 얹고,
        // 값과 판정은 여전히 서버가 계산한 것을 쓴다.
        conditions: window.PLAN_CONDITIONS || null,
      }),
    });
    loader.remove();
    addMessage("assistant", res.reply);
    renderToolTrace(res.tool_calls);
    state.conversationId = res.conversation_id;

    // 대화에서 뽑힌 재료를 장보기 카드로 올린다 (없으면 이전 것을 유지하지 않는다)
    state.focusItems = res.mentioned_items || [];
    state.focusReason = res.mention_reason || "";
    renderCart();
    if (state.focusItems.length) {
      $("cartCard").scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    await loadConversations();
  } catch (err) {
    loader.remove();
    addMessage("assistant", `⚠️ 오류가 발생했습니다: ${err.message}`);
    toast(err.message, true);
  } finally {
    window.PLAN_CONDITIONS = null;   // 한 번 쓰고 비운다 — 다음 질문까지 따라가면 안 된다
    state.sending = false;
    $("sendBtn").disabled = false;
    input.focus();
  }
}

/* ------------------------------------------------------------ 이벤트 바인딩 */
$("chatForm").addEventListener("submit", sendChat);
$("dataForm").addEventListener("submit", submitData);
$("cancelEditBtn").addEventListener("click", cancelEdit);
$("reloadDataBtn").addEventListener("click", refreshAll);
$("themeBtn").addEventListener("click", toggleTheme);
$("csvBtn").addEventListener("click", () => exportData("csv"));
$("jsonBtn").addEventListener("click", () => exportData("json"));

$("quickAsks").addEventListener("click", (e) => {
  const b = e.target.closest("[data-ask]");
  if (b) askQuick(b.dataset.ask);
});

$("sortSeg").addEventListener("click", (e) => {
  const b = e.target.closest("[data-sort]");
  if (!b) return;
  state.sort = b.dataset.sort;
  $("sortSeg").querySelectorAll("[data-sort]").forEach((x) =>
    x.setAttribute("aria-pressed", String(x === b)));
  if (state.summary) renderItemBoard(state.summary);
});

$("clearFocus").addEventListener("click", () => {
  state.focusItems = [];
  state.focusReason = "";
  renderCart();
});

$("rangeSeg").addEventListener("click", (e) => {
  const b = e.target.closest("[data-range]");
  if (!b) return;
  CHART.range = Number(b.dataset.range);
  $("rangeSeg").querySelectorAll("[data-range]").forEach((x) =>
    x.setAttribute("aria-pressed", String(x === b)));
  loadChart();
});

// OS 설정을 바꿨을 때, 사용자가 직접 고르지 않았다면 따라간다
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (!document.documentElement.getAttribute("data-theme")) applyTheme(null);
});
$("newChatBtn").addEventListener("click", newChat);

$("dataList").addEventListener("click", (e) => {
  const edit = e.target.closest("[data-edit]");
  const del = e.target.closest("[data-del]");
  if (edit) startEdit(edit.dataset.edit);
  if (del) deleteData(del.dataset.del);
});

$("convList").addEventListener("click", (e) => {
  const del = e.target.closest("[data-convdel]");
  if (del) return deleteConversation(del.dataset.convdel);
  const li = e.target.closest("[data-conv]");
  if (li) openConversation(li.dataset.conv);
});

/* ------------------------------------------------------------ 초기 구동 */
$("fDate").value = new Date().toISOString().slice(0, 10);

/** 데이터가 바뀌면 요약·목록·그래프가 모두 따라와야 한다. 한 곳에 모아 둔다. */
async function refreshAll() {
  try {
    const r = await api("/api/data/items");
    state.itemNames = r.items;
    renderItemPicker();
    // 데이터 입력칸 자동완성 — 품목 이름이 조금씩 달라지면 품목별 분석이 쪼개진다
    $("itemNames").innerHTML = state.itemNames
      .map((n) => `<option value="${escapeHtml(n)}"></option>`).join("");
  } catch (_) { /* 품목 목록이 없어도 나머지는 그린다 */ }
  await Promise.all([loadData(), loadSummary(), loadChart()]);
}

(async function init() {
  try { applyTheme(localStorage.getItem("theme")); } catch (_) { applyTheme(null); }
  renderLegend();
  $("messages").innerHTML =
    `<div class="msg msg--assistant"><div class="bubble">` +
    `안녕하세요. 만드실 음식이나 궁금한 재료를 말씀해 주세요. ` +
    `필요한 재료가 지금 사도 될 값인지 아래에 정리해 드립니다.` +
    `</div></div>`;
  await wakeServer();
  await Promise.all([refreshAll(), loadConversations()]);
})();
