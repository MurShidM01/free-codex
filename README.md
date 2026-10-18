# Free Codex — OmniRoute local AI multiplexer

> **One stable local OpenAI-compatible URL for Codex, VS Code, scripts, and multiple AI backends.**

Free Codex is a Python 3.9+ FastAPI proxy for the OpenAI Codex CLI and Codex VS Code extension. It keeps every client pointed at one local base URL—normally `http://127.0.0.1:8080/v1`—while a provider router selects NVIDIA NIM, Ollama, a local server, a custom OpenAI-compatible endpoint, or browser-mediated Puter Web behind the scenes.

It preserves the existing Responses API bridge, Chat Completions compatibility route, legacy Completions route, SSE conversion, workspace-context injection, tool normalization, usage tracking, retries, cache, admin UI, and `fc-init` / `fc-server` / `fc-codex` commands.

## The stable client contract

```text
Codex CLI / Codex VS Code / OpenAI-compatible client
                         |
                         |  always http://127.0.0.1:8080/v1
                         v
                 Free Codex local proxy
                 Provider Router + Responses bridge
                  /          |             |            \
                 v           v             v             v
          NVIDIA NIM      Ollama      Custom/local     Puter Web
       OpenAI-compatible  /v1 API      /v1 API       hidden Chromium
                                                        + Puter.js
```

The client **never** receives an upstream base URL, provider key, Puter cookie, or browser bridge URL. Switching providers changes router configuration or an optional local command flag; it does not require changing Codex's local `base_url`.

For Puter Web the route is deliberately browser-mediated:

```text
Codex / VS Code
      -> local POST /v1/responses or /v1/chat/completions
      -> Free Codex Provider Router
      -> background Chromium/Playwright page
      -> official https://js.puter.com/v2/ Puter.js SDK
      -> selected Puter model
      -> streamed text / function-call events
      -> local browser bridge -> Free Codex SSE -> Codex
```

Free Codex does **not** use Puter's paid OpenAI-compatible endpoint for `puter_web`, does not scrape Puter's private chat website, does not reverse engineer undocumented APIs, and does not bypass quotas, sign-in controls, or subscriptions.

---

## Endpoints

All endpoints are served below the same local `/v1` URL.

| Endpoint | Status | Purpose |
|---|---|---|
| `POST /v1/responses` | Preferred | Agentic Responses API, workspace context, tools, streaming SSE |
| `POST /v1/responses/stream` | Compatible alias | Explicit Responses streaming route |
| `POST /v1/chat/completions` | Compatible | OpenAI Chat Completions clients |
| `POST /v1/completions` | Legacy | Legacy text-completion clients |
| `GET /v1/models` | Discovery | Local aliases and selected provider/model metadata |
| `GET /v1/providers` | Discovery | Sanitized provider readiness, routing, and capabilities |
| `GET /health/json` | Health | Local proxy health plus provider readiness |
| `GET /v1/system` | Discovery | Local proxy capabilities |

`/v1/responses` is converted once to a provider-neutral Chat message representation and then routed. This avoids separate Responses-to-upstream implementations per provider.

---

## Quick start: existing NVIDIA NIM users

### 1. Install

```bash
uv tool install git+https://github.com/MurShidM01/free-codex.git
# or from a checkout
uv sync
```

### 2. Initialize

```bash
fc-init
```

This creates:

- `~/.config/free-codex/.env` — legacy NVIDIA variables and router environment values
- `~/.config/free-codex/providers.toml` — multi-provider router configuration
- `~/.config/free-codex/config.toml` — Codex config that points only to Free Codex

Existing NIM `.env` files continue to work unchanged:

```env
NVIDIA_NIM_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_NIM_API_KEY=your_nvidia_api_key
NVIDIA_NIM_MODEL=minimaxai/minimax-m2.7
```

### 3. Start the local proxy

```bash
fc-server
```

### 4. Start Codex in another terminal

```bash
fc-codex
```

The generated Codex configuration uses:

```toml
[model_providers.free_codex_nim]
base_url = "http://127.0.0.1:8080/v1"
wire_api = "responses"
```

No upstream endpoint or credential belongs in Codex's `config.toml`.

---

## Provider router configuration

`~/.config/free-codex/providers.toml` is optional for legacy NIM users, but is the recommended place to configure several providers at once.

