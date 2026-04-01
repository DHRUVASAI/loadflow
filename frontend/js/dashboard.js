/* global Chart */

const THEME = {
  primary: "#00d4aa",
  danger: "#e94560",
  warning: "#f0a500",
  info: "#4a9eff",
  text: "#ffffff",
  muted: "#8b8b9e",
};

const CPU_THRESHOLDS = {
  yellow: 50,
  red: 80,
};

let requestsChart = null;
let loadChart = null;
let compareCharts = {};

const chartsState = {
  // Keep last 10 snapshots.
  timeLabels: [],
  // Map serverName -> array of cpu% values (or null when missing)
  cpuSeriesByServer: {},
  // For stable colors
  colorByServer: {},
};

const autoRefreshMs = 3000;

function getPageKey() {
  const p = window.location.pathname || "/";
  if (p === "/") return "dashboard";
  if (p === "/compare") return "compare";
  if (p === "/history") return "history";
  if (p === "/servers") return "servers";
  return "unknown";
}

function toastContainer() {
  let el = document.getElementById("toast-container");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast-container";
    el.style.position = "fixed";
    el.style.right = "18px";
    el.style.bottom = "18px";
    el.style.zIndex = "9999";
    el.style.display = "flex";
    el.style.flexDirection = "column";
    el.style.gap = "10px";
    document.body.appendChild(el);
  }
  return el;
}

function showToast(message, type = "info") {
  const colors = {
    success: { border: THEME.primary, bg: "rgba(0,212,170,.12)", fg: "#bafff2" },
    error: { border: THEME.danger, bg: "rgba(233,69,96,.12)", fg: "#ffd2db" },
    warning: { border: THEME.warning, bg: "rgba(240,165,0,.12)", fg: "#fff1cc" },
    info: { border: THEME.info, bg: "rgba(74,158,255,.12)", fg: "#d6e9ff" },
  };
  const c = colors[type] || colors.info;

  const t = document.createElement("div");
  t.textContent = message;
  t.style.padding = "12px 14px";
  t.style.borderRadius = "14px";
  t.style.border = `1px solid rgba(255,255,255,.10)`;
  t.style.background = c.bg;
  t.style.color = c.fg;
  t.style.boxShadow = `0 0 0 1px ${c.border}22, 0 12px 40px rgba(0,0,0,.35)`;
  t.style.fontWeight = "800";
  t.style.fontSize = "13px";
  t.style.maxWidth = "360px";
  t.style.wordBreak = "break-word";
  t.style.animation = "flash-in .22s ease-out";

  toastContainer().appendChild(t);
  setTimeout(() => {
    try {
      t.remove();
    } catch (e) {
      // ignore
    }
  }, 3000);
}

function showAlert(message) {
  const banner = document.getElementById("overloadAlert");
  if (!banner) return;

  // Ensure there is a close button.
  let closeBtn = banner.querySelector("[data-alert-close]");
  if (!closeBtn) {
    closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.setAttribute("data-alert-close", "true");
    closeBtn.textContent = "X";
    closeBtn.style.cssText =
      "margin-left:12px; background:transparent; border:1px solid rgba(255,255,255,.14); color:#ffd2db; border-radius:10px; padding:6px 10px; cursor:pointer; font-weight:900;";
    closeBtn.addEventListener("click", () => {
      banner.classList.remove("is-visible");
    });
    // Place close button inside banner content if possible.
    const content = banner.querySelector(".alert-content");
    if (content) content.appendChild(closeBtn);
  }

  const textEl = banner.querySelector(".alert-text");
  if (textEl) textEl.textContent = message;
  banner.classList.add("is-visible");
}

function hideAlert() {
  const banner = document.getElementById("overloadAlert");
  if (!banner) return;
  banner.classList.remove("is-visible");
}

function setGlobalSpinner(visible) {
  const el = document.getElementById("global-spinner");
  if (!el) return;
  el.classList.toggle("is-visible", Boolean(visible));
}

