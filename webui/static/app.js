const $ = (id) => document.getElementById(id);

function showTab(tab) {
  document.querySelectorAll(".view").forEach((el) => el.classList.remove("active"));
  document.querySelectorAll("nav button").forEach((el) => el.classList.remove("active"));
  $(tab).classList.add("active");
  document.querySelector(`[data-tab="${tab}"]`).classList.add("active");
}

async function api(path, body) {
  const res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: body ? {"Content-Type": "application/json"} : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    data = {stdout: text};
  }
  if (!res.ok) {
    throw new Error(data.detail || text || res.statusText);
  }
  return data;
}

function renderCommand(target, data) {
  target.textContent = JSON.stringify(data, null, 2);
  if (data.stdout) {
    target.textContent = data.stdout;
  }
}

async function loadStatus() {
  const data = await api("/api/status");
  const rows = [
    ["mode", data.mode],
    ["role", data.role?.stdout?.trim() || ""],
    ["hostname", data.hostname?.stdout?.trim() || ""],
    ["project", data.project_dir || ""],
    ["host project", data.host_project_dir || ""],
  ];
  $("statusTable").innerHTML = "<tr><th>项</th><th>值</th></tr>" + rows.map(([k, v]) => `<tr><td>${k}</td><td>${String(v)}</td></tr>`).join("");
  $("statusLog").textContent = JSON.stringify(data, null, 2);
}

function tcBody() {
  return {
    config: $("tcConfig").value,
    interface: $("tcInterface").value,
    dst_ip: $("tcDst").value || null,
    backend: "simple",
    allow_ssh_interface: true,
    auto_rollback_seconds: 35,
  };
}

async function loadResults() {
  const data = await api("/api/results");
  $("resultsTable").innerHTML = "<tr><th>路径</th><th>大小</th><th>修改时间</th></tr>" + data.results.map((row) => {
    const date = new Date(row.mtime * 1000).toLocaleString();
    return `<tr><td><span class="path-link" data-path="${row.path}">${row.path}</span></td><td>${row.size}</td><td>${date}</td></tr>`;
  }).join("");
}

document.querySelectorAll("nav button").forEach((btn) => {
  btn.addEventListener("click", () => showTab(btn.dataset.tab));
});

$("refresh").addEventListener("click", loadStatus);
$("tcDry").addEventListener("click", async () => renderCommand($("tcOutput"), await api("/api/tc/dry-run", tcBody())));
$("tcApply").addEventListener("click", async () => renderCommand($("tcOutput"), await api("/api/tc/apply", tcBody())));
$("tcStatus").addEventListener("click", async () => renderCommand($("tcOutput"), await api("/api/tc/status", tcBody())));
$("tcClear").addEventListener("click", async () => renderCommand($("tcOutput"), await api("/api/tc/clear", tcBody())));

$("streamStart").addEventListener("click", async () => {
  const body = {
    role: $("streamRole").value,
    dest: $("streamDest").value || null,
    port: Number($("streamPort").value),
    duration: Number($("streamDuration").value),
    source: "testsrc",
    output: "results/webui/received.ts",
  };
  renderCommand($("streamOutput"), await api("/api/stream/start", body));
});

$("yoloRun").addEventListener("click", async () => {
  const body = {
    model: $("yoloModel").value,
    source: $("yoloSource").value,
    max_frames: Number($("yoloFrames").value),
    device: $("yoloDevice").value,
  };
  renderCommand($("yoloOutput"), await api("/api/yolo/run", body));
});

$("loadResults").addEventListener("click", loadResults);
$("resultsTable").addEventListener("click", async (ev) => {
  if (!ev.target.classList.contains("path-link")) return;
  const path = ev.target.dataset.path;
  const res = await fetch(`/api/log?path=${encodeURIComponent(path)}`);
  $("filePreview").textContent = await res.text();
});

loadStatus().catch((err) => {
  $("statusLog").textContent = String(err);
});