```toml
[routing]
default_provider = "nvidia"
# Map exact client model names to provider/model targets.
model_routes = {
  "puter/deepseek-flash" = "puter_web::deepseek/deepseek-v4.1-flash",
  "local-fast" = "ollama::llama3.2"
}
# Friendly aliases are resolved before exact routes.
aliases = {
  "puter/qwen-cyber" = "puter_web::qwen/qwen3.8-27b-abliterated-cyber:free"
}
# Optional and explicit only. Tool-result turns do not silently fail over.
fallback_providers = ["ollama"]
sticky_sessions = true

[providers.nvidia]
type = "nvidia_nim"
enabled = true
# NVIDIA_NIM_* from .env remain the default base URL/key/model source.

[providers.ollama]
type = "ollama"
enabled = true
base_url = "http://127.0.0.1:11434/v1"
default_model = "llama3.2"

[providers.local]
type = "local"
enabled = false
base_url = "http://127.0.0.1:8000/v1"
default_model = "your-vllm-model"

[providers.custom_team]
type = "custom_openai"
enabled = true
base_url = "https://api.example.com/v1"
api_key_env = "TEAM_API_KEY"
default_model = "team-model"

[providers.puter_web]
type = "puter_web"
enabled = true
default_model = "deepseek/deepseek-v4.1-flash"
headless = true
browser = "chromium"
max_concurrent_requests = 1

[providers.puter_web.aliases]
"puter/deepseek-flash" = "deepseek/deepseek-v4.1-flash"
"puter/qwen-cyber" = "qwen/qwen3.8-27b-abliterated-cyber:free"

# Only turn on a capability after testing that exact model through Puter.js.
[providers.puter_web.model_capabilities."deepseek/deepseek-v4.1-flash"]
text_input = true
streaming = true
tool_calling = true
parallel_tool_calls = true
image_input = false
video_input = false
structured_output = false
reasoning = false
```

### Routing choices

A request may be selected by, in priority order:

1. a local `provider` request field, `metadata.free_codex_provider`, or `X-Free-Codex-Provider` header;
2. a configured alias or exact `model_routes` entry;
3. a model prefix such as `puter_web:deepseek/deepseek-v4.1-flash`;
4. the global `[routing].default_provider` / `FREE_CODEX_DEFAULT_PROVIDER`.

A configured provider/model route is sticky for a Responses conversation when `previous_response_id` is used. Explicit fallback is available only with `free_codex_fallback: true` (or `metadata.free_codex_fallback: true`), and Free Codex does not silently switch provider during a tool-result turn.

### Environment alternatives

The original NIM variables are fully backward-compatible. Other built-in provider variables are:

```env
FREE_CODEX_DEFAULT_PROVIDER=ollama
OLLAMA_ENABLED=1
OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
OLLAMA_MODEL=llama3.2

CUSTOM_OPENAI_ENABLED=1
CUSTOM_OPENAI_BASE_URL=https://api.example.com/v1
CUSTOM_OPENAI_API_KEY=optional_key
CUSTOM_OPENAI_MODEL=your-model
```

Use `FREE_CODEX_PROVIDERS_CONFIG` to point at a different router TOML file. `FREE_CODEX_MODEL_ROUTES` and `FREE_CODEX_MODEL_ALIASES` accept JSON mappings for container/automation deployments.

---

## Selecting a provider for one Codex session

`fc-codex` preserves your persistent config. Its route flags create a temporary Codex config for that process only:

```bash
# Current session only; no config file is changed.
fc-codex --provider ollama --model llama3.2
fc-codex --provider puter-web --model deepseek/deepseek-v4.1-flash
fc-codex --model puter/deepseek-flash
```

Internally, Free Codex encodes the process-only choice as a local model route and strips it before upstream dispatch. Codex still only sees `http://127.0.0.1:8080/v1`.

For initial setup:

```bash
fc-init --provider nvidia
fc-init --provider ollama --model llama3.2
fc-init --provider puter-web --model deepseek/deepseek-v4.1-flash
# Optional menu:
fc-init --interactive
```

---

## Puter Web setup

### What it is

`puter_web` uses a managed local browser page that loads the **official** Puter.js SDK from `https://js.puter.com/v2/`. It is not the paid Puter OpenAI-compatible HTTP endpoint and it does not accept Puter tokens in Codex configuration.

Normal operation is hidden/headless. Free Codex never shows a Puter chat page, model playground, messages, or a browser tab in its normal UI/admin UI.

### Install browser support

Browser automation is optional, so NIM/Ollama/custom installations remain lightweight:

```bash
pip install 'free-codex[puter]'
python -m playwright install chromium
```

With `uv` from a checkout:

```bash
uv sync --extra puter
uv run python -m playwright install chromium
```

A system Chrome/Chromium/Edge executable can be selected with `PUTER_WEB_BROWSER` or `browser` in the provider TOML. Supported values include `chromium`, `chrome`, `edge`, or a filesystem path. Profile paths are handled with `pathlib` and work on Windows, macOS, and Linux.