async function fetchJSON(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${txt ? `: ${txt}` : ""}`);
  }
  return res.json();
}

function safeGetNumber(obj, key, fallback = null) {
  if (!obj) return fallback;
  const v = obj[key];
  if (v === undefined || v === null || v === "") return fallback;
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function getDisplayCpu(server) {
  // Our backend may provide `cpu_percent`, but if not, approximate from `load` (0-100).
  const cpu =
    safeGetNumber(server, "cpu_percent") ??
    safeGetNumber(server, "cpu") ??
    safeGetNumber(server, "load", null) ??
    0;
  return Math.max(0, Math.min(100, Math.round(cpu)));
}

function getStatusForCpu(cpu) {
  if (cpu > CPU_THRESHOLDS.red) return { level: "red", className: "health-red", badge: "status-red" };
  if (cpu >= CPU_THRESHOLDS.yellow) return { level: "yellow", className: "health-yellow", badge: "status-yellow" };
  return { level: "green", className: "health-green", badge: "status-green" };
}

function assignServerColors(serverNames) {
  const palette = [
    THEME.primary,
    THEME.info,
    THEME.warning,
    THEME.danger,
    "#b388ff",
    "#00ffa3",
    "#7dd3fc",
    "#fda4af",
  ];
  serverNames.forEach((name, idx) => {
    if (!chartsState.colorByServer[name]) {
      chartsState.colorByServer[name] = palette[idx % palette.length];
    }
  });
}

function updateServerCards(servers) {
  const cardContainer = document.getElementById("serverCards");
  if (!cardContainer) return;

  // Use up to the pre-rendered card count.
  const cardEls = Array.from(cardContainer.querySelectorAll(".server-card"));
  const max = Math.min(cardEls.length, servers.length);
  let sawOverload = false;

  for (let i = 0; i < max; i++) {
    const s = servers[i];
    const cpu = getDisplayCpu(s);
    const status = getStatusForCpu(cpu);

    const connectionsEl = document.getElementById(`serverConnections-${i}`);
    const handledEl = document.getElementById(`serverHandled-${i}`);
    const cpuFillEl = document.getElementById(`serverCpuFill-${i}`);
    const cpuLabelEl = document.getElementById(`serverCpuLabel-${i}`);
    const statusEl = document.getElementById(`serverStatus-${i}`);
    const healthEl = document.getElementById(`serverHealth-${i}`);
    const nameEl = document.getElementById(`serverName-${i}`);

    if (nameEl) nameEl.textContent = s.name || s.server_name || s.id || `server-${i}`;
    if (statusEl) {
      statusEl.textContent = s.status || "running";
      statusEl.classList.remove("status-green", "status-yellow", "status-red");
      statusEl.classList.add(status.badge);
    }

    // Backend may not have these fields; fall back to `load`.
    const connections = safeGetNumber(s, "connections") ?? safeGetNumber(s, "load", 0);
    const handled = safeGetNumber(s, "requests_handled") ?? safeGetNumber(s, "requests", null) ?? safeGetNumber(s, "load", 0);

    if (connectionsEl) connectionsEl.textContent = String(Math.max(0, Math.round(connections)));
    if (handledEl) handledEl.textContent = String(Math.max(0, Math.round(handled)));

    if (cpuFillEl) cpuFillEl.style.width = `${cpu}%`;
    if (cpuLabelEl) cpuLabelEl.textContent = `${cpu}%`;

    if (healthEl) {
      healthEl.classList.remove("health-green", "health-yellow", "health-red");
      healthEl.classList.add(status.className);
    }

    if (cpu > CPU_THRESHOLDS.red) sawOverload = true;
  }

  if (sawOverload) {
    showAlert("Overload detected: CPU crossed the threshold on at least one server.");
  } else {
    hideAlert();
  }
}

function updateChartsFromServers(servers) {
  const timestampLabel = new Date().toLocaleTimeString();

  const serverNames = servers.map((s) => s.name || s.server_name || s.id).slice(0, 12);
  assignServerColors(serverNames);

  chartsState.timeLabels.push(timestampLabel);
  if (chartsState.timeLabels.length > 10) chartsState.timeLabels.shift();

  // Update each server series with the current snapshot.
  serverNames.forEach((name, idx) => {
    if (!chartsState.cpuSeriesByServer[name]) chartsState.cpuSeriesByServer[name] = [];
    const cpu = getDisplayCpu(servers[idx]);
    chartsState.cpuSeriesByServer[name].push(cpu);
    if (chartsState.cpuSeriesByServer[name].length > 10) chartsState.cpuSeriesByServer[name].shift();
  });

  // For servers that disappeared, pad series with null so x/y align.
  Object.keys(chartsState.cpuSeriesByServer).forEach((name) => {
    if (serverNames.indexOf(name) === -1) {
      chartsState.cpuSeriesByServer[name].push(null);
      if (chartsState.cpuSeriesByServer[name].length > 10) chartsState.cpuSeriesByServer[name].shift();
    }
  });

  const requestsValues = servers.map((s) => {
    return (
      safeGetNumber(s, "requests_handled") ??
      safeGetNumber(s, "requests", null) ??
      safeGetNumber(s, "load", 0) ??
      0
    );
  });

  // Bar chart: requestsChart
  const barCanvas = document.getElementById("requestsChart") || document.getElementById("requestsBarChart");
  if (barCanvas) {
    if (!requestsChart) {
      requestsChart = new Chart(barCanvas, {
        type: "bar",
        data: {
          labels: serverNames,
          datasets: [
            {
              label: "Requests",
              data: requestsValues,
              backgroundColor: THEME.primary,
              borderColor: "rgba(0,212,170,.65)",
              borderWidth: 1,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: (ctx) => `${ctx.parsed.y} requests`,
              },
            },
          },
          scales: {
            x: { ticks: { color: THEME.muted } },
            y: { ticks: { color: THEME.muted }, grid: { color: "rgba(255,255,255,.06)" } },
          },
        },
      });
    } else {
      requestsChart.data.labels = serverNames;
      requestsChart.data.datasets[0].data = requestsValues;
      requestsChart.update();
    }
  }

  // Line chart: loadChart (multi-line CPU per server)
  const lineCanvas = document.getElementById("loadLineChart");
  if (lineCanvas) {
    const datasets = Object.keys(chartsState.cpuSeriesByServer).map((serverName) => {
      const color = chartsState.colorByServer[serverName] || THEME.info;
      return {
        label: serverName,
        data: chartsState.cpuSeriesByServer[serverName],
        borderColor: color,
        backgroundColor: `${color}22`,
        tension: 0.25,
        pointRadius: 2,
      };
    });

    if (!loadChart) {
      loadChart = new Chart(lineCanvas, {
        type: "line",
        data: {
          labels: chartsState.timeLabels,
          datasets,
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { labels: { color: THEME.muted } },
            tooltip: {
              callbacks: {
                label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y ?? 0}% CPU`,
              },
            },
          },
          scales: {
            x: { ticks: { color: THEME.muted }, grid: { color: "rgba(255,255,255,.06)" } },
            y: {
              ticks: { color: THEME.muted },
              grid: { color: "rgba(255,255,255,.06)" },
              suggestedMin: 0,
              suggestedMax: 100,
            },
          },
        },
      });
    } else {
      loadChart.data.labels = chartsState.timeLabels;
      loadChart.data.datasets = datasets;
      loadChart.update();
    }
  }
}

