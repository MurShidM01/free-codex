# Free Codex

> **Self-host OpenAI Codex CLI with NVIDIA NIM, Ollama, or any OpenAI-compatible API.**

A lightweight, open-source proxy server that bridges the OpenAI Codex CLI to your preferred AI provider — no OpenAI subscription required.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Package Manager: uv](https://img.shields.io/badge/package%20manager-uv-465fff?logo=uv&logoColor=white)](https://github.com/astral-sh/uv)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![GitHub Stars](https://img.shields.io/github/stars/MurShidM01/free-codex?style=social)](https://github.com/MurShidM01/free-codex/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/MurShidM01/free-codex?style=social)](https://github.com/MurShidM01/free-codex/network/members)

---

## What is Free Codex?

**Free Codex** is a lightweight API proxy that allows you to use the [OpenAI Codex CLI](https://developers.openai.com/codex/cli/) with your own hosted AI models. Instead of paying for OpenAI's API, connect to:

- **NVIDIA NIM** — Access NVIDIA's managed inference endpoints
- **Ollama** — Self-host open-source models locally
- **vLLM / LM Studio** — Deploy any OpenAI-compatible backend
- **Custom endpoints** — Any API that speaks the OpenAI format

Codex runs exactly as expected, with full tool-calling, function execution, and workspace context support.

---

## Why Free Codex?

| Feature | Free Codex | OpenAI Direct |
|----------|-----------|---------------|
| API Cost | Use your own provider | Expensive OpenAI pricing |
| Self-Hosting | Full control | Not available |
| Model Choice | Any OpenAI-compatible model | Only OpenAI models |
| Privacy | Data stays on your infrastructure | Data processed by OpenAI |
| Codex Integration | Native | Native |

---

## Quick Start

### Prerequisites

- Python 3.9+
- [uv](https://docs.astral.sh/uv/) package manager
- [OpenAI Codex CLI](https://developers.openai.com/codex/cli/)

### Installation

```bash
# One-liner install
uv tool install git+https://github.com/MurShidM01/free-codex.git

# Or reinstall with latest changes
uv tool install git+https://github.com/MurShidM01/free-codex.git --force
```

### Setup

```bash
# Initialize config (creates ~/.config/free-codex/)
fc-init
```

Edit `~/.config/free-codex/.env` with your provider credentials:

```env
# NVIDIA NIM example
NVIDIA_NIM_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_NIM_API_KEY=your_nvidia_api_key
NVIDIA_NIM_MODEL=minimaxai/minimax-m2.7
```

### Usage

```bash
# Terminal 1: Start the proxy server
fc-server

# Terminal 2: Run Codex
fc-codex
```

When you run `fc-init`, Free Codex writes the local Codex config so the client uses
`wire_api = "responses"` and sends agentic calls to `/v1/responses` on the proxy.

---

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NVIDIA_NIM_BASE_URL` | Yes | — | Your API provider's base URL |
| `NVIDIA_NIM_API_KEY` | Yes | — | API key for authentication |
| `NVIDIA_NIM_MODEL` | Yes | — | Model ID to use |
| `FREE_CODEX_PORT` | No | `8080` | Server port |
| `FREE_CODEX_HOST` | No | `0.0.0.0` | Bind address |
| `FREE_CODEX_ADMIN_TOKEN` | No | — | Bearer token for admin panel |

### Admin Dashboard

Access the web-based admin panel at `http://127.0.0.1:8080/admin`:

- Configure NIM credentials and test connections
- View usage statistics (requests, tokens, costs)
- Edit environment variables with validation
- Monitor streak days and daily/monthly stats
- Animated stat counters with real-time updates

---

## VS Code Extension Compatibility

Free Codex works with the **official OpenAI Codex VS Code extension**. The extension reads authentication from `~/.codex/config.toml`.

### Setup

1. **Start Free Codex Server**

```bash
# Start the proxy server
fc-server
```

2. **Initialize Free Codex (creates config for VS Code extension)**

```bash
fc-init
```

This automatically creates `~/.codex/config.toml` which the VS Code extension reads for authentication.

3. **Open Codex VS Code Extension**

The extension will automatically use the config from `~/.codex/config.toml` — no login required!

### Why This Works

The Codex VS Code extension reads its API configuration from `~/.codex/config.toml`. When you run `fc-init`, Free Codex automatically creates this file with the correct settings pointing to your local Free Codex server.

By default, the generated config now declares `wire_api = "responses"`, so the extension uses the OpenAI Responses API format against the proxy at `/v1/responses`.

### Manual Setup (if needed)

If the automatic setup doesn't work, manually copy the config:

**Windows:**
```powershell
copy $env:USERPROFILE\.config\free-codex\config.toml $env:USERPROFILE\.codex\config.toml
```

**Linux/Mac:**
```bash
cp ~/.config/free-codex/config.toml ~/.codex/config.toml
```

### After fc-init

You should see output like:
```
Copied config to Codex extension location: C:\Users\YourUser\.codex\config.toml
```

### No API Key Required

With the config file in place, the Codex VS Code extension works without entering any API key or login — it uses the proxy configuration directly.

### VS Code Settings (Optional)

You can also add these for better experience:

```json
{
    "claudeCode.preferredLocation": "panel",
    "workbench.colorTheme": "Light Modern"
}
```

---

## Advanced Configuration

### Timeout & Retry Settings

For complex tasks, long files, or reasoning/thinking models:

| Variable | Default | Description |
|----------|---------|-------------|
| `FREE_CODEX_READ_TIMEOUT` | `300` | Response timeout in seconds |
| `FREE_CODEX_CONNECT_TIMEOUT` | `30` | Connection timeout in seconds |
| `FREE_CODEX_MAX_RETRIES` | `3` | Retries on transient errors |
| `FREE_CODEX_SSE_HEARTBEAT_SECS` | `25` | Keep-alive interval (0 to disable) |

```env
# For thinking/reasoning and heavy models like glm-5.1 or deepseek-v4-pro
FREE_CODEX_READ_TIMEOUT=900
FREE_CODEX_CONNECT_TIMEOUT=60
FREE_CODEX_MAX_RETRIES=5
FREE_CODEX_SSE_HEARTBEAT_SECS=20
```

Free Codex now defaults NIM timeouts based on the provider preset, so NIM users get longer read/connect defaults without needing to set env vars.

### Workspace Context Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `FREE_CODEX_WORKSPACE_SNIPPET_BYTES` | `65536` | Max bytes per file snippet |
| `FREE_CODEX_WORKSPACE_SNIPPET_LINES` | `300` | Max lines per file snippet |

---

## Thinking & Reasoning Models

Free Codex has special support for reasoning models like DeepSeek, Qwen3, Claude with extended thinking:

### Automatic Detection

Thinking models (DeepSeek, Qwen3, etc.) are automatically detected and receive:
- **Extended timeout**: Up to 10 minutes for long reasoning chains
- **Heartbeat keep-alive**: Prevents connection drops during thinking
- **Thinking token tracking**: Separate tracking for reasoning tokens

### Supported Thinking Patterns

| Model | Thinking Format |
|-------|-----------------|
| DeepSeek R1 | `thinking` content block + final answer |
| Qwen3 | `reasoning_content` in delta |
| Claude | `thinking` blocks |
| Custom | Tagged thinking (``) auto-stripped |

### Optimizing for Reasoning Tasks

```env
# DeepSeek R1 / DeepSeek Chat
NVIDIA_NIM_MODEL=deepseek-ai/DeepSeek-R1

# Qwen3
NVIDIA_NIM_MODEL=qwen3

# Extended context for complex reasoning
FREE_CODEX_READ_TIMEOUT=900
NVIDIA_NIM_MODEL=meta/llama-3.3-70b-instruct

# Higher max_tokens for complex tasks
# (Set in request or use thinking parameter)
```

---

## Supported Providers

### NVIDIA NIM

```env
NVIDIA_NIM_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_NIM_API_KEY=nvapi-xxxx
NVIDIA_NIM_MODEL=minimaxai/minimax-m2.7
```

[Get your NVIDIA API key →](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/cloudai)

### Ollama

```env
NVIDIA_NIM_BASE_URL=http://localhost:11434/v1
NVIDIA_NIM_API_KEY=ollama
NVIDIA_NIM_MODEL=llama3.2
```

### Generic OpenAI-Compatible

```env
NVIDIA_NIM_BASE_URL=https://your-api.com/v1
NVIDIA_NIM_API_KEY=your-key
NVIDIA_NIM_MODEL=your-model
```

---

## Architecture

```
┌────────────┐      ┌───────────────┐      ┌──────────────┐
│   Codex    │─────▶│  Free Codex   │─────▶│   Provider   │
│    CLI     │◀─────│    Proxy      │◀─────│              │
└────────────┘      └───────────────┘      └──────────────┘
                                           NVIDIA NIM
                                           Ollama
                                           vLLM
```

Free Codex acts as a transparent proxy:
1. Codex sends requests to `http://127.0.0.1:8080`
2. The configured `wire_api = "responses"` makes Codex use the `/v1/responses` endpoint
3. Free Codex forwards the request to your provider and translates between Responses and Chat Completions as needed
4. Responses stream back to Codex in real-time

---

## Development

```bash
# Clone repository
git clone https://github.com/MurShidM01/free-codex.git
cd free-codex

# Install dependencies
uv sync

# Run with live reload
FREE_CODEX_RELOAD=1 uv run fc-server
```

---

## Troubleshooting

### Server won't start
1. Run `fc-init` to generate config files
2. Verify `~/.config/free-codex/.env` has correct credentials
3. Test endpoint via Admin UI → "Test Chat" button

### Admin UI access denied
- Access from `http://127.0.0.1:8080/admin` (not IP aliases)
- Or set `FREE_CODEX_ADMIN_TOKEN` in `.env`

### Model not routing correctly
Ensure `NVIDIA_NIM_MODEL` in `.env` matches exactly:
- Case-sensitive
- Include org prefix (e.g., `minimaxai/minimax-m2.7`)

---

## Contributing

Contributions welcome! Open an issue or submit a PR.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Submit a Pull Request

---

## License

MIT License — free to use, modify, and distribute.

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=MurShidM01/free-codex&type=Timeline)](https://star-history.com/#MurShidM01/free-codex&Timeline)

---

<p align="center">
  <strong>Free Codex</strong> — OpenAI Codex, your way.
  <br/>
  <a href="https://github.com/MurShidM01/free-codex">GitHub</a>
  ·
  <a href="https://github.com/MurShidM01/free-codex/issues">Issues</a>
  ·
  <a href="https://github.com/MurShidM01/free-codex/discussions">Discussions</a>
</p>