/* ==========================================================================
   viz.js — 분류 필터 · 조건 추천 · 네 가지 시각화 · 향후 추이선

   app.js 와 나눈 이유
     app.js 는 '데이터를 주고받고 표를 그리는' 일을 한다.
     이 파일은 '해석해서 보여주는' 일만 한다. 한 파일에 두면 1,400줄이 되어
     어디를 고쳐야 하는지 찾는 데 시간이 더 걸린다.

   프레임워크는 쓰지 않는다 (과제 제약). 그래프는 전부 SVG 를 직접 만든다.
   색은 CSS 변수로만 주므로 다크 모드가 저절로 따라온다.
   ========================================================================== */

const VIZ = {
  tree: [],
  vocab: { prep: [], purpose: [] },
  cat: { major: null, mid: null, minor: null },   // 시세판 필터
  chartCat: { major: null, mid: null, minor: null },
  mode: "radar",
  planMode: "server",
  scores: null,
  swot: null,
  forecast: null,
};

// 고전 스크립트의 최상위 const 는 window 에 붙지 않는다. app.js 가
// window.VIZ 로 확인하므로 여기서 명시적으로 걸어 준다. (이걸 빠뜨려서
// 분류 필터가 시세판에만 안 먹는 일이 실제로 있었다)
window.VIZ = VIZ;

/* ---------------------------------------------------------------- 공통 */
const vEl = (id) => document.getElementById(id);
const vEsc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const vWon = (n) => Number(n || 0).toLocaleString("ko-KR");

/** 이 분류 필터에 걸리는 품목 이름들. 아무것도 안 고르면 null(=전체). */
function catItems(sel) {
  if (!sel.major) return null;
  const out = [];
  for (const maj of VIZ.tree) {
    if (maj.name !== sel.major) continue;
    for (const mid of maj.children) {
      if (sel.mid && mid.name !== sel.mid) continue;
      for (const mnr of mid.children) {
        if (sel.minor && mnr.name !== sel.minor) continue;
        out.push(...mnr.items);
      }
    }
  }
  return out;
}

/* ---------------------------------------------------------------- 분류 막대
   대 → 중 → 소 를 한 줄씩 쌓는다. 대분류를 고르기 전에는 아랫줄을 만들지 않는다.
   3단을 처음부터 다 펼치면 46품목에서 버튼이 60개가 넘어 오히려 못 찾는다. */
function renderCatBar(boxId, sel, onChange) {
  const box = vEl(boxId);
  if (!box || !VIZ.tree.length) return;

  const rows = [];
  const chip = (label, count, on, data) =>
    `<button type="button" class="cat-chip" aria-pressed="${on}" ${data}>
       ${vEsc(label)}${count != null ? `<em>${count}</em>` : ""}</button>`;

  rows.push(`<div class="cat-row"><span class="cat-label">대분류</span>
    ${chip("전체", null, !sel.major, 'data-major=""')}
    ${VIZ.tree.map((m) => chip(m.name, m.count, sel.major === m.name,
      `data-major="${vEsc(m.name)}"`)).join("")}</div>`);

  const maj = VIZ.tree.find((m) => m.name === sel.major);
  if (maj) {
    rows.push(`<div class="cat-row"><span class="cat-label">중분류</span>
      ${chip("전체", null, !sel.mid, 'data-mid=""')}
      ${maj.children.map((m) => chip(m.name, m.count, sel.mid === m.name,
        `data-mid="${vEsc(m.name)}"`)).join("")}</div>`);

    const mid = maj.children.find((m) => m.name === sel.mid);
    if (mid && mid.children.length > 1) {
      rows.push(`<div class="cat-row"><span class="cat-label">소분류</span>
        ${chip("전체", null, !sel.minor, 'data-minor=""')}
        ${mid.children.map((m) => chip(m.name, m.count, sel.minor === m.name,
          `data-minor="${vEsc(m.name)}"`)).join("")}</div>`);
    }
  }
  box.innerHTML = rows.join("");

  box.querySelectorAll("[data-major]").forEach((b) => b.onclick = () => {
    sel.major = b.dataset.major || null; sel.mid = null; sel.minor = null;
    renderCatBar(boxId, sel, onChange); onChange();
  });
  box.querySelectorAll("[data-mid]").forEach((b) => b.onclick = () => {
    sel.mid = b.dataset.mid || null; sel.minor = null;
    renderCatBar(boxId, sel, onChange); onChange();
  });
  box.querySelectorAll("[data-minor]").forEach((b) => b.onclick = () => {
    sel.minor = b.dataset.minor || null;
    renderCatBar(boxId, sel, onChange); onChange();
  });
}