async function updateDashboard() {
  // Only run on dashboard page.
  if (getPageKey() !== "dashboard") return;

  setGlobalSpinner(true);
  try {
    const servers = await fetchJSON("/api/servers");
    // Ensure stable ordering by server_name.
    const sorted = Array.isArray(servers)
      ? servers.slice().sort((a, b) => String(a.name || a.server_name).localeCompare(String(b.name || b.server_name)))
      : [];

    updateServerCards(sorted);

    // Stats bar.
    const totalReqEl = document.getElementById("statTotalRequests");
    const activeServersEl = document.getElementById("statActiveServers");
    const algoEl = document.getElementById("statAlgorithm");
    if (algoEl) {
      const sel = document.getElementById("algorithmSelect");
      algoEl.textContent = sel?.selectedOptions?.[0]?.text || "Round Robin";
    }

    if (activeServersEl) activeServersEl.textContent = String(sorted.length);
    if (totalReqEl) {
      const sum = sorted.reduce((acc, s) => {
        return acc + (safeGetNumber(s, "requests_handled") ?? safeGetNumber(s, "load", 0) ?? 0);
      }, 0);
      totalReqEl.textContent = String(Math.round(sum));
    }

    const avgRespEl = document.getElementById("statAvgResponseTime");
    if (avgRespEl) {
      // Best-effort: show average of the most recent history if the API supports it.
      // If it doesn't, keep the dashboard responsive (no extra fetch).
      avgRespEl.textContent = "--";
    }

    // Charts.
    updateChartsFromServers(sorted);
  } catch (e) {
    showToast(`Dashboard refresh failed: ${e.message}`, "error");
  } finally {
    setGlobalSpinner(false);
  }
}

