"""Call NVIDIA NIM / OpenAI-compatible endpoints from the admin UI."""

from __future__ import annotations

import time
from typing import Any

import httpx


def normalize_base_url(url: str) -> str:
    return url.strip().rstrip("/")


async def nim_fetch_models(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    api_key: str,
) -> dict[str, Any]:
    base = normalize_base_url(base_url)
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Accept": "application/json",
    }
    url = f"{base}/models"
    t0 = time.perf_counter()
    probe_timeout = httpx.Timeout(120.0, connect=30.0)
    try:
        r = await client.get(url, headers=headers, timeout=probe_timeout)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        payload: dict[str, Any]
        try:
            payload = r.json()
        except Exception:
            payload = {}
        rows = payload.get("data")
        if isinstance(rows, list):
            count = len(rows)
            ids = [str(x.get("id", "")) for x in rows if isinstance(x, dict)]
        else:
            count = 0
            ids = []
        return {
            "ok": True,
            "status_code": r.status_code,
            "elapsed_ms": elapsed_ms,
            "model_count": count,
            "model_ids_sample": ids[:40],
            "raw_error": None,
            "response_text": r.text[:500] if r.status_code != 200 else None,
        }
    except (httpx.HTTPError, httpx.TimeoutException, OSError) as e:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "ok": False,
            "status_code": None,
            "elapsed_ms": elapsed_ms,
            "model_count": 0,
            "model_ids_sample": [],
            "raw_error": str(e),
        }


async def nim_ping_chat(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    api_key: str,
    model: str,
) -> dict[str, Any]:
    base = normalize_base_url(base_url)
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }
    url = f"{base}/chat/completions"
    body = {
        "model": model.strip(),
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 8,
        "temperature": 0,
    }
    t0 = time.perf_counter()
    probe_timeout = httpx.Timeout(120.0, connect=30.0)
    try:
        r = await client.post(url, headers=headers, json=body, timeout=probe_timeout)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        # Treat 2xx as success
        is_success = 200 <= r.status_code < 300
        snippet = ""
        raw_error = None

        if is_success:
            try:
                data = r.json()
                choices = data.get("choices") or []
                if choices and isinstance(choices[0], dict):
                    msg = choices[0].get("message") or {}
                    snippet = str(msg.get("content") or "")[:500]
            except Exception:
                # If response is valid but not JSON, that's still a working connection
                snippet = r.text[:500] if r.text else "[no content]"
        else:
            raw_error = r.text[:1000]

        return {
            "ok": is_success,
            "status_code": r.status_code,
            "elapsed_ms": elapsed_ms,
            "assistant_preview": snippet,
            "raw_error": raw_error,
            "response_text": r.text[:500] if not is_success else None,
        }
    except (httpx.HTTPError, httpx.TimeoutException, OSError) as e:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "ok": False,
            "status_code": None,
            "elapsed_ms": elapsed_ms,
            "assistant_preview": "",
            "raw_error": str(e),
        }
