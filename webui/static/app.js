const state = {
  auth: null,
  status: null,
  assets: null,
  bootstrap: null,
  diagnostics: null,
  openapi: null,
  selectedRunId: null,
};

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const token = localStorage.getItem("jetsonWebuiToken") || "";
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (token) headers["X-Auth-Token"] = token;
  const res = await fetch(path, {
    headers,
    ...options,
  });
  if (res.status === 401) {
    const nextToken = window.prompt("Access token");
    if (nextToken) {
      localStorage.setItem("jetsonWebuiToken", nextToken);
      return api(path, options);
    }
  }
  const body = await res.json();
  if (!res.ok) {
    throw new Error(body.error || `request failed: ${res.status}`);
  }
  return body;
}

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setOutput(id, value) {
  $(id).textContent = typeof value === "string" ? value : pretty(value);
}

function showTab(tab) {
  document.querySelectorAll(".nav-button").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === tab);
  });
}

function statusCard(label, value) {
  const div = document.createElement("div");
  div.className = "status-card";
  div.innerHTML = `<div class="status-label">${escapeHtml(label)}</div><div class="status-value">${escapeHtml(value ?? "unknown")}</div>`;
  return div;
}

async function loadAuthInfo() {
  state.auth = await api("/api/auth", { headers: {} });
  return state.auth;
}

async function setAccessToken() {
  const current = localStorage.getItem("jetsonWebuiToken") || "";
  const nextToken = window.prompt("Access token", current);
  if (nextToken !== null) {
    localStorage.setItem("jetsonWebuiToken", nextToken.trim());
    await refreshAll();
  }
}

async function clearAccessToken() {
  localStorage.removeItem("jetsonWebuiToken");
  await loadAuthInfo();
  $("subtitle").textContent = state.auth.auth_required ? "token required" : "local/open";
}

async function loadStatus() {
  state.status = await api("/api/status");
  $("subtitle").textContent = `${state.status.hostname} | v${state.status.version.version} | ${state.status.is_jetson ? "Jetson detected" : "local preview"} | ${state.status.time}`;
  const grid = $("statusGrid");
  grid.innerHTML = "";
  grid.appendChild(statusCard("L4T", state.status.l4t || "not detected"));
  grid.appendChild(statusCard("Config", state.status.paths.pipeline_config));
  grid.appendChild(statusCard("Assets", state.status.paths.asset_root));
  grid.appendChild(statusCard("Release", state.status.paths.release_root));
  grid.appendChild(statusCard("tegrastats", state.status.commands.tegrastats ? "available" : "missing"));
  grid.appendChild(statusCard("GStreamer", state.status.commands["gst-launch-1.0"] ? "available" : "missing"));
  grid.appendChild(statusCard("Auth", state.status.auth_required ? "token required" : "local/open"));
  grid.appendChild(statusCard("Strict 1024", `${state.status.known_results.strict_1024_single_cpp_fps} FPS`));
  grid.appendChild(statusCard("1024 cascade", `${state.status.known_results.cascade_1024_requested400_actual416_fps} FPS`));
}

function renderReadiness() {
  const data = state.bootstrap;
  const list = $("readinessList");
  list.innerHTML = "";
  if (!data) return;

  $("bootstrapSummary").textContent = data.ok ? "ready" : "needs attention";
  data.readiness.forEach((item) => {
    const div = document.createElement("div");
    const cls = item.ok ? "ok" : item.severity === "warning" ? "warn" : "bad";
    div.className = `check-item ${cls}`;
    div.innerHTML = [
      `<div class="check-state">${item.ok ? "OK" : item.severity === "warning" ? "WARN" : "FAIL"}</div>`,
      `<div><div class="item-name">${escapeHtml(item.label)}</div><div class="item-path">${escapeHtml(item.detail)}</div></div>`,
    ].join("");
    list.appendChild(div);
  });
  setOutput("bootstrapOutput", {
    asset_counts: data.asset_counts,
    selected_defaults: data.selected_defaults,
    security: data.security,
  });
}

async function loadBootstrap() {
  state.bootstrap = await api("/api/bootstrap");
  renderReadiness();
}

async function initializeConfig() {
  const result = await api("/api/bootstrap", {
    method: "POST",
    body: JSON.stringify({ write_config: true, force: true }),
  });
  setOutput("bootstrapOutput", result);
  await loadConfig();
  await loadBootstrap();
}

async function loadDiagnostics() {
  state.diagnostics = await api("/api/diagnostics");
  setOutput("diagnosticsOutput", {
    ok: state.diagnostics.ok,
    bootstrap_ok: state.diagnostics.bootstrap_ok,
    version: state.diagnostics.version,
    asset_counts: state.diagnostics.asset_counts,
    systemd: state.diagnostics.systemd,
    commands: state.diagnostics.commands,
    security: state.diagnostics.security,
  });
}

async function loadConfig() {
  const data = await api("/api/config");
  $("configPath").textContent = data.path;
  $("configText").value = data.text || "";
  setOutput("configValidation", data.validation);
}

async function saveConfig() {
  const data = await api("/api/config", {
    method: "POST",
    body: JSON.stringify({ text: $("configText").value }),
  });
  setOutput("configValidation", data.validation);
}

async function validateConfig() {
  const run = await api("/api/run", {
    method: "POST",
    body: JSON.stringify({ action: "validate_config", params: {} }),
  });
  await loadRuns();
  await showRun(run.id);
}