async function sendRequest() {
  if (getPageKey() !== "dashboard") return;
  const btn = document.getElementById("sendRequestBtn");
  if (btn) btn.disabled = true;
  try {
    setGlobalSpinner(true);
    const data = await fetchJSON("/api/send-request", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });

    // Best-effort parse.
    const first = (data && data.results && data.results[0]) ? data.results[0] : null;
    const serverName = first?.server_name || first?.serverName || first?.server || "server";
    const latency = first?.simulated_latency_ms ?? first?.response_time ?? null;
    if (latency !== null && latency !== undefined) {
      showToast(`Request handled by ${serverName} (${latency} ms)`, first?.simulated_ok ? "success" : "warning");
    } else {
      showToast(`Request handled by ${serverName}`, first?.simulated_ok ? "success" : "warning");
    }

    await updateDashboard();
  } catch (e) {
    showToast(`Send request failed: ${e.message}`, "error");
  } finally {
    setGlobalSpinner(false);
    if (btn) btn.disabled = false;
  }
}

function ensureAutoSendProgressUI() {
  let wrapper = document.getElementById("autoSendProgressWrapper");
  if (!wrapper) {
    wrapper = document.createElement("div");
    wrapper.id = "autoSendProgressWrapper";
    wrapper.style.cssText =
      "display:flex; align-items:center; gap:10px; margin-left:8px; min-width:220px;";
    wrapper.innerHTML = `
      <div style="flex:1; height:10px; border-radius:999px; background:rgba(255,255,255,.06); border:1px solid rgba(255,255,255,.06); overflow:hidden;">
        <div id="autoSendProgressFill" style="height:100%; width:0%; background:linear-gradient(90deg, rgba(0,212,170,.9), rgba(74,158,255,.85)); transition: width .3s ease; box-shadow: 0 0 24px rgba(0,212,170,.18);"></div>
      </div>
      <span id="autoSendProgressText" style="font-weight:900; color:rgba(255,255,255,.85); font-size:13px;">0%</span>
    `;
    const parent = document.getElementById("autoSendBtn")?.parentElement || document.body;
    parent.appendChild(wrapper);
  }
  return wrapper;
}