### One-time sign-in

```bash
# Opens the only visible authentication window.
fc-puter-auth
# Alias:
fc-puter-login
```

Sign in yourself through the documented Puter.js authentication flow. Free Codex persists the browser profile at `PUTER_WEB_PROFILE_DIR` (default `~/.config/free-codex/puter-profile`) and does not read, print, or place cookies/tokens in `.env` or Codex config.

After sign-in:

```bash
PUTER_WEB_ENABLED=1
PUTER_WEB_MODEL=deepseek/deepseek-v4.1-flash
FREE_CODEX_DEFAULT_PROVIDER=puter_web
fc-server
fc-codex --provider puter-web --model deepseek/deepseek-v4.1-flash
```

If authentication is needed, `fc-codex` preflights the local proxy and gives the concise action: **run `fc-puter-auth`**. If Playwright/browser support is missing, other providers continue to work and Puter requests return an actionable `Puter Web is not initialized` error rather than crashing the server.

### Puter browser settings

| Variable | Default | Meaning |
|---|---:|---|
| `PUTER_WEB_ENABLED` | `0` | Enable the Puter Web provider |
| `PUTER_WEB_MODEL` | empty | Default Puter model ID |
| `PUTER_WEB_BROWSER` | `chromium` | Playwright channel or Chromium executable path |
| `PUTER_WEB_HEADLESS` | `1` | Hidden/background browser during normal use |
| `PUTER_WEB_PROFILE_DIR` | Free Codex profile dir | Persistent authenticated browser profile |
| `PUTER_WEB_AUTH_TIMEOUT` | `300` | Interactive sign-in wait in seconds |
| `PUTER_WEB_CONNECT_TIMEOUT` | `30` | Local bridge connect timeout |
| `PUTER_WEB_SESSION_TIMEOUT` | `3600` | Nonce-bound bridge session lifetime |
| `PUTER_WEB_REQUEST_TIMEOUT` | `900` | Per-request ceiling for long thinking responses |
| `PUTER_WEB_MAX_CONCURRENT_REQUESTS` | `1` | Browser-side provider concurrency |

### Tools, streaming, and media

Free Codex sends the requested message history, sampling controls, tool definitions, tool choice, parallel-tool preference, and supported response-format controls to the documented `puter.ai.chat()` path in the hidden page. Browser events are translated into Chat Completions SSE and then complete Responses SSE events such as:

- `response.created`, `response.in_progress`
- `response.output_item.added`, `response.output_text.delta`, `response.output_text.done`
- `response.function_call_arguments.delta`, `response.function_call_arguments.done`
- `response.output_item.done`, `response.completed`, `response.failed`, and `error`

The browser runtime **never executes shell, code, filesystem, or other arbitrary tools**. When a model requests a function, Free Codex returns that function call to Codex with stable `call_id` values. Codex/the existing local tool authority executes it. On the next Responses request, a `function_call_output` is normalized to a tool result and forwarded back to the same browser conversation. Multiple calls are preserved.

Image input is accepted at the local OpenAI-compatible API only when the selected provider/model advertises `image_input: true`; otherwise Free Codex returns an explicit unsupported-modality error rather than silently dropping an image. Video is disabled unless the exact model has a verified `video_input: true` override. The same conservative policy applies to structured output and reasoning fields.

---

## Capability and health discovery

```bash
curl http://127.0.0.1:8080/v1/providers
curl http://127.0.0.1:8080/v1/models
curl http://127.0.0.1:8080/health/json
```

Each provider/model can report only these implemented/configured capabilities:

- `text_input`, `image_input`, `video_input`
- `streaming`, `tool_calling`, `parallel_tool_calls`
- `structured_output`, `reasoning`, `embeddings`
- `context_window`, `max_output_tokens`, `provider_notes`

`GET /v1/providers` and the **AI Providers** section at `http://127.0.0.1:8080/admin` show provider status, selected defaults, capabilities, browser/auth state, active background request count, and sanitized last error. They never show cookies, auth tokens, full prompts, raw tool payloads, or chat content.

---

## Security model

The browser bridge is intentionally narrow:

- cryptographically random session IDs and nonces;
- loopback-only bridge page/WebSocket validation by default;
- strict local Host/Origin checks, one active browser consumer, request correlation IDs, and expired sessions;
- ignored late/replayed request events;
- heartbeat/ping, browser crash/navigation detection, request timeout, cancellation, and cleanup on server shutdown;
- no arbitrary cross-origin command channel;
- persistent browser profile directory is owner-only on POSIX where supported.

Provider logs are structured JSON with routing metadata only:

```text
request_id, provider, model, protocol, stream, latency_ms,
status, tool_call_count, retry_count, error_type
```