/* ---------------------------------------------------------------- 조건 손잡이 */
const SEASON_WORDS = [[0, "아무 때나"], [35, "약하게"], [65, "보통"], [85, "제철 위주"], [101, "제철만"]];
const LEVEL_WORDS = ["상관없음", "아주 쉬움", "쉬움", "보통", "손이 감", "많이 감"];
const CONV_WORDS = ["상관없음", "준비 오래", "조금 걸림", "보통", "간단", "바로 조리"];

function word(list, v) {
  for (const [max, w] of list) if (v < max) return w;
  return list[list.length - 1][1];
}

function renderKnobs() {
  const chips = (id, list) => {
    const box = vEl(id);
    box.innerHTML = list.map((v) =>
      `<button type="button" class="chip-btn" data-v="${vEsc(v)}" aria-pressed="false">${vEsc(v)}</button>`).join("");
    box.querySelectorAll("[data-v]").forEach((b) => b.onclick = () => {
      b.setAttribute("aria-pressed", b.getAttribute("aria-pressed") === "true" ? "false" : "true");
    });
  };
  chips("prepChips", VIZ.vocab.prep);
  chips("purposeChips", VIZ.vocab.purpose);

  const bind = (id, out, fn) => {
    const el = vEl(id);
    const paint = () => (vEl(out).textContent = fn(Number(el.value)));
    el.oninput = paint;
    paint();
  };
  bind("kSeason", "kSeasonV", (v) => word(SEASON_WORDS, v));
  bind("kFresh", "kFreshV", (v) => word(SEASON_WORDS, v));
  bind("kDiff", "kDiffV", (v) => LEVEL_WORDS[v]);
  bind("kConv", "kConvV", (v) => CONV_WORDS[v]);
}

function readConditions() {
  const picked = (id) => [...vEl(id).querySelectorAll('[aria-pressed="true"]')].map((b) => b.dataset.v);
  const num = (id) => Number(vEl(id).value);
  return {
    prep: picked("prepChips"),
    purpose: picked("purposeChips"),
    season_weight: num("kSeason") / 100,
    freshness_weight: num("kFresh") / 100,
    difficulty: num("kDiff") || null,
    convenience: num("kConv") || null,
    limit: 5,
  };
}

/* ---------------------------------------------------------------- 추천 */
async function runPlan() {
  const cond = readConditions();
  const box = vEl("planResult");

  // AI 모드 — 같은 조건을 말로 바꿔 채팅으로 보낸다.
  // 결정적인 답이 필요하면 서버 추천, 사람 말투의 제안이 필요하면 이쪽.
  if (VIZ.planMode === "ai") {
    const bits = [];
    if (cond.prep.length) bits.push(cond.prep.join("·") + " 로");
    if (cond.purpose.length) bits.push(cond.purpose.join("·") + " 용으로");
    if (cond.season_weight >= 0.7) bits.push("제철인 걸로");
    if (cond.difficulty) bits.push(`난이도 ${cond.difficulty} 정도로`);
    if (cond.convenience) bits.push(`준비가 ${CONV_WORDS[cond.convenience]}한 걸로`);
    window.PLAN_CONDITIONS = cond;
    askQuick(`${bits.join(" ") || "지금 시기에"} 만들 만한 음식과 재료를 추천해줘.`);
    return;
  }

  box.innerHTML = `<div class="muted">조건에 맞는 음식을 고르는 중…</div>`;
  vEl("planBtn").disabled = true;
  try {
    const res = await api("/api/recommend", { method: "POST", body: JSON.stringify(cond) });
    renderPlan(res);
  } catch (err) {
    box.innerHTML = `<div class="empty"><b>추천하지 못했습니다</b>${vEsc(err.message)}</div>`;
  } finally {
    vEl("planBtn").disabled = false;
  }
}