async function autoSend(count) {
  if (getPageKey() !== "dashboard") return;
  const btn = document.getElementById("autoSendBtn");
  if (!btn) return;

  const progressUI = ensureAutoSendProgressUI();
  const fill = document.getElementById("autoSendProgressFill");
  const text = document.getElementById("autoSendProgressText");
  const prevDisabled = btn.disabled;
  btn.disabled = true;

  let isDone = false;
  let progress = 0;
  let timer = null;
  try {
    progress = 0;
    if (fill) fill.style.width = "0%";
    if (text) text.textContent = "0%";

    // Simulated progress while backend runs.
    timer = window.setInterval(() => {
      if (isDone) return;
      progress = Math.min(92, progress + Math.random() * 10);
      if (fill) fill.style.width = `${Math.round(progress)}%`;
      if (text) text.textContent = `${Math.round(progress)}%`;
    }, 220);

    setGlobalSpinner(true);
    await fetchJSON(`/api/auto-send/${count}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });

    isDone = true;
    progress = 100;
    if (fill) fill.style.width = "100%";
    if (text) text.textContent = "100%";

    showToast(`Auto Send complete (${count} requests)`, "success");
    await updateDashboard();
  } catch (e) {
    showToast(`Auto Send failed: ${e.message}`, "error");
  } finally {
    if (timer) window.clearInterval(timer);
    setGlobalSpinner(false);
    btn.disabled = prevDisabled;
    // Keep progress UI visible but at 100%.
    if (progressUI) {
      progressUI.style.opacity = "1";
    }
  }
}

async function setAlgorithm(name) {
  if (getPageKey() !== "dashboard" && getPageKey() !== "unknown") return;

  try {
    const displayName =
      name === "round_robin"
        ? "Round Robin"
        : name === "least_connections"
          ? "Least Connections"
          : name === "weighted"
            ? "Weighted"
            : name;

    setGlobalSpinner(true);
    await fetchJSON("/api/set-algorithm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ algorithm: name }),
    });
    showToast(`Switched to ${displayName}`, "success");
    await updateDashboard();
  } catch (e) {
    showToast(`Switch algorithm failed: ${e.message}`, "error");
  } finally {
    setGlobalSpinner(false);
  }
}

async function toggleDemoMode() {
  // This endpoint may not exist in your backend yet.
  const toggle = document.getElementById("demoModeToggle");
  if (!toggle) return;
  const enabled = Boolean(toggle.checked);

  try {
    setGlobalSpinner(true);
    await fetchJSON("/api/toggle-demo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ demo: enabled }),
    });
  } catch (e) {
    // Keep app running: if toggle isn't implemented server-side, just reload.
  } finally {
    setGlobalSpinner(false);
    window.location.reload();
  }
}

// --- COMPARE PAGE ---
function computeAlgoStatsFromCompareResponse(compareData) {
  // Expected from your backend:
  //   { predictions: { algoKey: {...} } }
  // We'll compute best-effort: total requests defaults to 1.
  const predictions = compareData?.predictions || {};
  const algoKeys = ["round_robin", "least_connections", "weighted"];

  const statsByAlgo = {};
  algoKeys.forEach((algo) => {
    const p = predictions[algo] || {};
    const totalRequests = p.total_requests ?? p.count ?? 1;
    const loadAfter = p.load_after ?? p.loadAfter ?? p.simulated_load_after ?? 0;

    // Balance score: higher is better; use an inverse function of max load.
    const maxServerLoad = Number.isFinite(Number(loadAfter)) ? Number(loadAfter) : 0;
    const balanceScore = Math.round(100 - Math.min(100, maxServerLoad) + (Math.min(100, maxServerLoad) === 0 ? 0 : 0));

    statsByAlgo[algo] = {
      totalRequests,
      maxServerLoad,
      balanceScore,
      predicted: p,
    };
  });

  // Choose winner: lowest max server load, then highest balance score.
  const sorted = Object.keys(statsByAlgo).sort((a, b) => {
    const A = statsByAlgo[a];
    const B = statsByAlgo[b];
    if (A.maxServerLoad !== B.maxServerLoad) return A.maxServerLoad - B.maxServerLoad;
    return B.balanceScore - A.balanceScore;
  });
  const winnerAlgo = sorted[0] || "round_robin";
  return { statsByAlgo, winnerAlgo };
}

async function runComparison() {
  if (getPageKey() !== "compare") return;

  setGlobalSpinner(true);
  try {
    const compareData = await fetchJSON("/api/compare");
    const { statsByAlgo, winnerAlgo } = computeAlgoStatsFromCompareResponse(compareData);

    const algoMeta = {
      round_robin: { title: "Round Robin", badgeId: "winner-badge-round_robin", chartId: "distChart-round_robin" },
      least_connections: {
        title: "Least Connections",
        badgeId: "winner-badge-least_connections",
        chartId: "distChart-least_connections",
      },
      weighted: { title: "Weighted", badgeId: "winner-badge-weighted", chartId: "distChart-weighted" },
    };

    // Charts (best-effort): each algo may only include one predicted server/load.
    Object.keys(algoMeta).forEach((algo) => {
      const meta = algoMeta[algo];
      const canvas = document.getElementById(meta.chartId);
      if (!canvas) return;

      const pred = statsByAlgo[algo].predicted || {};
      const serverName = pred.server_name || pred.serverName || "server";
      const loadAfter = statsByAlgo[algo].maxServerLoad;

      const labels = [serverName];
      const values = [loadAfter];

      const color =
        algo === "round_robin"
          ? THEME.primary
          : algo === "least_connections"
            ? THEME.info
            : THEME.warning;

      if (!compareCharts[algo]) {
        compareCharts[algo] = new Chart(canvas, {
          type: "bar",
          data: {
            labels,
            datasets: [
              {
                label: "Max server load (predicted)",
                data: values,
                backgroundColor: color,
                borderColor: "rgba(255,255,255,.22)",
                borderWidth: 1,
              },
            ],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { display: false },
            },
            scales: {
              x: { ticks: { color: THEME.muted } },
              y: { ticks: { color: THEME.muted }, grid: { color: "rgba(255,255,255,.06)" } },
            },
          },
        });
      } else {
        compareCharts[algo].data.labels = labels;
        compareCharts[algo].data.datasets[0].data = values;
        compareCharts[algo].update();
      }
    });

    // Winner badges.
    Object.keys(algoMeta).forEach((algo) => {
      const badge = document.getElementById(algoMeta[algo].badgeId);
      if (badge) badge.style.display = algo === winnerAlgo ? "inline-flex" : "none";
    });

    // Summary table.
    const body = document.getElementById("compareSummaryBody");
    if (body) {
      body.innerHTML = "";
      ["round_robin", "least_connections", "weighted"].forEach((algo) => {
        const s = statsByAlgo[algo];
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${algo.replaceAll("_", " ")}</td>
          <td>${s.totalRequests}</td>
          <td>${s.maxServerLoad}</td>
          <td>${s.balanceScore}</td>
        `;
        body.appendChild(tr);
      });
    }

    showToast(`Comparison complete. Winner: ${winnerAlgo.replaceAll("_", " ")}`, "success");
  } catch (e) {
    showToast(`Comparison failed: ${e.message}`, "error");
  } finally {
    setGlobalSpinner(false);
  }
}

