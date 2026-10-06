"""Sanitized structured provider-routing logs.

Provider events are useful for diagnosing a local proxy but prompts, model
outputs, tool arguments, media, cookies and authorization headers must not end
up in normal logs.  This module therefore logs only routing metadata.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from typing import Any, Deque, Dict, List, Optional


SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "token",
    "cookie",
    "set-cookie",
    "prompt",
    "input",
    "messages",
    "content",
    "arguments",
    "output",
    "media",
    "image",
    "image_url",
}


class ProviderEventLogger:
    def __init__(self, logger: Optional[logging.Logger] = None, debug: bool = False) -> None:
        self.logger = logger or logging.getLogger("free-codex.providers")
        self.debug = debug
        self._recent: Deque[Dict[str, Any]] = deque(maxlen=100)

    @staticmethod
    def redact(value: Any) -> Any:
        if isinstance(value, dict):
            redacted: Dict[str, Any] = {}
            for key, item in value.items():
                lowered = str(key).lower().replace("_", "-")
                if lowered in SENSITIVE_KEYS or any(
                    token in lowered
                    for token in ("cookie", "authorization", "secret", "api-key", "apikey", "token", "prompt", "content", "argument", "output", "media", "image")
                ):
                    redacted[str(key)] = "[redacted]"
                else:
                    redacted[str(key)] = ProviderEventLogger.redact(item)
            return redacted
        if isinstance(value, list):
            return [ProviderEventLogger.redact(item) for item in value]
        return value

    def event(
        self,
        event: str,
        *,
        request_id: str = "",
        provider: str = "",
        model: str = "",
        protocol: str = "",
        stream: bool = False,
        latency_ms: Optional[float] = None,
        status: str = "",
        tool_call_count: int = 0,
        retry_count: int = 0,
        error_type: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload: Dict[str, Any] = {
            "event": event,
            "request_id": request_id,
            "provider": provider,
            "model": model,
            "protocol": protocol,
            "stream": bool(stream),
            "latency_ms": latency_ms,
            "status": status,
            "tool_call_count": tool_call_count,
            "retry_count": retry_count,
            "error_type": error_type,
        }
        if extra:
            # Even explicit debug mode keeps hard credentials redacted.  Normal
            # mode intentionally does not include arbitrary request metadata.
            payload["extra"] = self.redact(extra) if self.debug else self.redact({
                key: value for key, value in extra.items()
                if key in ("browser_state", "reason", "attempt", "session_state")
            })
        # Store the same sanitized shape for the local admin status endpoint.
        self._recent.append(dict(payload))
        self.logger.info("provider_event=%s", json.dumps(payload, sort_keys=True, default=str))

    def recent(self, limit: int = 25) -> List[Dict[str, Any]]:
        """Return sanitized, newest-first routing events for local diagnostics."""
        count = max(1, min(int(limit), 100))
        return list(reversed(list(self._recent)[-count:]))
