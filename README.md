# Free Codex

<p align="center">

[![GitHub Stars](https://img.shields.io/github/stars/MurShidM01/free-codex?style=social)](https://github.com/MurShidM01/free-codex/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/MurShidM01/free-codex?style=social)](https://github.com/MurShidM01/free-codex/network/members)
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/badge/package%20manager-uv-465fff?logo=uv&logoColor=white)](https://github.com/astral-sh/uv)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows--lightgrey)](#)

</p>

<p align="center">

**Use OpenAI Codex CLI with your own hosted models.**<br>
A lightweight, self-hosted API layer that brings Codex tooling to NVIDIA NIM and any OpenAI-compatible endpoint.

</p>

---

## Features

| | |
|--|--|
| **OpenAI-Compatible API** | `/v1/chat/completions`, `/v1/models`, `/v1/completions` endpoints |
| **Any Provider** | NVIDIA NIM, Ollama, vLLM, LM Studio, or any OpenAI-compatible API |
| **Codex Tool Support** | Full tool-calling (functions) and workspace context |
| **Beautiful Admin UI** | Web console at `/admin` for configuration, testing, and monitoring |
| **Model Alignment** | Automatic model ID matching — just set `NVIDIA_NIM_MODEL` in `.env` |
| **Live Reload** | Instant config refresh without restart |
| **Usage Statistics** | Real-time tracking of requests, tokens, and costs |
| **Cross-Platform** | Linux, macOS, and Windows (with SSE error handling) |

---

## Installation

### One-Line Install

```bash
# Install globally (recommended)
uv tool install git+https://github.com/MurShidM01/free-codex.git

# Or upgrade to latest
uv tool install git+https://github.com/MurShidM01/free-codex.git --force
```

> **Note:** After installing, run `fc-init` once to create your config files.

### Development Install

```bash
# Clone and run locally
git clone https://github.com/MurShidM01/free-codex.git
cd free-codex
uv sync

# Run with live reload
FREE_CODEX_RELOAD=1 uv run fc-server
```

### Prerequisites

| Requirement | Description |
|------------|-------------|
| **Python 3.9+** | [Download python.org](https://www.python.org/downloads/) |
| **[uv](https://docs.astral.sh/uv/)** | Modern Python package manager |
| **[OpenAI Codex CLI](https://developers.openai.com/codex/cli/)** | `npm install -g @openai/codex` |
| **API Endpoint** | NVIDIA NIM, Ollama, or any OpenAI-compatible API |

---

## Quick Start

### 1. Install OpenAI Codex CLI

```bash
npm install -g @openai/codex
codex --version
```

### 2. Initialize Free Codex

```bash
fc-init
```

This creates `~/.config/free-codex/` with:
- `config.toml` — Codex configuration (uses `minimaxai/minimax-m2.7` by default)
- `.env` — Your credentials (edit this)

### 3. Configure Your Provider

Edit `~/.config/free-codex/.env`:

```env
NVIDIA_NIM_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_NIM_API_KEY=your_api_key_here
NVIDIA_NIM_MODEL=minimaxai/minimax-m2.7
```

> **Tip:** Open `http://127.0.0.1:8080/admin` for a visual editor with:
> - NIM endpoint testing (List Models, Test Chat)
> - Usage statistics (requests, tokens, costs)
> - Environment file editor with validation

### 4. Start the Server

```bash
fc-server
```

Server runs at **`http://127.0.0.1:8080`** — Health check at `/health`

### 5. Run Codex

In another terminal:

```bash
fc-codex
```

---

## Screenshots

<p align="center">

| Server | Codex CLI |
|:------:|:---------:|
| <img src="src/free_codex/static/fc-server.png" alt="fc-server" width="800"/> | <img src="src/free_codex/static/fc-codex.png" alt="fc-codex" width="800"/> |

| Admin Dashboard |
|:---------------:|
| <img src="src/free_codex/static/admin-panel.png" alt="Admin Panel" width="800"/> |

</p>

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NVIDIA_NIM_BASE_URL` | — | Provider base URL (required) |
| `NVIDIA_NIM_API_KEY` | — | API key (required) |
| `NVIDIA_NIM_MODEL` | — | Default model ID (required) |
| `FREE_CODEX_PORT` | `8080` | Server port |
| `FREE_CODEX_HOST` | `0.0.0.0` | Bind address |
| `FREE_CODEX_RELOAD` | `0` | Enable auto-reload (`1`/`true`/`on`) |
| `FREE_CODEX_ACCESS_LOG` | `0` | Enable request logging |
| `FREE_CODEX_SSE_DELTA_CHARS` | `1536` | SSE chunk size cap |
| `FREE_CODEX_LOG_LEVEL` | `info` | Logging level |
| `FREE_CODEX_ADMIN_TOKEN` | — | Bearer token for admin |
| `FREE_CODEX_WORKSPACE_CONTEXT` | — | Enable workspace hints (`1`) |
| `FREE_CODEX_WORKSPACE_ROOT` | — | Default workspace directory |
| `FREE_CODEX_WORKSPACE_SNIPPET_BYTES` | `49152` | Snippet size cap (bytes) |
| `FREE_CODEX_WORKSPACE_SNIPPET_LINES` | `160` | Snippet size cap (lines) |

---

## CLI Commands

| Command | Description |
|---------|-------------|
| `fc-init` | Initialize `~/.config/free-codex/` (safe — won't overwrite existing config) |
| `fc-server` | Start the API proxy server |
| `fc-codex` | Launch Codex CLI with Free Codex config |
| `fc-admin` | Open admin dashboard in browser |

---

## Architecture

```
┌──────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  OpenAI      │     │   Free Codex    │     │  Your API       │
│  Codex CLI   │────▶│   Server        │────▶│  Provider       │
│              │     │                 │     │                 │
│              │◀────│   (Proxy)       │◀────│  NVIDIA NIM     │
│              │     │                 │     │  Ollama         │
└──────────────┘     └─────────────────┘     │  vLLM           │
                                              └─────────────────┘
```

### How Model Selection Works

1. Set `NVIDIA_NIM_MODEL` in `~/.config/free-codex/.env`
2. Free Codex **always** routes requests to the configured model
3. The `model` in `config.toml` can be any string — it's overridden by `NVIDIA_NIM_MODEL`
4. Use the Admin UI to test your connection before running Codex

---

## Security

> **Warning:** Binding to `0.0.0.0` exposes your API and admin panel to the network. Always use `FREE_CODEX_ADMIN_TOKEN`, TLS, and firewall rules in production.

| Environment | Recommendation |
|------------|----------------|
| **Local dev** | `http://127.0.0.1:8080` — loopback only |
| **Production** | Set `FREE_CODEX_ADMIN_TOKEN` for admin access |
| **Production** | Never use `FREE_CODEX_RELOAD` |

---

## Troubleshooting

### Changes don't apply after editing files?

`uv tool install` creates an **isolated copy**. Your git clone edits won't affect it.

**Fix:**
```bash
# Option 1: Reinstall after pulling updates
uv tool install git+https://github.com/MurShidM01/free-codex.git --force

# Option 2: Clone and dev mode
git clone https://github.com/MurShidM01/free-codex.git
FREE_CODEX_RELOAD=1 uv run fc-server
```

### Server won't start?

1. Run `fc-init` to create config files
2. Edit `~/.config/free-codex/.env` with your credentials
3. Restart `fc-server`

### Admin UI shows "Authentication failed" when testing?

1. Open `http://127.0.0.1:8080/admin` (not a different IP)
2. The admin panel auto-unlocks from localhost
3. Or set `FREE_CODEX_ADMIN_TOKEN` in `.env`

### How do I change the model?

Edit `~/.config/free-codex/.env`:
```env
NVIDIA_NIM_MODEL=your-model-id
```
Then restart `fc-server` (or save via Admin UI which auto-reloads).

### Windows SSE errors on close?

Benign `WinError 10054` on SSE client disconnect is filtered — safe to ignore.

### Need help?

- [Open an issue](https://github.com/MurShidM01/free-codex/issues)
- [Start a discussion](https://github.com/MurShidM01/free-codex/discussions)

---

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

<p align="center">

**Built with**

[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![uv](https://img.shields.io/badge/uv-465fff?logo=uv&logoColor=white)](https://github.com/astral-sh/uv)

<br/>

[![GitHub](https://img.shields.io/badge/GitHub-MurShidM01%2Ffree--codex-181717?logo=github&logoColor=white)](https://github.com/MurShidM01/free-codex)
&nbsp;·&nbsp;
[Issues](https://github.com/MurShidM01/free-codex/issues)
&nbsp;·&nbsp;
[Discussions](https://github.com/MurShidM01/free-codex/discussions)

</p>