function renderPlan(res) {
  const box = vEl("planResult");
  if (!res.ok || !res.dishes.length) {
    box.innerHTML = `<div class="empty"><b>맞는 음식을 찾지 못했습니다</b>
      조건을 조금 느슨하게 해 보세요.</div>`;
    vEl("planCount").textContent = "";
    return;
  }
  vEl("planCount").textContent = `${res.month}월 기준 · ${res.dishes.length}가지`;

  box.innerHTML = res.dishes.map((d) => {
    const rows = d.ingredients.map((i) => {
      if (!i.known) return `<li class="ing ing--unknown">${vEsc(i.item)}<em>시세 없음</em></li>`;
      const alt = (i.alternatives || []).map((a) =>
        `<span class="alt-pill" title="${vEsc(a.why)}">↔ ${vEsc(a.item)}</span>`).join("");
      return `<li class="ing">
        <b>${vEsc(i.item)}</b>
        <span class="ing-price">${vWon(Math.round(i.recent_avg))}원</span>
        <span class="ing-verdict tone-${vEsc(i.verdict_tone)}">${vEsc(i.verdict_short)}</span>
        ${alt}</li>`;
    }).join("");

    return `<article class="dish">
      <header>
        <h3>${vEsc(d.dish)}</h3>
        <span class="dish-tag">${vEsc(d.prep)}</span>
        <span class="dish-cost">${vWon(d.cost)}원</span>
      </header>
      <p class="dish-why">${vEsc(d.why)}</p>
      <ul class="ing-list">${rows}</ul>
      <button type="button" class="btn btn--ghost btn--sm" data-basket="${vEsc(d.dish)}">🛒 이 재료 담기</button>
    </article>`;
  }).join("");

  box.querySelectorAll("[data-basket]").forEach((b) => b.onclick = () => {
    const d = res.dishes.find((x) => x.dish === b.dataset.basket);
    state.focusItems = d.ingredients.filter((i) => i.known).map((i) => i.item);
    state.focusReason = `${d.dish} → ${state.focusItems.join(", ")}`;
    renderCart();
    vEl("cartCard").scrollIntoView({ behavior: "smooth", block: "center" });
  });
}

/* ==========================================================================
   시각화 ①  평가 지표 레이더
   여섯 축 중 셋은 측정값, 셋은 참고값이다. 한 그림에 넣되 실선/점선으로 나눈다.
   ========================================================================== */
function radarSvg(sc) {
  const R = 74, CX = 100, CY = 96, n = sc.axes.length;
  const pt = (i, v) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / n;
    const r = (v / 100) * R;
    return [CX + r * Math.cos(a), CY + r * Math.sin(a)];
  };
  const web = [25, 50, 75, 100].map((lv) =>
    `<polygon class="radar-web" points="${sc.axes.map((_, i) => pt(i, lv).map((x) => x.toFixed(1)).join(",")).join(" ")}"/>`
  ).join("");
  const spokes = sc.axes.map((_, i) =>
    `<line class="radar-web" x1="${CX}" y1="${CY}" x2="${pt(i, 100)[0].toFixed(1)}" y2="${pt(i, 100)[1].toFixed(1)}"/>`
  ).join("");
  const poly = sc.axes.map((a, i) => pt(i, a.value).map((x) => x.toFixed(1)).join(",")).join(" ");
  const dots = sc.axes.map((a, i) => {
    const [x, y] = pt(i, a.value);
    return `<circle r="2.6" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}"
      class="radar-dot ${a.source === "measured" ? "is-measured" : "is-ref"}"><title>${vEsc(a.label)} ${a.value}</title></circle>`;
  }).join("");
  const labels = sc.axes.map((a, i) => {
    const [x, y] = pt(i, 122);
    return `<text class="radar-label ${a.source === "measured" ? "is-measured" : ""}"
      x="${x.toFixed(1)}" y="${(y + 3).toFixed(1)}" text-anchor="middle">${vEsc(a.label)}</text>`;
  }).join("");
  return `<svg viewBox="0 0 200 200" role="img" aria-label="${vEsc(sc.item)} 평가 지표">
    ${web}${spokes}<polygon class="radar-area" points="${poly}"/>${dots}${labels}</svg>`;
}

function renderRadar() {
  const body = vEl("vizBody");
  const all = VIZ.scores?.items || [];
  const filter = catItems(VIZ.cat);
  const items = (filter ? all.filter((s) => filter.includes(s.item)) : all).slice(0, 12);
  if (!items.length) { body.innerHTML = `<div class="empty"><b>표시할 품목이 없습니다</b></div>`; return; }

  vEl("vizNote").innerHTML =
    `축 여섯 개 중 <b class="is-measured-txt">계절성 · 가격 · 신선도</b> 는 실제 가격에서 계산한 값이고,
     <b>기호도 · 편의성 · 쉬움</b> 은 카탈로그에 적어 둔 참고값입니다. 섞지 않고 구분해 표시합니다.`;

  body.innerHTML = `<div class="radar-grid">${items.map((s) => `
    <figure class="radar-card">
      ${radarSvg(s)}
      <figcaption>
        <b>${vEsc(s.item)}</b>
        <span class="muted">${vEsc(s.mid)}</span>
        <span class="radar-score">측정 ${s.measured_avg}점</span>
      </figcaption>
    </figure>`).join("")}</div>`;
}