// --- HISTORY PAGE ---
const historyState = {
  allRows: [],
  algorithm: "all",
  server: "all",
  page: 1,
  pageSize: 10,
};

function statusFromRow(row) {
  // Backend may use simulated_ok (from simulator).
  if (row.simulated_ok === true) return "OK";
  if (row.simulated_ok === false) return "OVERLOADED";
  // Fallback.
  const status = row.status ?? row.statusText ?? "";
  return status || "UNKNOWN";
}

function responseTimeFromRow(row) {
  return (
    row.response_time ??
    row.simulated_latency_ms ??
    row.latency_ms ??
    row.responseTime ??
    "--"
  );
}

function renderHistoryTable(rows, page) {
  const body = document.getElementById("historyTableBody");
  if (!body) return;

  const total = rows.length;
  const pageSize = historyState.pageSize;
  const start = (page - 1) * pageSize;
  const end = start + pageSize;
  const pageRows = rows.slice(start, end);

  body.innerHTML = "";
  pageRows.forEach((r) => {
    const tr = document.createElement("tr");
    const id = r.id ?? r.request_no ?? "";
    const time = r.created_at ?? r.timestamp ?? "";
    const algo = r.algorithm ?? "";
    const server = r.server_name ?? "";
    const rt = responseTimeFromRow(r);
    const st = statusFromRow(r);

    tr.innerHTML = `
      <td>${id}</td>
      <td>${time}</td>
      <td>${algo}</td>
      <td>${server}</td>
      <td>${rt}</td>
      <td>${st}</td>
    `;
    body.appendChild(tr);
  });

  const showing = document.getElementById("historyShowingMeta");
  if (showing) {
    const from = total === 0 ? 0 : start + 1;
    const to = Math.min(total, end);
    showing.textContent = `${from}-${to} `;
  }

  const pageMeta = document.getElementById("historyPageMeta");
  if (pageMeta) pageMeta.textContent = `Page ${page}`;

  const prevBtn = document.getElementById("historyPrevBtn");
  const nextBtn = document.getElementById("historyNextBtn");
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  if (prevBtn) prevBtn.disabled = page <= 1;
  if (nextBtn) nextBtn.disabled = page >= totalPages;
}

function applyHistoryFilters(rows, algorithm, server) {
  let filtered = Array.isArray(rows) ? rows.slice() : [];
  if (algorithm && algorithm !== "all") {
    filtered = filtered.filter((r) => String(r.algorithm || "").toLowerCase() === String(algorithm).toLowerCase());
  }
  if (server && server !== "all") {
    filtered = filtered.filter((r) => String(r.server_name || "").toLowerCase() === String(server).toLowerCase());
  }
  return filtered;
}

async function filterHistory() {
  if (getPageKey() !== "history") return;
  const algoSel = document.getElementById("historyAlgorithmSelect");
  const serverSel = document.getElementById("historyServerSelect");
  if (!algoSel || !serverSel) return;

  historyState.algorithm = algoSel.value;
  historyState.server = serverSel.value;
  historyState.page = 1;

  setGlobalSpinner(true);
  try {
    // Best-effort: pass query params; then filter client-side in case backend ignores them.
    const url = `/api/history?algorithm=${encodeURIComponent(historyState.algorithm)}&server=${encodeURIComponent(
      historyState.server
    )}`;
    const rows = await fetchJSON(url);
    const filtered = applyHistoryFilters(rows, historyState.algorithm, historyState.server);
    historyState.allRows = filtered;
    renderHistoryTable(filtered, historyState.page);
  } catch (e) {
    showToast(`History fetch failed: ${e.message}`, "error");
  } finally {
    setGlobalSpinner(false);
  }
}