function renderList(id, items, onClick) {
  const el = $(id);
  el.innerHTML = "";
  if (!items || items.length === 0) {
    el.innerHTML = `<div class="item-meta">No items found.</div>`;
    return;
  }
  items.slice(0, 80).forEach((item) => {
    const div = document.createElement("div");
    div.className = "list-item";
    div.innerHTML = `<div class="item-name">${escapeHtml(item.name)}</div><div class="item-path">${escapeHtml(item.path)}</div><div class="item-meta">${escapeHtml(item.bytes ?? "")}</div>`;
    div.addEventListener("click", () => onClick(item));
    el.appendChild(div);
  });
}

async function loadAssets() {
  state.assets = await api("/api/assets");
  renderList("videoList", state.assets.videos, (item) => {
    $("videoPath").value = item.path;
    showTab("tests");
  });
  renderList("engineList", state.assets.engines, (item) => {
    if (!$("stage1Engine").value) $("stage1Engine").value = item.path;
    else $("stage2Engine").value = item.path;
    showTab("tests");
  });
  renderList("modelList", state.assets.models, () => {});
  renderList("reportList", state.assets.reports, (item) => loadLog(item.path));
  renderList("logList", state.assets.logs, (item) => loadLog(item.path));

  const firstVideo = state.assets.videos.find((v) => v.name.includes("1080p")) || state.assets.videos[0];
  if (firstVideo && !$("videoPath").value) $("videoPath").value = firstVideo.path;
}

function testParams() {
  return {
    video: $("videoPath").value.trim(),
    stage1_engine: $("stage1Engine").value.trim(),
    stage2_engine: $("stage2Engine").value.trim(),
    warmup: Number($("warmup").value || 5),
    measure: Number($("measure").value || 30),
    slots: Number($("slots").value || 4),
  };
}

async function startAction(action) {
  const run = await api("/api/run", {
    method: "POST",
    body: JSON.stringify({ action, params: testParams() }),
  });
  state.selectedRunId = run.id;
  await loadRuns();
  await showRun(run.id);
}

async function loadRuns() {
  const data = await api("/api/runs");
  const el = $("runList");
  el.innerHTML = "";
  data.runs.forEach((run) => {
    const div = document.createElement("div");
    div.className = "run-item";
    div.innerHTML = `<div class="item-name">${escapeHtml(run.action)} <span class="pill ${escapeHtml(run.status)}">${escapeHtml(run.status)}</span></div><div class="item-meta">${escapeHtml(run.id)}</div><div class="item-path">${escapeHtml(run.created_at)}</div>`;
    div.addEventListener("click", () => showRun(run.id));
    el.appendChild(div);
  });
}

async function loadOpenApi() {
  state.openapi = await api("/api/openapi.json");
  setOutput("openApiSpec", state.openapi);
  const base = $("apiBaseUrl").value.trim() || window.location.origin;
  const examples = [
    `curl -fsS ${base}/api/health`,
    `curl -fsS ${base}/api/auth`,
    `curl -fsS -H "X-Auth-Token: <token>" ${base}/api/status`,
    `curl -fsS -H "X-Auth-Token: <token>" ${base}/api/bootstrap`,
    `curl -fsS -H "X-Auth-Token: <token>" ${base}/api/actions`,
    `curl -fsS -H "X-Auth-Token: <token>" ${base}/api/diagnostics`,
    `curl -fsS -H "X-Auth-Token: <token>" ${base}/api/openapi.json`,
    `curl -fsS -H "X-Auth-Token: <token>" -H "Content-Type: application/json" -d '{"action":"validate_config","params":{}}' ${base}/api/run`,
  ].join("\\n\\n");
  setOutput("apiExamples", examples);
}

async function showRun(id) {
  state.selectedRunId = id;
  const run = await api(`/api/runs/${id}`);
  setOutput("runLog", `${pretty(run)}\n\n${run.log_tail || ""}`);
}

async function loadLog(path) {
  showTab("logs");
  const data = await api(`/api/log?path=${encodeURIComponent(path)}`);
  setOutput("logTail", `${data.path}\n\n${data.tail}`);
}

async function refreshAll() {
  await loadAuthInfo();
  await loadStatus();
  await loadBootstrap();
  await loadDiagnostics();
  await loadConfig();
  await loadAssets();
  await loadRuns();
  await loadOpenApi();
}

function wireEvents() {
  document.querySelectorAll(".nav-button").forEach((btn) => {
    btn.addEventListener("click", () => showTab(btn.dataset.tab));
  });
  $("setToken").addEventListener("click", setAccessToken);
  $("clearToken").addEventListener("click", clearAccessToken);
  $("refreshAll").addEventListener("click", refreshAll);
  $("loadConfig").addEventListener("click", loadConfig);
  $("initializeConfig").addEventListener("click", initializeConfig);
  $("loadDiagnostics").addEventListener("click", loadDiagnostics);
  $("saveConfig").addEventListener("click", saveConfig);
  $("validateConfig").addEventListener("click", validateConfig);
  $("refreshLogs").addEventListener("click", loadAssets);
  $("loadOpenApi").addEventListener("click", loadOpenApi);
  document.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => startAction(btn.dataset.action));
  });
  setInterval(async () => {
    if (state.selectedRunId) {
      try {
        await showRun(state.selectedRunId);
        await loadRuns();
      } catch (_) {
        // Keep the UI responsive if a run disappears.
      }
    }
  }, 2500);
}

wireEvents();
refreshAll().catch((err) => {
  $("subtitle").textContent = err.message;
  setOutput("configValidation", err.stack || err.message);
});