/* ==========================================================================
   시각화 ②  SWOT — 네 칸 모두 계산 결과이고, 항목마다 근거가 붙는다.
   ========================================================================== */
function renderSwot() {
  const body = vEl("vizBody");
  const s = VIZ.swot;
  if (!s) { body.innerHTML = `<div class="empty"><b>불러오는 중…</b></div>`; return; }

  vEl("vizNote").textContent =
    "강점·약점은 지금 값에서, 기회·위협은 월별 평균과 변동성에서 계산했습니다. 각 줄의 이유가 곧 근거입니다.";

  const cell = (key, title, hint, tone) => {
    const rows = s[key] || [];
    return `<div class="swot-cell swot--${tone}">
      <h3>${title}<em>${hint}</em></h3>
      ${rows.length ? `<ul>${rows.map((r) =>
        `<li><b>${vEsc(r.item)}</b> ${vEsc(r.why)}</li>`).join("")}</ul>`
        : `<p class="muted">해당 없음</p>`}
    </div>`;
  };
  body.innerHTML = `<div class="swot">
    ${cell("strength", "S 강점", "지금이 유리한 것", "good")}
    ${cell("weakness", "W 약점", "지금이 불리한 것", "bad")}
    ${cell("opportunity", "O 기회", "미루면 좋아질 것", "mid")}
    ${cell("threat", "T 위협", "곧 나빠질 것", "warn")}
  </div>`;
}

/* ==========================================================================
   시각화 ③  분류별 히트맵 — 분류 × 월. 어느 갈래가 언제 싼지 한눈에.
   각 칸은 그 분류에 속한 품목들의 '연평균 대비 그 달 평균' 이다.
   절대 가격을 칠하면 대하(3만원)가 전부를 덮어 채소가 안 보인다.
   ========================================================================== */
function heatColor(pct) {
  // -25% 초록 ~ 0 회색 ~ +25% 빨강
  const t = Math.max(-1, Math.min(1, pct / 25));
  if (t < 0) return `color-mix(in srgb, var(--accent) ${Math.round(-t * 70)}%, var(--card))`;
  return `color-mix(in srgb, var(--danger) ${Math.round(t * 70)}%, var(--card))`;
}

async function renderHeat() {
  const body = vEl("vizBody");
  vEl("vizNote").textContent =
    "칸의 값은 그 분류의 '연평균 대비 그 달 평균'입니다. 절대 가격을 칠하면 값비싼 한 품목이 표 전체를 덮어 버립니다.";
  body.innerHTML = `<div class="muted">월별 평균을 모으는 중…</div>`;

  let rel;
  try {
    rel = (await api("/api/data/monthly")).relative || {};
  } catch (err) {
    body.innerHTML = `<div class="empty"><b>월별 평균을 불러오지 못했습니다</b>${vEsc(err.message)}</div>`;
    return;
  }

  // 분류(대·중) 별로 품목의 상대값을 평균낸다
  const buckets = [];
  for (const maj of VIZ.tree) {
    for (const mid of maj.children) {
      const names = mid.children.flatMap((c) => c.items).filter((n) => rel[n]);
      if (names.length) buckets.push({ label: `${maj.name} · ${mid.name}`, names });
    }
  }
  if (!buckets.length) { body.innerHTML = `<div class="empty"><b>월별 평균을 만들 데이터가 부족합니다</b></div>`; return; }

  const MONTHS = Array.from({ length: 12 }, (_, i) => String(i + 1).padStart(2, "0"));
  body.innerHTML = `<div class="heat-wrap"><table class="heat">
    <thead><tr><th></th>${MONTHS.map((m) => `<th>${Number(m)}월</th>`).join("")}</tr></thead>
    <tbody>${buckets.map((b) => `<tr>
      <th>${vEsc(b.label)}<em>${b.names.length}품목</em></th>
      ${MONTHS.map((m) => {
        const vs = b.names.map((n) => rel[n][m]).filter((v) => v != null);
        if (!vs.length) return `<td class="na">·</td>`;
        const pct = vs.reduce((a, c) => a + c, 0) / vs.length;
        return `<td style="background:${heatColor(pct)}"
          title="${vEsc(b.label)} ${Number(m)}월 · 연평균 대비 ${pct.toFixed(0)}%">${pct > 0 ? "+" : ""}${pct.toFixed(0)}</td>`;
      }).join("")}</tr>`).join("")}</tbody>
  </table></div>
  <div class="heat-legend"><span>싼 달</span><i class="g"></i><i class="n"></i><i class="b"></i><span>비싼 달</span></div>`;
}

