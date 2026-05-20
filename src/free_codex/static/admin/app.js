const $ = (id) => document.getElementById(id);

const BANNER_OK =
  "rounded-xl border px-4 py-3 text-sm leading-relaxed font-medium border-emerald-500/35 bg-emerald-950/40 text-emerald-200";
const BANNER_ERR =
  "rounded-xl border px-4 py-3 text-sm leading-relaxed font-medium border-red-500/40 bg-red-950/45 text-red-200";

const LIST_COUNT_OK =
  "inline-flex min-h-[1.375rem] items-center justify-center rounded-full bg-violet-500/25 px-2 text-xs font-bold tabular-nums text-violet-100 ring-1 ring-violet-400/35";
const RING_RADIUS = 8;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS; // ≈ 50.27

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
  const icon = document.createElement("span");
  icon.className = "mr-2 text-lg";
  icon.textContent = kind === "err" ? "✖" : "✔";
  const text = document.createElement("span");
  text.textContent = msg;
  b.innerHTML = "";
  b.appendChild(icon);
  b.appendChild(text);
}

function hideBanner() {
  const b = $("banner");
  b.hidden = true;
  b.textContent = "";
  b.className =
    "hidden rounded-xl border px-4 py-3 text-sm leading-relaxed font-medium";
}

function adjustEnvHeight() {
  const env = $("env");
  if (!env) return;
  env.style.height = "auto";
  const height = env.scrollHeight;
  env.style.height = `${height}px`;
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

function buildUpdatedEnvContent(currentContent, base, apiKey, model) {
  const required = {
    NVIDIA_NIM_BASE_URL: base,
    NVIDIA_NIM_API_KEY: apiKey,
    NVIDIA_NIM_MODEL: model,
  };
  const lines = currentContent.split("\n");
  const seen = new Set();
  const outLines = [];

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) {
      outLines.push(rawLine);
      continue;
    }
    const [key, ...rest] = rawLine.split("=");
    const name = key.trim();
    if (Object.prototype.hasOwnProperty.call(required, name)) {
      const value = required[name] ?? "";
      outLines.push(`${name}=${value}`);
      seen.add(name);
    } else {
      outLines.push(rawLine);
    }
  }

  for (const [name, value] of Object.entries(required)) {
    if (!seen.has(name)) {
      outLines.push(`${name}=${value}`);
    }
  }
  return outLines.join("\n");
}

function setValidationStyle(ok) {
  const v = $("validation");
  if (!v) return;
  v.classList.remove(
    "border-emerald-500/40",
    "border-red-500/45",
    "border-slate-700/80"
  );
  v.classList.add(ok ? "border-emerald-500/40" : "border-red-500/45");
}

function setValidateBadge(text, success) {
  const badge = $("validate-badge");
  if (!badge) return;
  badge.textContent = text;
  badge.classList.toggle("hidden", false);
  badge.classList.toggle("bg-emerald-500/25", success);
  badge.classList.toggle("text-emerald-100", success);
  badge.classList.toggle("ring-emerald-400/40", success);
  badge.classList.toggle("bg-red-500/20", !success);
  badge.classList.toggle("text-red-100", !success);
  badge.classList.toggle("ring-red-400/40", !success);
}

function clearValidateBadge() {
  const badge = $("validate-badge");
  if (!badge) return;
  badge.className =
    "hidden rounded-full bg-slate-800 px-3 py-1 text-xs font-semibold text-slate-200 ring-1 ring-slate-700";
  badge.textContent = "";
}

