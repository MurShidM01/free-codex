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
    try:
        r = await client.get(url, headers=headers, timeout=45.0)
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
            "ok": r.status_code == 200,
            "status_code": r.status_code,
            "elapsed_ms": elapsed_ms,
            "model_count": count,
            "model_ids_sample": ids[:40],
            "raw_error": None if r.status_code == 200 else r.text[:2000],
        }
    except httpx.HTTPError as e:
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
    try:
        r = await client.post(url, headers=headers, json=body, timeout=60.0)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        snippet = ""
        try:
            data = r.json()
            choices = data.get("choices") or []
            if choices and isinstance(choices[0], dict):
                msg = choices[0].get("message") or {}
                snippet = str(msg.get("content") or "")[:500]
        except Exception:
            snippet = r.text[:500]
        return {
            "ok": r.status_code == 200,
            "status_code": r.status_code,
            "elapsed_ms": elapsed_ms,
            "assistant_preview": snippet,
            "raw_error": None if r.status_code == 200 else r.text[:2000],
        }
    except httpx.HTTPError as e:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "ok": False,
            "status_code": None,
            "elapsed_ms": elapsed_ms,
            "assistant_preview": "",
            "raw_error": str(e),
        }