/* ==========================================================================
   시각화 ④  가격 분포 — 품목마다 최저~최고 막대 위에 지금 값을 점으로.
   "지금이 그 품목의 1년 범위에서 어디쯤인가"가 이 그림의 질문이다.
   ========================================================================== */
function renderDist() {
  const body = vEl("vizBody");
  vEl("vizNote").textContent =
    "가로 막대는 그 품목의 1년 최저~최고 범위이고, 점은 최근 7일 평균입니다. 점이 왼쪽에 있을수록 지금이 싼 편입니다.";

  const filter = catItems(VIZ.cat);
  let rows = state.summary?.items || [];
  if (filter) rows = rows.filter((r) => filter.includes(r.item));
  rows = rows.filter((r) => r.min != null && r.max != null && r.max > r.min);
  if (!rows.length) { body.innerHTML = `<div class="empty"><b>표시할 품목이 없습니다</b></div>`; return; }

  rows = [...rows].sort((a, b) => (b.max || 0) - (a.max || 0));
  body.innerHTML = `<div class="dist">${rows.map((r) => {
    const pos = ((r.recent_avg - r.min) / (r.max - r.min)) * 100;
    const avgPos = ((r.average - r.min) / (r.max - r.min)) * 100;
    return `<div class="dist-row">
      <span class="dist-name">${vEsc(r.item)}</span>
      <span class="dist-bar">
        <i class="dist-avg" style="left:${avgPos.toFixed(1)}%" title="1년 평균 ${vWon(Math.round(r.average))}원"></i>
        <i class="dist-now tone-bg-${vEsc(r.verdict_tone)}" style="left:${Math.max(0, Math.min(100, pos)).toFixed(1)}%"
           title="최근 7일 ${vWon(Math.round(r.recent_avg))}원"></i>
      </span>
      <span class="dist-lo">${vWon(r.min)}</span>
      <span class="dist-hi">${vWon(r.max)}</span>
    </div>`;
  }).join("")}
  <p class="dist-key"><i class="k-avg"></i> 1년 평균 &nbsp; <i class="k-now"></i> 지금(최근 7일)</p></div>`;
}

/* ---------------------------------------------------------------- 전환 */
async function showViz(mode) {
  VIZ.mode = mode;
  vEl("vizSeg").querySelectorAll("[data-viz]").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.viz === mode)));

  if (mode === "radar") {
    if (!VIZ.scores) VIZ.scores = await api("/api/data/scores").catch(() => null);
    renderRadar();
  } else if (mode === "swot") {
    if (!VIZ.swot) VIZ.swot = await api("/api/data/swot").catch(() => null);
    renderSwot();
  } else if (mode === "heat") {
    await renderHeat();
  } else {
    renderDist();
  }
}

/* ==========================================================================
   향후 추이선 — 과거 선 뒤에 이어 붙이고, 불확실성은 띠로 그린다.
   선 하나만 그리면 사용자가 그것을 '정답'으로 읽는다. 띠가 넓다는 것은
   못 믿을 품목이라는 뜻이고, 그 사실이 값 자체만큼 중요하다.
   ========================================================================== */
async function loadForecast() {
  const box = vEl("fcBox");
  if (!box.open) return;

  const q = new URLSearchParams({
    days: vEl("fcDays").value,
    fx: vEl("fcFx").value,
    weather: vEl("fcWeather").value,
    fuel: vEl("fcFuel").value,
  });
  if (CHART.item) q.set("item", CHART.item);

  try {
    const f = await api(`/api/data/forecast?${q}`);
    VIZ.forecast = f;
    if (!f.ok) {
      vEl("fcMethod").textContent = f.reason;
      drawChart();
      return;
    }
    vEl("fcMethod").innerHTML =
      `<b>이렇게 계산했습니다</b> ${vEsc(f.method)}<br><span class="muted">⚠️ ${vEsc(f.caveat)}</span>`;
    drawChart();
  } catch (err) {
    vEl("fcMethod").textContent = `추이선을 계산하지 못했습니다: ${err.message}`;
  }
}

