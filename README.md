# Free Codex NIM Proxy

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.9%2B-blue?logo=python&logoColor=white" alt="Python 3.9+"></a>
  <a href="https://github.com/astral-sh/uv"><img src="https://img.shields.io/badge/package%20manager-uv-465fff?logo=uv&logoColor=white" alt="uv"></a>
  <img src="https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey" alt="Platform">
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI"></a>
</p>

An **OpenAI-compatible HTTP proxy** for [**NVIDIA NIM**](https://docs.nvidia.com/nim/) workloads, tuned for agents and the [**OpenAI Codex CLI**](https://developers.openai.com/codex/).

---

## Features

| | |
|--|--|
| **OpenAI API** | `/v1/chat/completions`, `/v1/models`, **`/v1/responses`** (Codex wire) |
| **NIM** | Forwards to your NVIDIA base URL with your API key |
| **Codex-friendly** | Maps Codex tool outputs into Chat Completions tool messages; optional workspace context |
| **Admin UI** | Browser dashboard at **`/admin`** — edit `~/.config/free-codex/.env`, list remote models, run a tiny chat probe |
| **Model mapping** | Map common names to real NIM model IDs |

---

## Prerequisites

- **Python 3.9+**
- **[uv](https://docs.astral.sh/uv/)** (recommended) or another PEP 517 installer
- **NVIDIA NIM** credentials ([API key & endpoint](https://docs.nvidia.com/nim/large-language-models/latest/getting-started.html))
- **[OpenAI Codex CLI](https://developers.openai.com/codex/)** (for `fc-codex`)

---

## 1) Install uv

<details>
<summary><strong>Linux / macOS</strong></summary>

Official installer (downloads the right binary for your OS/arch):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Reload your shell or add uv to `PATH` as printed by the installer. Verify:

```bash
uv --version
```

</details>

<details>
<summary><strong>Windows (PowerShell)</strong></summary>

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen the terminal, then:

```powershell
uv --version
```

</details>

<details>
<summary><strong>Windows (winget)</strong></summary>

```powershell
winget install --id astral-sh.uv -e
```

</details>

<details>
<summary><strong>macOS (Homebrew)</strong></summary>

```bash
brew install uv
```

</details>

---

## 2) Install the OpenAI Codex CLI

Follow the **current** steps in the official guide: **[Install and authenticate Codex](https://developers.openai.com/codex/cli/)**.

Typical pattern (check the docs for updates):

```bash
# Example: npm global install (see upstream docs for the authoritative command)
npm install -g @openai/codex
codex --version
```

Authenticate with your ChatGPT / OpenAI account as described in the Codex documentation. **`fc-codex`** reuses the Codex CLI but points the provider at this proxy.

---

## 3) Install Free Codex

Pick **one** approach.

### A) From GitHub with `uv tool` (recommended for end users)

Replace the URL with **your** fork or upstream repository:

```bash
uv tool install git+https://github.com/YOUR_USERNAME/free-codex.git
```

Upgrading later:

```bash
uv tool install --force git+https://github.com/YOUR_USERNAME/free-codex.git
```

This exposes **`fc-init`**, **`fc-server`**, and **`fc-codex`** on your PATH (managed by uv).

### B) Clone and editable install (development)

```bash
git clone https://github.com/YOUR_USERNAME/free-codex.git
cd free-codex
uv pip install -e .
```

Or without activating a venv:

```bash
uv run fc-server
```

---

## 4) Configure (`fc-init` + `.env`)

1. **Initialize** config files under `~/.config/free-codex/` (or the platform equivalent):

   ```bash
   fc-init
   ```

2. **Set NVIDIA variables** in **`~/.config/free-codex/.env`** (or use the Admin UI — see below):

   ```env
   NVIDIA_NIM_BASE_URL=https://integrate.api.nvidia.com/v1
   NVIDIA_NIM_API_KEY=your_api_key
   NVIDIA_NIM_MODEL=your_org/your-model-id
   ```

   Use the **same** `NVIDIA_NIM_MODEL` string in **`config.toml`** (after `fc-init`) so Codex and the proxy agree on the model id.

3. **Start the proxy** (required before `fc-codex`):

   ```bash
   fc-server
   ```

   Default listen: **`0.0.0.0:8080`**. Health: `http://127.0.0.1:8080/health`.

4. **Run Codex through the wrapper**:

   ```bash
   fc-codex
   ```

   `fc-codex` sets **`CODEX_HOME`** to `~/.config/free-codex` and checks that **`fc-server`** is healthy before starting.

---

## Admin UI (`/admin`)

Open **`http://127.0.0.1:<port>/admin`** (the URL is printed when `fc-server` starts).

- **NVIDIA fields** (base URL, API key, model) are **filled from your `.env`** on load; you can still edit them before listing models or running a test.
- **Saving `.env`** and **NIM actions** from the UI:
  - **`FREE_CODEX_ADMIN_TOKEN` unset:** allowed **only** from a **same-machine** client (`127.0.0.1`, `::1`, `localhost`). Open `/admin` via `http://127.0.0.1`, not via another machine’s hostname/IP.
  - **`FREE_CODEX_ADMIN_TOKEN` set:** every browser must send **`Authorization: Bearer <token>`** (use the **Unlock** field in the UI).

Restart **`fc-server`** after saving `.env` so worker processes reload NVIDIA variables from disk.

---

## Environment variables

| Variable | Purpose |
|----------|---------|
| `NVIDIA_NIM_BASE_URL` | NVIDIA OpenAI-compatible base URL |
| `NVIDIA_NIM_API_KEY` | API key |
| `NVIDIA_NIM_MODEL` | Default model id |
| `FREE_CODEX_PORT` | Listen port (default `8080`) |
| `FREE_CODEX_HOST` | Bind address (default `0.0.0.0`) |
| `FREE_CODEX_HEALTH_URL` | Override health URL for `fc-codex` |
| `FREE_CODEX_HEALTH_HOST` | Host for default health URL (default `127.0.0.1`) |
| `FREE_CODEX_ACCESS_LOG` | `1` = log each HTTP request |
| `FREE_CODEX_SSE_DELTA_CHARS` | Max chars per streamed SSE delta (256–32768) |
| `FREE_CODEX_LOG_LEVEL` | Python log level (default `INFO`) |
| `FREE_CODEX_ADMIN_TOKEN` | Bearer token for `/admin` writes & probes from **non-local** clients |
| `FREE_CODEX_WORKSPACE_CONTEXT` | `1` = inject shallow workspace listing into `/v1/responses` |
| `FREE_CODEX_WORKSPACE_ROOT` | Default workspace if Codex omits metadata |
| `FREE_CODEX_WORKSPACE_SNIPPET_BYTES` / `_LINES` | Caps for injected file excerpts |

Codex may also send `metadata.workspace_root` or header **`X-Free-Codex-Workspace`**.

---

## Security

- Binding to **`0.0.0.0`** exposes the admin UI and proxy on your LAN. Use a strong **`FREE_CODEX_ADMIN_TOKEN`**, TLS termination where appropriate, and firewall rules for anything beyond local development.
- Without a token, **never** rely on “local trust” if you expose port **8080** to untrusted networks.

---

## Codex `config.toml` notes

`fc-init` writes **`~/.config/free-codex/config.toml`** and **`.env`**, not `~/.codex`. The template uses a **custom** `model_providers` entry that targets this proxy and omits `env_key` / `requires_openai_auth` for that provider so traffic does not depend on OpenAI API keys for the NIM path. See [Codex provider configuration](https://developers.openai.com/codex/config-advanced#custom-model-providers).

Optional schema line:

```toml
#:schema https://developers.openai.com/codex/config-schema.json
```

---

## Windows SSE notes

When Codex closes an SSE stream early, Windows may log asyncio `WinError 10054`. The server filters that noise so benign client disconnects are not treated as hard failures.

---

## Development

- Application code: `src/free_codex/`
- Tests: `tests/`

```bash
uv run pytest
```

---

## Contributing

Issues and PRs welcome. Replace **`YOUR_USERNAME`** / repository URLs in this document with your real GitHub path before publishing.