function exportCSV() {
  if (getPageKey() !== "history") return;
  window.location = "/api/export-csv";
}

async function clearHistory() {
  if (getPageKey() !== "history") return;
  try {
    setGlobalSpinner(true);
    await fetchJSON("/api/clear-history", { method: "POST" });
  } catch (e) {
    // Endpoint may not exist yet; fall back to simple reload so UI doesn't break.
    showToast("Clear history is not available yet.", "warning");
  } finally {
    setGlobalSpinner(false);
    window.location.reload();
  }
}

function initComparePage() {
  const btn = document.getElementById("runComparisonBtn");
  if (!btn) return;
  btn.addEventListener("click", runComparison);
}

async function initHistoryPage() {
  // Populate server dropdown.
  const serverSel = document.getElementById("historyServerSelect");
  if (serverSel) {
    try {
      const servers = await fetchJSON("/api/servers");
      const names = (Array.isArray(servers) ? servers : [])
        .map((s) => s.server_name || s.name || s.id)
        .filter(Boolean);

      // Clear everything except the first "all" option.
      serverSel.innerHTML = `<option value="all">All</option>`;
      names.forEach((n) => {
        const opt = document.createElement("option");
        opt.value = n;
        opt.textContent = n;
        serverSel.appendChild(opt);
      });
    } catch (e) {
      // Keep dropdown as-is.
    }
  }

  const algoSel = document.getElementById("historyAlgorithmSelect");
  if (algoSel) algoSel.addEventListener("change", filterHistory);
  if (serverSel) serverSel.addEventListener("change", filterHistory);

  const exportBtn = document.getElementById("exportCsvBtn");
  if (exportBtn) exportBtn.addEventListener("click", exportCSV);

  const clearBtn = document.getElementById("clearHistoryBtn");
  if (clearBtn) clearBtn.addEventListener("click", clearHistory);

  const prevBtn = document.getElementById("historyPrevBtn");
  const nextBtn = document.getElementById("historyNextBtn");
  if (prevBtn) {
    prevBtn.addEventListener("click", () => {
      historyState.page = Math.max(1, historyState.page - 1);
      renderHistoryTable(historyState.allRows, historyState.page);
    });
  }
  if (nextBtn) {
    nextBtn.addEventListener("click", () => {
      historyState.page += 1;
      renderHistoryTable(historyState.allRows, historyState.page);
    });
  }

  // First render.
  await filterHistory();
}

function initDashboardPage() {
  const sendBtn = document.getElementById("sendRequestBtn");
  const autoBtn = document.getElementById("autoSendBtn");
  const algorithmSelect = document.getElementById("algorithmSelect");
  const setAlgorithmBtn = document.getElementById("setAlgorithmBtn");
  const toggle = document.getElementById("demoModeToggle");

  if (sendBtn) sendBtn.addEventListener("click", sendRequest);
  if (autoBtn) autoBtn.addEventListener("click", () => autoSend(100));
  if (algorithmSelect) algorithmSelect.addEventListener("change", (e) => setAlgorithm(e.target.value));
  if (setAlgorithmBtn && algorithmSelect) setAlgorithmBtn.addEventListener("click", () => setAlgorithm(algorithmSelect.value));
  if (toggle) toggle.addEventListener("change", toggleDemoMode);
}

async function initPage() {
  const page = getPageKey();

  // Initialize charts area for dashboard.
  // (Charts are created lazily in updateDashboard.)
  if (page === "dashboard") {
    initDashboardPage();
    await updateDashboard();
    window.setInterval(() => updateDashboard(), autoRefreshMs);
  } else if (page === "compare") {
    initComparePage();
    // Optionally run once immediately.
    await runComparison();
  } else if (page === "history") {
    await initHistoryPage();
  } else {
    // Unknown: no-op.
  }
}

// Start when DOM is ready.
document.addEventListener("DOMContentLoaded", () => {
  initPage();
});