/** 지금 보고 있는 품목의 대체재. 값이 비쌀 때 다음 질문은 항상 "그럼 뭘 사나"다.
    예측 패널 안에 두었더니 패널을 펼쳐야만 보였다 — 대체재는 예측과 상관없는
    정보라, 품목을 고르는 즉시 보이게 한다. */
async function renderAlts() {
  const box = vEl("altRow");
  if (!CHART.item) { box.innerHTML = ""; return; }
  try {
    const r = await api(`/api/data/alternatives?item=${encodeURIComponent(CHART.item)}`);
    const list = r.alternatives || [];
    box.innerHTML = list.length
      ? `<span class="muted">${vEsc(CHART.item)} 대신 —</span>` + list.map((a) =>
          `<span class="alt-pill" title="${vEsc(a.why)}">${vEsc(a.item)}</span>`).join("")
      : "";
  } catch (_) { box.innerHTML = ""; }
}

/* ---------------------------------------------------------------- 초기화 */
async function initViz() {
  try {
    const c = await api("/api/data/categories");
    VIZ.tree = c.tree || [];
    VIZ.vocab = c.vocabulary || VIZ.vocab;
  } catch (_) { VIZ.tree = []; }

  renderKnobs();

  renderCatBar("catBar", VIZ.cat, () => {
    if (state.summary) renderItemBoard(state.summary);
    if (VIZ.mode === "radar") renderRadar();
    if (VIZ.mode === "dist") renderDist();
  });
  renderCatBar("chartCatBar", VIZ.chartCat, () => {
    renderItemPicker();
  });

  vEl("planBtn").onclick = runPlan;
  vEl("planReset").onclick = () => {
    document.querySelectorAll("#prepChips [data-v],#purposeChips [data-v]")
      .forEach((b) => b.setAttribute("aria-pressed", "false"));
    vEl("kSeason").value = 70; vEl("kFresh").value = 50;
    vEl("kDiff").value = 0; vEl("kConv").value = 0;
    renderKnobs();
    vEl("planResult").innerHTML = "";
    vEl("planCount").textContent = "";
  };

  vEl("planMode").onclick = (e) => {
    const b = e.target.closest("[data-mode]");
    if (!b) return;
    VIZ.planMode = b.dataset.mode;
    vEl("planMode").querySelectorAll("[data-mode]").forEach((x) =>
      x.setAttribute("aria-pressed", String(x === b)));
    vEl("planBtn").textContent = VIZ.planMode === "ai" ? "AI에게 물어보기" : "이 조건으로 추천받기";
    vEl("planModeNote").textContent = VIZ.planMode === "ai"
      ? "조건을 문장으로 바꿔 AI에게 보냅니다. 말투가 자연스러운 대신 같은 조건이라도 답이 조금씩 달라집니다."
      : "같은 조건이면 같은 결과가 나옵니다. 조건은 서버가 계산해 음식을 고르고, 값은 실제 시세로 판정합니다.";
  };

  vEl("vizSeg").onclick = (e) => {
    const b = e.target.closest("[data-viz]");
    if (b) showViz(b.dataset.viz);
  };

  ["fcDays", "fcFx", "fcWeather", "fcFuel"].forEach((id) => {
    const el = vEl(id);
    const out = vEl(id + "V");
    const paint = () => {
      const v = Number(el.value);
      out.textContent = id === "fcDays" ? `${v}일` : `${v > 0 ? "+" : ""}${v}%`;
    };
    el.oninput = paint;
    el.onchange = () => { paint(); loadForecast(); };
    paint();
  });
  vEl("fcBox").addEventListener("toggle", () => {
    if (vEl("fcBox").open) loadForecast(); else { VIZ.forecast = null; drawChart(); }
  });

  await showViz("radar");
}

/** app.js 가 데이터를 새로 받아올 때마다 부른다. 캐시를 버리고 다시 그린다. */
function refreshViz() {
  VIZ.scores = null;
  VIZ.swot = null;
  if (VIZ.mode === "radar" || VIZ.mode === "swot") showViz(VIZ.mode);
  else if (VIZ.mode === "dist") renderDist();
  if (vEl("fcBox").open) loadForecast();
}
window.refreshViz = refreshViz;

initViz();
