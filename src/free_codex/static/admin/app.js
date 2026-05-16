const $ = (id) => document.getElementById(id);

const BANNER_OK =
  "rounded-xl border px-4 py-3 text-sm leading-relaxed font-medium border-emerald-500/35 bg-emerald-950/40 text-emerald-200";
const BANNER_ERR =
  "rounded-xl border px-4 py-3 text-sm leading-relaxed font-medium border-red-500/40 bg-red-950/45 text-red-200";

const LIST_COUNT_OK =
  "inline-flex min-h-[1.375rem] items-center justify-center rounded-full bg-violet-500/25 px-2 text-xs font-bold tabular-nums text-violet-100 ring-1 ring-violet-400/35";

const TEST_WORKING =
  "inline-flex min-h-[1.375rem] items-center justify-center rounded-full bg-emerald-500/25 px-2.5 text-xs font-bold text-emerald-100 ring-1 ring-emerald-400/40";
const TEST_FAILED =
  "inline-flex min-h-[1.375rem] items-center justify-center rounded-full bg-red-500/20 px-2.5 text-xs font-bold text-red-100 ring-1 ring-red-400/40";

function setBtnLoading(btn, on) {
  if (!btn) return;
  const spin = btn.querySelector(".btn-spinner");
  const label = btn.querySelector(".btn-label");
  btn.disabled = !!on;
  btn.setAttribute("aria-busy", on ? "true" : "false");
  if (spin) spin.classList.toggle("hidden", !on);
  if (label) label.classList.toggle("opacity-75", on);
}

async function withBtn(btn, fn) {
  setBtnLoading(btn, true);
  try {
    await fn();
  } catch (e) {
    console.error("Operation failed:", e);
  } finally {
    setBtnLoading(btn, false);
  }
}

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
    const err = new Error(`${res.status} ${res.statusText}`);
    err.status = res.status;
    err.body = data;
    throw err;
  }
  return data;
}

function showBanner(kind, msg) {
  const b = $("banner");
  b.hidden = false;
  b.className = kind === "err" ? BANNER_ERR : BANNER_OK;
  b.textContent = msg;
}

function hideBanner() {
  const b = $("banner");
  b.hidden = true;
  b.textContent = "";
  b.className =
    "hidden rounded-xl border px-4 py-3 text-sm leading-relaxed font-medium";
}

function hideListCountBadge() {
  const el = $("nim-list-count");
  el.textContent = "0";
  el.className = LIST_COUNT_OK;
  el.hidden = true;
}

function showListCountBadge(data) {
  const el = $("nim-list-count");
  el.hidden = false;

  if (!data) {
    el.textContent = "ERR";
    el.className = TEST_FAILED;
    el.title = "No response from server";
    return;
  }

  // Check for explicit error
  if (data.error || data.raw_error) {
    el.textContent = "Failed";
    el.className = TEST_FAILED;
    el.title = data.raw_error || data.error || "Unknown error";
    return;
  }

  // check ok flag (boolean)
  if (data.ok === true) {
    el.textContent = String(data.model_count || "?");
    el.className = LIST_COUNT_OK;
    el.title = `Found ${data.model_count} models in ${data.elapsed_ms}ms`;
    return;
  }

  // If status code is 2xx but ok is false, still show success
  if (data.status_code && data.status_code >= 200 && data.status_code < 300) {
    el.textContent = String(data.model_count || "OK");
    el.className = LIST_COUNT_OK;
    el.title = `Connected (${data.elapsed_ms}ms)`;
    return;
  }

  // Check status code
  if (data.status_code === 401 || data.status_code === 403) {
    el.textContent = "Auth";
    el.className = TEST_FAILED;
    el.title = data.raw_error || "Authentication failed";
    return;
  }

  el.textContent = "Failed";
  el.className = TEST_FAILED;
  el.title = data.raw_error || `HTTP ${data.status_code}`;
}

function hideTestStatusBadge() {
  const el = $("nim-test-status");
  el.textContent = "";
  el.className =
    "hidden min-h-[1.375rem] items-center justify-center rounded-full px-2.5 text-xs font-bold ring-1";
  el.hidden = true;
}

function showTestStatusBadge(data) {
  const el = $("nim-test-status");
  el.hidden = false;

  if (!data) {
    el.textContent = "ERR";
    el.className = TEST_FAILED;
    el.title = "No response from server";
    return;
  }

  // Check for explicit error
  if (data.error || data.raw_error) {
    el.textContent = "Failed";
    el.className = TEST_FAILED;
    el.title = data.raw_error || data.error || "Unknown error";
    return;
  }

  // Check ok flag (boolean true = success)
  if (data.ok === true) {
    el.textContent = "Working";
    el.className = TEST_WORKING;
    el.title = `Response in ${data.elapsed_ms}ms: "${data.assistant_preview || '[no content]'}"`;
    return;
  }

  // If status code is 2xx but ok is not explicitly false, show success
  if (data.status_code && data.status_code >= 200 && data.status_code < 300) {
    el.textContent = "Working";
    el.className = TEST_WORKING;
    el.title = `Response in ${data.elapsed_ms}ms`;
    return;
  }

  // Handle authentication errors
  if (data.status_code === 401 || data.status_code === 403) {
    el.textContent = "Auth";
    el.className = TEST_FAILED;
    el.title = "Invalid or missing API key";
    return;
  }

  // Handle other error codes
  if (data.status_code) {
    el.textContent = "HTTP " + data.status_code;
    el.className = TEST_FAILED;
    el.title = data.raw_error || `Server returned ${data.status_code}`;
    return;
  }

  // Fallback
  el.textContent = "Failed";
  el.className = TEST_FAILED;
  el.title = data.raw_error || "Connection failed";
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

function setValidationStyle(ok) {
  const v = $("validation");
  v.classList.remove(
    "border-emerald-500/40",
    "border-red-500/45",
    "border-slate-700/80"
  );
  v.classList.add(ok ? "border-emerald-500/40" : "border-red-500/45");
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
    setValidationStyle(data.validation_ok);
    if (data.masked) {
      showBanner(
        "ok",
        "Secrets masked. Open via http://127.0.0.1/admin, or enter admin token + Unlock."
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
  await withBtn($("save"), async () => {
    try {
      const body = JSON.stringify({ content: $("env").value });
      const data = await fetchJSON("/admin/api/env", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      });
      showBanner("ok", data.hint || "Saved successfully.");
      await loadEnv();
    } catch (e) {
      const detail = e.body?.detail || e.body?.validation_errors || e.message;
      showBanner(
        "err",
        typeof detail === "object" ? JSON.stringify(detail) : detail
      );
    }
  });
}

async function nimListModels() {
  await withBtn($("nim-list"), async () => {
    try {
      const data = await fetchJSON("/admin/api/nim/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nimPayload()),
      });
      showListCountBadge(data);
    } catch (e) {
      showListCountBadge({
        error: e.body?.detail || e.body || e.message || "Request failed",
      });
    }
  });
}

async function nimTestChat() {
  await withBtn($("nim-test"), async () => {
    try {
      const data = await fetchJSON("/admin/api/nim/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nimPayload()),
      });
      showTestStatusBadge(data);
    } catch (e) {
      showTestStatusBadge({
        error: e.message || e.body?.detail || e.body || "Request failed",
      });
    }
  });
}

$("reload").addEventListener("click", () => withBtn($("reload"), loadEnv));
$("unlock").addEventListener("click", () => withBtn($("unlock"), loadEnv));
$("save").addEventListener("click", saveEnv);
$("nim-list").addEventListener("click", nimListModels);
$("nim-test").addEventListener("click", nimTestChat);

loadEnv();