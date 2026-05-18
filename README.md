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

Free Codex works with VS Code extensions that support custom API endpoints. Configure them to use Free Codex as the backend.

### Setup

1. **Start Free Codex Server**

```bash
# Start the proxy server
fc-server
```

2. **Configure VS Code Settings**

Add the following to your VS Code `settings.json` (File → Preferences → Settings → Open JSON):

#### For ChatGPT for VS Code Extension

```json
{
  "chatgpt.cliExecutable": "codex"
}
```

Then set environment variables via `chatgpt.env`:

```json
{
  "chatgpt.env": {
    "OPENAI_BASE_URL": "http://localhost:8080",
    "OPENAI_API_KEY": "freecodex"
  }
}
```

#### For Claude Code Extension (Official)

```json
{
  "claudeCode.environmentVariables": [
    { "name": "OPENAI_BASE_URL", "value": "http://localhost:8080" },
    { "name": "OPENAI_API_KEY", "value": "freecodex" },
    { "name": "CODEX_ENABLE_GATEWAY_MODEL_DISCOVERY", "value": "1" }
  ]
}
```

Or if you prefer to edit the settings file directly:

```json
{
  "claudeCode": {
    "environmentVariables": [
      { "name": "OPENAI_BASE_URL", "value": "http://localhost:8080" },
      { "name": "OPENAI_API_KEY", "value": "freecodex" },
      { "name": "CODEX_ENABLE_GATEWAY_MODEL_DISCOVERY", "value": "1" }
    ]
  }
}
```

### Environment Variables Explained

| Variable | Value | Description |
|----------|-------|-------------|
| `OPENAI_BASE_URL` | `http://localhost:8080` | Free Codex proxy URL |
| `OPENAI_API_KEY` | `freecodex` | Dummy key (Free Codex accepts any value) |
| `CODEX_ENABLE_GATEWAY_MODEL_DISCOVERY` | `1` | Enable model discovery via `/v1/models` |

### Custom Port

If you changed the default port (8080), update the URL accordingly:

```json
{
  "chatgpt.env": {
    "OPENAI_BASE_URL": "http://localhost:YOUR_PORT"
  }
}
```

### Remote Server

For connecting to a Free Codex server on another machine:

```json
{
  "chatgpt.env": {
    "OPENAI_BASE_URL": "http://192.168.1.100:8080",
    "OPENAI_API_KEY": "freecodex"
  }
}
```

### Authentication

If you've enabled admin authentication on Free Codex:

```json
{
  "chatgpt.env": {
    "OPENAI_BASE_URL": "http://localhost:8080",
    "OPENAI_API_KEY": "YOUR_ADMIN_TOKEN"
  }
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
# For thinking/reasoning models (DeepSeek, Qwen3, etc.)
FREE_CODEX_READ_TIMEOUT=600
FREE_CODEX_CONNECT_TIMEOUT=60
FREE_CODEX_MAX_RETRIES=4
FREE_CODEX_SSE_HEARTBEAT_SECS=25
```

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
2. Free Codex forwards to your configured provider
3. Responses stream back to Codex in real-time

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