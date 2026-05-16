"""Circuit breaker pattern for resilient API calls."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger("free-codex.circuit_breaker")


class CircuitState(Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5       # Failures before opening
    success_threshold: int = 3        # Successes in half-open to close
    timeout: float = 30.0             # Seconds before trying half-open
    half_open_max_calls: int = 3      # Max concurrent calls in half-open


@dataclass
class CircuitBreaker:
    """Circuit breaker for preventing cascade failures."""

    name: str
    config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _success_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _half_open_calls: int = field(default=0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    @property
    def state(self) -> CircuitState:
        return self._state

    def _should_attempt_reset(self) -> bool:
        """Check if we should attempt to reset (go to half-open)."""
        if self._state != CircuitState.OPEN:
            return False
        elapsed = time.time() - self._last_failure_time
        return elapsed >= self.config.timeout

    async def can_execute(self) -> bool:
        """Check if execution is allowed."""
        async with self._lock:
            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    self._success_count = 0
                    logger.info(f"Circuit breaker '{self.name}' transitioning to HALF_OPEN")
                    return True
                return False

            # HALF_OPEN: allow limited calls
            if self._half_open_calls < self.config.half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False

    async def record_success(self) -> None:
        """Record a successful call."""
        async with self._lock:
            if self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0
                return

            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    logger.info(f"Circuit breaker '{self.name}' CLOSED after recovery")

    async def record_failure(self) -> None:
        """Record a failed call."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open goes back to open
                self._state = CircuitState.OPEN
                logger.warning(f"Circuit breaker '{self.name}' re-OPENED after failure in half-open")

            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.config.failure_threshold:
                    self._state = CircuitState.OPEN
                    logger.warning(
                        f"Circuit breaker '{self.name}' OPENED after {self._failure_count} failures"
                    )

    def get_status(self) -> dict[str, Any]:
        """Get circuit breaker status."""
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure_time": self._last_failure_time,
            "config": {
                "failure_threshold": self.config.failure_threshold,
                "success_threshold": self.config.success_threshold,
                "timeout": self.config.timeout,
            }
        }


class CircuitBreakerManager:
    """Manages multiple circuit breakers for different services."""

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()

    async def get_breaker(self, name: str, **config_kwargs) -> CircuitBreaker:
        """Get or create a circuit breaker."""
        async with self._lock:
            if name not in self._breakers:
                config = CircuitBreakerConfig(**config_kwargs)
                self._breakers[name] = CircuitBreaker(name=name, config=config)
                logger.info(f"Created circuit breaker: {name}")
            return self._breakers[name]

    async def execute(
        self,
        name: str,
        func: Callable,
        *args,
        fallback: Any = None,
        **kwargs
    ) -> Any:
        """Execute a function with circuit breaker protection."""
        breaker = await self.get_breaker(name)

        if not await breaker.can_execute():
            logger.debug(f"Circuit breaker '{name}' is OPEN, using fallback")
            if fallback is not None:
                return fallback
            raise CircuitBreakerOpenError(
                f"Circuit breaker '{name}' is open. Service unavailable."
            )

        try:
            result = await func(*args, **kwargs)
            await breaker.record_success()
            return result
        except Exception as e:
            await breaker.record_failure()
            raise

    def get_all_status(self) -> dict[str, dict[str, Any]]:
        """Get status of all circuit breakers."""
        return {name: b.get_status() for name, b in self._breakers.items()}


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass


# Global circuit breaker manager
circuit_breaker_manager = CircuitBreakerManager()

# Pre-configured circuit breakers for different services
NIM_CIRCUIT_BREAKER = "nim_api"
WORKSPACE_CIRCUIT_BREAKER = "workspace"