Prompts, outputs, API keys, authorization headers, cookies, tool arguments, and uploaded media are redacted by default. `FREE_CODEX_DEBUG_PROVIDER_PAYLOADS=1` is an explicit diagnostic switch; hard credentials/cookies remain redacted.

Upstream terms, quotas, rate limits, access controls, and model availability still apply. Free Codex does not promise unlimited usage.

---

## Admin UI

Open `http://127.0.0.1:8080/admin`.

- Existing NVIDIA NIM editing/probing remains available.
- **AI Providers** shows NVIDIA, Ollama, local/custom OpenAI-compatible, and Puter Web status/capabilities.
- Provider test/select/toggle endpoints are admin-protected and expose only sanitized state.
- Puter Web is represented only by readiness/authentication state; it is never embedded as a visible Puter website or chat UI.

Set `FREE_CODEX_ADMIN_TOKEN` before exposing admin actions beyond trusted localhost.

---

## Reliability behavior

- Client rate limiting is charged once per local request; internal provider retries do not double-charge it.
- Generic compatible providers retry only transient connection/timeout/429/5xx startup failures with bounded backoff.
- Thinking-model names receive extended upstream timeout handling where appropriate.
- Streaming is forwarded end-to-end whenever upstream supports it; a bounded compatibility conversion remains available for older NIM paths.
- If Chromium crashes, the bridge disconnects, a page navigates away, or a session expires, pending requests receive a precise provider-unavailable error rather than hanging. A subsequent request reinitializes the managed runtime.
- On shutdown Free Codex closes browser contexts, bridge sockets, pending request queues, cache resources, and HTTP clients.

---

## Manual Puter end-to-end verification (real account)

> Unit tests use mocked browser/Puter.js transports and do **not** require an account, network, browser login, or provider credentials. This procedure is only for an operator who wants to test their own authenticated setup.

1. Install Playwright and Chromium as shown above.
2. Configure `PUTER_WEB_ENABLED=1`, a model ID, and `FREE_CODEX_DEFAULT_PROVIDER=puter_web` (or equivalent `providers.toml` section).
3. Run `fc-puter-auth`, complete sign-in in the visible official SDK flow, and wait for confirmation.
4. Start `fc-server`. Verify `GET /v1/providers` reports Puter browser connected/authenticated.
5. Send a stream through the local proxy:

   ```bash
   curl -N http://127.0.0.1:8080/v1/responses \
     -H 'Content-Type: application/json' \
     -d '{"model":"puter_web:deepseek/deepseek-v4.1-flash","input":"Reply with a short greeting.","stream":true}'
   ```

6. Run `fc-codex --provider puter-web --model deepseek/deepseek-v4.1-flash` and verify streamed agent output.
7. Ask Codex to use an existing local function/tool. Confirm Free Codex emits the function call, Codex executes it, and the next `function_call_output` continues the model conversation. The browser must never execute that tool itself.
8. If the selected model has a tested `image_input = true` override, submit an OpenAI-style image block through `/v1/responses`; otherwise confirm the expected explicit unsupported-modality error.

---

## Development and tests

```bash
uv sync
uv run pytest -q
# optional browser package; tests still mock browser/Puter.js transport
uv run --extra puter python -m playwright install chromium
```

The test suite covers legacy NIM behavior plus provider config/selection, model routing, capability validation, provider errors, Responses/Chat contracts, and mockable browser bridge primitives. No automated test needs a real Puter login or external provider.

---

## Troubleshooting

| Symptom | Action |
|---|---|
| `fc-codex` cannot reach proxy | Start `fc-server`; confirm `FREE_CODEX_PORT` matches its health URL. |
| NIM still looks forced | Check `FREE_CODEX_DEFAULT_PROVIDER`, `providers.toml [routing]`, and `/v1/providers`. Legacy `NVIDIA_NIM_MODEL` remains the NIM default, but it no longer controls other providers. |
| Puter says not initialized | Install optional browser support, run `python -m playwright install chromium`, then `fc-puter-auth`. |
| Puter says authentication required | Run `fc-puter-auth` once with the same `PUTER_WEB_PROFILE_DIR`. |
| Image input rejected | Enable `image_input = true` only for a tested exact provider/model; otherwise choose an image-capable model. |
| Admin action denied | Use `http://127.0.0.1:8080/admin` or configure/send `FREE_CODEX_ADMIN_TOKEN`. |
| Browser fails to launch | Set `PUTER_WEB_BROWSER=chromium`, `chrome`, `edge`, or a valid Chromium executable path. |

---

## License

MIT License. Free Codex is an independent local proxy; respect each upstream provider's terms and applicable usage limits.
