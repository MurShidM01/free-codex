const $ = (id) => document.getElementById(id);

async function fetchJSON(url, opts = {}) {
  const headers = { Accept: "application/json", ...(opts.headers || {}) };
  const tok = $("token").value.trim();
  if (tok) headers.Authorization = `Bearer ${tok}`;
  const res = await fetch(url, { ...opts, headers });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { raw: text };
  }
  if (!res.ok) {
    const err = new Error(res.statusText || "Request failed");
    err.status = res.status;
    err.body = data;
    throw err;
  }
  return data;
}

function showBanner(kind, msg) {
  const b = $("banner");
  b.hidden = false;
  b.className = `banner ${kind}`;
  b.textContent = msg;
}

function hideBanner() {
  const b = $("banner");
  b.hidden = true;
  b.textContent = "";
}

function setNimFields(base, key, model) {
  $("nim-base").value = base ?? "";
  $("nim-key").value = key ?? "";
  $("nim-model").value = model ?? "";
}

/** Parse ~/.env-style lines; skip masked placeholders. */
function fillNimFromEnvText(text) {
  const parsed = {};
  for (const line of text.split("\n")) {
    const s = line.trim();
    if (!s || s.startsWith("#") || !s.includes("=")) continue;
    const i = s.indexOf("=");
    const k = s.slice(0, i).trim();
    if (!k) continue;
    let v = s.slice(i + 1).trim();
    if (
      v.length >= 2 &&
      ((v[0] === '"' && v[v.length - 1] === '"') ||
        (v[0] === "'" && v[v.length - 1] === "'"))
    ) {
      v = v.slice(1, -1);
    }
    if (v === "***") continue;
    parsed[k] = v;
  }
  const b = parsed["NVIDIA_NIM_BASE_URL"];
  const apiKey = parsed["NVIDIA_NIM_API_KEY"];
  const m = parsed["NVIDIA_NIM_MODEL"];
  if (b) $("nim-base").value = b;
  if (apiKey) $("nim-key").value = apiKey;
  if (m) $("nim-model").value = m;
}

async function loadNimDefaultsAfterEnv() {
  try {
    const d = await fetchJSON("/admin/api/nim/defaults");
    setNimFields(d.base_url, d.api_key, d.model);
  } catch {
    fillNimFromEnvText($("env").value || "");
  }
}

function nimPayload() {
  const base = $("nim-base").value.trim();
  const key = $("nim-key").value.trim();
  const model = $("nim-model").value.trim();
  const o = {};
  if (base) o.base_url = base;
  if (key) o.api_key = key;
  if (model) o.model = model;
  return o;
}

function showNimResult(obj) {
  $("nim-result").textContent = JSON.stringify(obj, null, 2);
}

async function loadEnv() {
  hideBanner();
  $("hint").textContent = "";
  try {
    const data = await fetchJSON("/admin/api/env");
    $("env").value = data.content || "";
    const lines = (data.validation_errors || []).join("\n") || "(none)";
    $("validation").textContent =
      `validation_ok: ${data.validation_ok}\n${lines}`;
    $("validation").style.borderColor = data.validation_ok ? "#356845" : "#884444";
    if (data.masked) {
      showBanner(
        "ok",
        "Secrets masked. Use http://127.0.0.1/admin, or enter admin token + Unlock."
      );
    }
    await loadNimDefaultsAfterEnv();
  } catch (e) {
    showBanner("err", e.body?.detail || e.message || String(e));
  }
}

async function saveEnv() {
  hideBanner();
  $("hint").textContent = "";
  try {
    const body = JSON.stringify({ content: $("env").value });
    const data = await fetchJSON("/admin/api/env", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    showBanner("ok", data.hint || "Saved.");
    await loadEnv();
  } catch (e) {
    const detail = e.body?.detail || e.body?.validation_errors || e.message;
    showBanner("err", typeof detail === "object" ? JSON.stringify(detail) : detail);
  }
}

async function nimListModels() {
  $("nim-result").textContent = "Loading…";
  try {
    const data = await fetchJSON("/admin/api/nim/models", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(nimPayload()),
    });
    showNimResult(data);
  } catch (e) {
    showNimResult({ error: e.body?.detail || e.body || e.message });
  }
}

async function nimTestChat() {
  $("nim-result").textContent = "Testing…";
  try {
    const data = await fetchJSON("/admin/api/nim/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(nimPayload()),
    });
    showNimResult(data);
  } catch (e) {
    showNimResult({ error: e.body?.detail || e.body || e.message });
  }
}

document.getElementById("reload").addEventListener("click", loadEnv);
document.getElementById("unlock").addEventListener("click", loadEnv);
document.getElementById("save").addEventListener("click", saveEnv);
document.getElementById("nim-list").addEventListener("click", nimListModels);
document.getElementById("nim-test").addEventListener("click", nimTestChat);

loadEnv();
