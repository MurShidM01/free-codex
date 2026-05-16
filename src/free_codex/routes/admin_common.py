"""Shared admin auth helpers."""

from __future__ import annotations

import os

from fastapi import HTTPException, Request

_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def admin_bearer_configured() -> str:
    return os.getenv("FREE_CODEX_ADMIN_TOKEN", "").strip()


def is_trusted_localhost(request: Request) -> bool:
    """True when the TCP client appears to be same-machine (loopback)."""
    client = request.client
    if client is None or not client.host:
        return False
    return client.host.lower() in _LOCAL_HOSTS


def can_access_admin_secrets(request: Request) -> bool:
    """Reveal NIM values / full .env when token matches, or dev mode (no token + local)."""
    tok = admin_bearer_configured()
    if tok:
        return request.headers.get("authorization") == f"Bearer {tok}"
    return is_trusted_localhost(request)


def require_admin_action(request: Request) -> None:
    """Mutations & NIM probes: Bearer when token is set, else same-host only (no token)."""
    tok = admin_bearer_configured()
    if tok:
        if request.headers.get("authorization") != f"Bearer {tok}":
            raise HTTPException(status_code=401, detail="Invalid admin token")
        return
    if not is_trusted_localhost(request):
        raise HTTPException(
            status_code=403,
            detail=(
                "Set FREE_CODEX_ADMIN_TOKEN for admin actions from this client host, "
                "or open /admin from http://127.0.0.1 on the machine running fc-server."
            ),
        )
