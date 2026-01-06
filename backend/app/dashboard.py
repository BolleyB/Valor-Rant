# backend/app/dashboard.py
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    # NOTE: raw string so JS regex/backslashes are not mangled by Python
    return HTMLResponse(
        r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>VALORANT Assistant Coach</title>

  <link rel="stylesheet" href="/static/dashboard.css" />
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>

<body>

  <!-- Chat Floating Button + Panel -->
  <div id="chatFab">Chat</div>

  <div id="chatPanel" class="chatPanel" style="display:none;">
    <div class="chatHeader">
      <div>
        <div class="chatTitle">Coach Chat</div>
        <div class="chatSub">Ask about trades, first deaths, autopsy</div>

        <div class="chatQuick">
          <button class="chatQuickBtn" type="button" data-q="What’s our biggest issue?">Biggest issue</button>
          <button class="chatQuickBtn" type="button" data-q="Summarize the round autopsy.">Autopsy summary</button>
          <button class="chatQuickBtn" type="button" data-q="Give me 3 actionable fixes for our entry.">Entry fixes</button>
          <button class="chatQuickBtn" type="button" data-q="Give me 1 drill to improve trade rate.">Trade drill</button>
        </div>
      </div>

      <button id="chatClose" type="button" aria-label="Close chat">✕</button>
    </div>

    <div id="chatLog" class="chatLog"></div>

    <div class="chatInputRow">
      <input id="chatInput" placeholder="Ask: why are we losing on A?" />
      <button id="chatSend" type="button">Send</button>
    </div>
  </div>

  <div class="wrap">
    <div class="topbar">
      <div>
        <h1>VALORANT Assistant Coach</h1>
        <div class="sub">Micro mistakes → macro impact → coach actions (powered by your API)</div>
      </div>

      <div class="controls">
        <span class="pill"><span class="dot"></span><span id="apiStatus">API: checking…</span></span>

        <label class="hint">min_fd</label>
        <select id="minFd">
          <option value="1">1</option>
          <option value="2" selected>2</option>
          <option value="3">3</option>
          <option value="4">4</option>
        </select>

        <label class="hint">map</label>
        <select id="mapSel"><option value="">All</option></select>

        <label class="hint">side</label>
        <select id="sideSel"><option value="">All</option></select>

        <label class="hint">site</label>
        <select id="siteSel"><option value="">All</option></select>

        <button id="refreshBtn" type="button">Refresh</button>
      </div>
    </div>

    <div class="grid">
      <!-- KPIs -->
      <div class="card span-3 kpi">
        <div class="label">Baseline Round Win%</div>
        <div class="value" id="kpiBaseline">—</div>
        <div class="hint">Across filtered rounds</div>
      </div>

      <div class="card span-3 kpi">
        <div class="label">FD Trade Rate</div>
        <div class="value" id="kpiTradeRate">—</div>
        <div class="hint">Of first-death events</div>
      </div>

      <div class="card span-3 kpi">
        <div class="label">Win% when FD Traded</div>
        <div class="value good" id="kpiTradedWin">—</div>
        <div class="hint">Should be high</div>
      </div>

      <div class="card span-3 kpi">
        <div class="label">Win% when FD Untraded</div>
        <div class="value bad" id="kpiUntradedWin">—</div>
        <div class="hint">Pain indicator</div>
      </div>

      <!-- Charts -->
      <div class="card span-8">
        <div class="titleRow">
          <h2>First Death Impact (pp vs baseline)</h2>
          <span class="hint">More negative = costing rounds</span>
        </div>
        <canvas id="impactChart" height="120"></canvas>
      </div>

      <div class="card span-4">
        <div class="titleRow">
          <h2>FD Traded vs Untraded</h2>
          <span class="hint">Count</span>
        </div>
        <canvas id="tradeDonut" height="200"></canvas>
      </div>

      <div class="card span-6">
        <div class="titleRow">
          <h2>Trade Rate by Player</h2>
          <span class="hint">Spacing/coordination</span>
        </div>
        <canvas id="tradeRateChart" height="140"></canvas>
      </div>

      <div class="card span-6">
        <div class="titleRow">
          <h2>Coach Briefing</h2>
          <span class="hint">Generated from insights</span>
        </div>
        <div id="coachReport" class="coachReport">
          <div class="coachReportEmpty">Loading…</div>
        </div>
      </div>

      <!-- Autopsy -->
      <div class="card span-6">
        <div class="titleRow">
          <h2>Round Autopsy — Loss Causes</h2>
          <span class="hint">Share of LOST rounds</span>
        </div>
        <canvas id="autopsyChart" height="160"></canvas>
      </div>

      <div class="card span-6">
        <div class="titleRow">
          <h2>Examples (click to copy)</h2>
          <span class="hint">match · round · side · site</span>
        </div>
        <div id="autopsyExamples" class="examples"></div>
      </div>

      <div id="errorBox" class="err span-12" style="display:none;"></div>
    </div>
  </div>

<script>
  const $ = (id) => document.getElementById(id);

  let impactChart, tradeRateChart, tradeDonut, autopsyChart;

  // ---------- Utils ----------
  function escapeHtml(s){
    return (s || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function fmtPct(v){
    if (v === null || v === undefined) return "—";
    return `${Number(v).toFixed(1)}%`;
  }

  function showError(msg){
    const box = $("errorBox");
    box.style.display = "block";
    box.textContent = msg;
  }

  function clearError(){
    const box = $("errorBox");
    box.style.display = "none";
    box.textContent = "";
  }

  async function checkHealth(){
    try{
      const r = await fetch("/health");
      const j = await r.json();
      $("apiStatus").textContent = "API: " + (j.status || "ok");
    }catch(e){
      $("apiStatus").textContent = "API: error";
    }
  }

  // ---------- Coach report formatting ----------
  function formatCoachReport(text){
    const raw = (text || "").trim();
    if (!raw) return `<div class="coachReportEmpty">No report.</div>`;

    const toInlineHtml = (s) => {
      let out = escapeHtml(s);
      out = out.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
      out = out.replace(/\*(.+?)\*/g, "<em>$1</em>");
      return out;
    };

    const lines = raw.split("\n");

    let html = "";
    let inList = false;

    function closeList(){
      if (inList){
        html += "</ul>";
        inList = false;
      }
    }

    for (let line of lines){
      const l = (line || "").trim();
      if (!l){
        closeList();
        continue;
      }

      // markdown headings
      if (l.startsWith("## ")){
        closeList();
        html += `<h3>${toInlineHtml(l.slice(3))}</h3>`;
        continue;
      }
      if (l.startsWith("# ")){
        closeList();
        html += `<h2>${toInlineHtml(l.slice(2))}</h2>`;
        continue;
      }

      // numbered headings "1) Title"
      let m = l.match(/^(\d+)\)\s+(.+)$/);
      if (m){
        closeList();
        html += `<h3>${toInlineHtml(m[1] + ") " + m[2])}</h3>`;
        continue;
      }

      // bullets
      if (l.startsWith("- ") || l.startsWith("• ")){
        if (!inList){
          html += `<ul class="coachBullets">`;
          inList = true;
        }
        html += `<li>${toInlineHtml(l.replace(/^[-•]\s+/, ""))}</li>`;
        continue;
      }

      closeList();
      html += `<p>${toInlineHtml(l)}</p>`;
    }

    closeList();
    return html;
  }

  // ---------- Chat formatting (bot messages) ----------
  function formatBotText(text){
    const raw = (text || "").trim();
    if (!raw) return `<div class="chatPlain"></div>`;

    const lines = raw.split("\n").map(l => l.trim()).filter(Boolean);

    const toInlineHtml = (s) => {
      let out = escapeHtml(s);
      out = out.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
      out = out.replace(/\*(.+?)\*/g, "<em>$1</em>");
      return out;
    };

    let html = "";
    let sectionTitle = "";
    let bullets = [];
    let paragraphLines = [];

    const flushParagraph = () => {
      if (!paragraphLines.length) return;
      html += `<div class="chatPlain">${toInlineHtml(paragraphLines.join(" "))}</div>`;
      paragraphLines = [];
    };

    const flushSection = () => {
      if (!sectionTitle && !bullets.length) return;
      html += `<div class="chatSection">`;
      if (sectionTitle) html += `<div class="chatSectionTitle">${toInlineHtml(sectionTitle)}</div>`;
      if (bullets.length){
        html += `<ul class="chatBullets">` + bullets.map(b => `<li>${toInlineHtml(b)}</li>`).join("") + `</ul>`;
      }
      html += `</div>`;
      sectionTitle = "";
      bullets = [];
    };

    for (const l of lines){
      // STRICT numbered headings only: "1) ..."
      let m = l.match(/^(\d+)\)\s+(.+)$/);
      if (m){
        flushParagraph();
        flushSection();
        sectionTitle = `${m[1]}) ${m[2]}`;
        continue;
      }

      // markdown headings: "# Title" / "## Title"
      m = l.match(/^(#{1,3})\s+(.+)$/);
      if (m){
        flushParagraph();
        flushSection();
        sectionTitle = m[2];
        continue;
      }

      // "Player Focus:" style headings
      if (l.endsWith(":") && l.length < 60){
        flushParagraph();
        flushSection();
        sectionTitle = l.replace(/:$/, "");
        continue;
      }

      // bullets
      if (l.startsWith("- ") || l.startsWith("• ")){
        flushParagraph();
        bullets.push(l.replace(/^[-•]\s+/, ""));
        continue;
      }

      paragraphLines.push(l);
    }

    flushParagraph();
    flushSection();

    return html || `<div class="chatPlain">${toInlineHtml(raw)}</div>`;
  }

  function addMsg(text, who="bot"){
    const div = document.createElement("div");
    div.className = `msg ${who}`;

    if (who === "bot"){
      div.innerHTML = `
        <div class="msgTools">
          <button class="msgToolBtn" type="button" title="Copy">⧉</button>
        </div>
        <div class="msgBody">${formatBotText(text)}</div>
      `;
      div.querySelector(".msgToolBtn").onclick = async () => {
        try{ await navigator.clipboard.writeText(text); }catch(e){}
      };
    } else {
      div.innerHTML = `<div class="msgBody">${escapeHtml(text)}</div>`;
    }

    $("chatLog").appendChild(div);
    $("chatLog").scrollTop = $("chatLog").scrollHeight;
  }

  // ---------- Options ----------
  async function loadOptions(){
    const res = await fetch("/meta/options");
    const opt = await res.json();

    const mapSel = $("mapSel");
    const sideSel = $("sideSel");
    const siteSel = $("siteSel");

    mapSel.innerHTML = '<option value="">All</option>';
    sideSel.innerHTML = '<option value="">All</option>';
    siteSel.innerHTML = '<option value="">All</option>';

    for (const m of (opt.maps || [])){
      const o = document.createElement("option");
      o.value = m; o.textContent = m;
      mapSel.appendChild(o);
    }
    for (const s of (opt.sides || [])){
      const o = document.createElement("option");
      o.value = s; o.textContent = s;
      sideSel.appendChild(o);
    }
    for (const s of (opt.sites || [])){
      const o = document.createElement("option");
      o.value = s; o.textContent = s;
      siteSel.appendChild(o);
    }
  }

  // ---------- Charts ----------
  function buildImpactChart(players){
    const labels = (players || []).map(p => p.player);
    const data = (players || []).map(p => p.impact_delta_pct_points);

    if (impactChart) impactChart.destroy();
    impactChart = new Chart($("impactChart"), {
      type: "bar",
      data: { labels, datasets: [{ label: "Impact (pp)", data }] },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: { y: { ticks: { callback: (v) => v + "pp" } } }
      }
    });
  }

  function buildTradeRateChart(players){
  // players already sorted by worst → best trade rate
  const labels = players.map(p => p.player);
  const data = players.map(p => p.trade_rate_pct);

  if (tradeRateChart) tradeRateChart.destroy();

  tradeRateChart = new Chart($("tradeRateChart"), {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "Trade Rate %",
        data,
        tension: 0.35,
        fill: true,
        borderWidth: 3,
        pointRadius: 4,
        pointHoverRadius: 6
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        y: {
          min: 0,
          max: 100,
          ticks: { callback: v => v + "%" }
        }
      }
    }
  });
}


  function buildTradeDonut(tradedCount, untradedCount){
    if (tradeDonut) tradeDonut.destroy();
    tradeDonut = new Chart($("tradeDonut"), {
      type: "doughnut",
      data: {
        labels: ["Traded", "Untraded"],
        datasets: [{ data: [tradedCount, untradedCount] }]
      },
      options: { responsive: true, plugins: { legend: { position: "bottom" } } }
    });
  }

  function buildAutopsyChart(causes){
    const labels = (causes || []).map(c => c.cause);
    const data = (causes || []).map(c => c.share_pct);

    if (autopsyChart) autopsyChart.destroy();
    autopsyChart = new Chart($("autopsyChart"), {
      type: "bar",
      data: { labels, datasets: [{ label: "Share of losses (%)", data }] },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: { y: { min: 0, max: 100, ticks: { callback: (v)=> v + "%" } } }
      }
    });
  }

  function renderAutopsyExamples(examples){
    const root = $("autopsyExamples");
    root.innerHTML = "";

    const show = (examples || []).slice(0, 8);
    for (const ex of show){
      const line =
        `${ex.cause} — match ${ex.match_id} · round ${ex.round_number} · ${ex.side} · site ${ex.site_hit}` +
        ` · FD ${ex.first_death_player} (${ex.first_death_role}) · traded ${ex.traded_within_5s} · util ${ex.utility_used_before_first_death}`;

      const item = document.createElement("div");
      item.className = "exampleItem";
      item.textContent = line;

      item.onclick = async () => {
        try{
          await navigator.clipboard.writeText(line);
          item.classList.add("copied");
          setTimeout(()=> item.classList.remove("copied"), 650);
        }catch(e){}
      };

      root.appendChild(item);
    }
  }

  // ---------- Dashboard loader ----------
  async function loadDashboard(){
    clearError();
    $("coachReport").innerHTML = `<div class="coachReportEmpty">Loading…</div>`;

    const minFd = $("minFd").value;
    const map = $("mapSel").value;
    const side = $("sideSel").value;
    const site = $("siteSel").value;

    const params = new URLSearchParams();
    params.set("min_fd", minFd);
    if (map) params.set("map", map);
    if (side) params.set("side", side);
    if (site) params.set("site", site);

    try{
      const [fdRes, tradesRes, reportRes, autopsyRes] = await Promise.all([
        fetch(`/insights/first-deaths?${params.toString()}`),
        fetch(`/insights/trades?${params.toString()}`),
        fetch(`/report/coach?${params.toString()}`),
        fetch(`/insights/round-autopsy?${params.toString()}`)
      ]);

      const fd = await fdRes.json();
      const trades = await tradesRes.json();
      const report = await reportRes.json();
      const autopsy = await autopsyRes.json();

      if (!fdRes.ok) throw new Error(fd.detail || "Failed to load first deaths");
      if (!tradesRes.ok) throw new Error(trades.detail || "Failed to load trades");
      if (!reportRes.ok) throw new Error(report.detail || "Failed to load report");
      if (!autopsyRes.ok) throw new Error(autopsy.detail || "Failed to load round autopsy");

      $("kpiBaseline").textContent = fmtPct(fd.baseline_round_win_pct);
      $("kpiTradeRate").textContent = fmtPct(trades.team_trade_summary.trade_rate_pct);
      $("kpiTradedWin").textContent = fmtPct(trades.team_trade_summary.win_pct_when_traded_fd);
      $("kpiUntradedWin").textContent = fmtPct(trades.team_trade_summary.win_pct_when_untraded_fd);

      buildImpactChart(fd.players || []);
      buildTradeRateChart(trades.players || []);

      const tradedCount = trades.team_trade_summary.traded_first_deaths ?? 0;
      const untradedCount = trades.team_trade_summary.untraded_first_deaths ?? 0;
      buildTradeDonut(tradedCount, untradedCount);

      $("coachReport").innerHTML = formatCoachReport(report.report || "");

      buildAutopsyChart(autopsy.causes || []);
      renderAutopsyExamples(autopsy.examples || []);

    }catch(e){
      showError(e.message || String(e));
    }
  }

  // ---------- Chat ----------
  async function sendChat(){
    const input = $("chatInput");
    const text = (input.value || "").trim();
    if (!text) return;

    input.value = "";
    addMsg(text, "user");

    const payload = {
      message: text,
      map: $("mapSel")?.value || null,
      side: $("sideSel")?.value || null,
      site: $("siteSel")?.value || null
    };

    try{
      const res = await fetch("/chat", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify(payload)
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.detail || "Chat failed");
      addMsg(j.answer || "No response.", "bot");
    }catch(e){
      addMsg("Error: " + (e.message || String(e)), "bot");
    }
  }

  function initChatUI(){
    const fab = $("chatFab");
    const panel = $("chatPanel");
    const closeBtn = $("chatClose");
    const sendBtn = $("chatSend");
    const input = $("chatInput");
    const log = $("chatLog");

    if (!fab || !panel || !closeBtn || !sendBtn || !input || !log){
      console.error("Chat DOM missing");
      return;
    }

    fab.addEventListener("click", () => {
      fab.style.display = "none";
      panel.style.display = "flex";
      if (log.children.length === 0){
        addMsg("Ask me: 'What’s our biggest issue?' or 'Give me drills for trade rate.'", "bot");
      }
      setTimeout(()=> input.focus(), 50);
    });

    closeBtn.addEventListener("click", () => {
      panel.style.display = "none";
      fab.style.display = "block";
    });

    sendBtn.addEventListener("click", sendChat);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") sendChat();
    });

    // quick buttons
    panel.querySelectorAll(".chatQuickBtn").forEach(btn => {
      btn.addEventListener("click", () => {
        input.value = btn.getAttribute("data-q") || "";
        sendChat();
      });
    });
  }

  // ---------- Events ----------
  function bindControls(){
    $("refreshBtn").addEventListener("click", loadDashboard);
    $("minFd").addEventListener("change", loadDashboard);
    $("mapSel").addEventListener("change", loadDashboard);
    $("sideSel").addEventListener("change", loadDashboard);
    $("siteSel").addEventListener("change", loadDashboard);
  }

  async function initApp(){
    bindControls();
    initChatUI();
    await checkHealth();
    await loadOptions();
    await loadDashboard();
  }

  window.addEventListener("DOMContentLoaded", () => {
    initApp().catch((e) => {
      console.error("Init failed:", e);
      showError(e?.message || String(e));
    });
  });
</script>

</body>
</html>
"""
    )