async function loadEnv() {
  hideBanner();
  $("hint").textContent = "";
  clearValidateBadge();
  try {
    const data = await fetchJSON("/admin/api/env");
    $("env").value = data.content || "";
    adjustEnvHeight();
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
      const current = $("env").value;
      const { base_url, api_key, model } = nimPayload();
      const content = buildUpdatedEnvContent(current, base_url || "", api_key || "", model || "");
      const body = JSON.stringify({ content });
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

async function validateEnv() {
  hideBanner();
  $("hint").textContent = "";
  clearValidateBadge();
  await withBtn($("validate"), async () => {
    try {
      const current = $("env").value;
      const { base_url, api_key, model } = nimPayload();
      const content = buildUpdatedEnvContent(current, base_url || "", api_key || "", model || "");
      const data = await fetchJSON("/admin/api/env/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      if (data.ok) {
        setValidateBadge("Valid", true);
        showBanner("ok", "File is valid.");
      } else {
        setValidateBadge("Invalid", false);
        showBanner("err", "File is not valid.");
      }
    } catch (e) {
      setValidateBadge("Error", false);
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

async function copyEnv() {
  const text = $("env").value;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.style.position = "fixed";
      textarea.style.left = "-9999px";
      textarea.style.top = "0";
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
    }
    showBanner("ok", "Environment content copied to clipboard.");
  } catch (e) {
    showBanner("err", "Unable to copy environment content.");
  }
}

$("reload").addEventListener("click", () => withBtn($("reload"), loadEnv));
$("unlock").addEventListener("click", () => withBtn($("unlock"), loadEnv));
$("save").addEventListener("click", saveEnv);
$("validate").addEventListener("click", validateEnv);
$("copy-env").addEventListener("click", copyEnv);
$("nim-list").addEventListener("click", nimListModels);
$("nim-test").addEventListener("click", nimTestChat);
window.addEventListener("resize", adjustEnvHeight);

loadEnv();

// Animated number counter
function animateValue(element, start, end, duration, isCurrency = false, decimals = 0) {
  if (!element) return;

  // Trigger glow animation
  element.classList.add('stat-value', 'updating-glow');

  const startTime = performance.now();
  const diff = end - start;

  function update(currentTime) {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);
    // Ease out cubic for smooth deceleration
    const easeOut = 1 - Math.pow(1 - progress, 3);
    const current = start + (diff * easeOut);

    if (isCurrency) {
      element.textContent = "$" + current.toFixed(decimals);
    } else {
      element.textContent = formatNumber(Math.round(current));
    }

    if (progress < 1) {
      requestAnimationFrame(update);
    } else {
      // Remove animation class when complete
      element.classList.remove('updating-glow');
    }
  }

  requestAnimationFrame(update);
}

// Track previous values for animation
const previousValues = {};

// Usage statistics polling
async function loadUsageStats() {
  try {
    const data = await fetchJSON("/admin/api/usage");

    // Use today & monthly + streak + costs from backend
    const today = data.today || {};
    const monthly = data.monthly || {};

    // Today stats with animation
    const todayReqs = today.requests ?? 0;
    animateValue($("stat-today-requests"), previousValues.todayRequests ?? 0, todayReqs, 600);
    animateValue($("stat-today-prompt"), previousValues.todayPrompt ?? 0, today.prompt_tokens ?? 0, 600);
    animateValue($("stat-today-completion"), previousValues.todayCompletion ?? 0, today.completion_tokens ?? 0, 600);
    animateValue($("stat-today-total"), previousValues.todayTotal ?? 0, today.total_tokens ?? 0, 600);
    const cToday = data.cost_today ?? ((today.prompt_tokens ?? 0) * 5 / 1e6 + (today.completion_tokens ?? 0) * 30 / 1e6);
    animateValue($("stat-today-cost"), previousValues.todayCost ?? 0, cToday, 600, true, 6);
    // Avg tokens per request
    const avgTokens = todayReqs > 0 ? Math.round((today.total_tokens ?? 0) / todayReqs) : 0;
    animateValue($("stat-today-avg-tokens"), previousValues.todayAvgTokens ?? 0, avgTokens, 600);

    // Monthly stats with animation
    animateValue($("stat-month-requests"), previousValues.monthRequests ?? 0, monthly.requests ?? 0, 600);
    animateValue($("stat-month-prompt"), previousValues.monthPrompt ?? 0, monthly.prompt_tokens ?? 0, 600);
    animateValue($("stat-month-completion"), previousValues.monthCompletion ?? 0, monthly.completion_tokens ?? 0, 600);
    animateValue($("stat-month-total"), previousValues.monthTotal ?? 0, monthly.total_tokens ?? 0, 600);
    const cMonth = data.cost_monthly ?? ((monthly.prompt_tokens ?? 0) * 5 / 1e6 + (monthly.completion_tokens ?? 0) * 30 / 1e6);
    animateValue($("stat-month-cost"), previousValues.monthCost ?? 0, cMonth, 600, true, 6);

    // Store previous values
    previousValues.todayRequests = todayReqs;
    previousValues.todayPrompt = today.prompt_tokens ?? 0;
    previousValues.todayCompletion = today.completion_tokens ?? 0;
    previousValues.todayTotal = today.total_tokens ?? 0;
    previousValues.todayCost = cToday;
    previousValues.todayAvgTokens = avgTokens;
    previousValues.monthRequests = monthly.requests ?? 0;
    previousValues.monthPrompt = monthly.prompt_tokens ?? 0;
    previousValues.monthCompletion = monthly.completion_tokens ?? 0;
    previousValues.monthTotal = monthly.total_tokens ?? 0;
    previousValues.monthCost = cMonth;

    // Streak (no animation for single value)
    if (data.streak_days !== undefined) {
      const streakText = data.streak_days + " day" + (data.streak_days === 1 ? '' : 's');
      $("stat-streak").textContent = streakText;
      $("stat-streak").title = `Current streak: ${data.streak_days} consecutive days with usage`;
    }

    // Reset countdown timer on successful refresh
    resetRefreshTimer();
  } catch (e) {
    console.error("Failed to load usage stats:", e);
  }
}

// Poll every 5 seconds
let refreshInterval = 5000; // ms
let lastRefresh = Date.now();
function updateCountdownRing() {
  const now = Date.now();
  const elapsed = now - lastRefresh;
  const remaining = Math.max(0, refreshInterval - elapsed);
  const progress = elapsed / refreshInterval; // 0 to 1
  // Countdown: ring starts FULL and empties as time passes
  const offset = RING_CIRCUMFERENCE * progress; // Starts at 0 (full), goes to full (empty)
  const ring = $("refresh-progress");
  const countdown = $("countdown");
  if (ring) {
    ring.style.strokeDasharray = RING_CIRCUMFERENCE;
    ring.style.strokeDashoffset = offset;
    // Color gradient: green → yellow → red as time passes
    if (progress < 0.5) {
      ring.setAttribute("stroke", "#22c55e"); // green-500
    } else if (progress < 0.8) {
      ring.setAttribute("stroke", "#eab308"); // yellow-500
    } else {
      ring.setAttribute("stroke", "#ef4444"); // red-500
    }
  }
  if (countdown) {
    countdown.textContent = (remaining / 1000).toFixed(1);
  }
}
function tick() {
  updateCountdownRing();
}
function startCountdownTimer() {
  setInterval(tick, 100);
}
function resetRefreshTimer() {
  lastRefresh = Date.now();
}
let pollHandle = setInterval(() => {
  loadUsageStats();
  resetRefreshTimer();
}, refreshInterval);
startCountdownTimer();
// Initial load after a short delay
setTimeout(() => { loadUsageStats(); resetRefreshTimer(); tick(); }, 2000);

// Token formatter: 1.2M, 1.5B, etc
function formatNumber(num) {
  if (num >= 1_000_000_000) return (num / 1_000_000_000).toFixed(2) + 'B';
  if (num >= 1_000_000) return (num / 1_000_000).toFixed(2) + 'M';
  if (num >= 1_000) return (num / 1_000).toFixed(1) + 'K';
  return num.toLocaleString();
}
