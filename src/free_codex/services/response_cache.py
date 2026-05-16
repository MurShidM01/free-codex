"""Response caching with cache invalidation support."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from ..utils.free_codex_paths import free_codex_dir

logger = logging.getLogger("free-codex.cache")


@dataclass
class CacheConfig:
    enabled: bool = True
    ttl_seconds: int = 300
    max_entries: int = 100
    cache_dir: Optional[Path] = None


@dataclass
class CacheEntry:
    key: str
    value: Any
    created_at: float
    expires_at: float
    hit_count: int = 0
    tags: set[str] = field(default_factory=set)

    def is_expired(self, now: float) -> bool:
        return now > self.expires_at


class CacheEvent:
    """Cache event for invalidation."""

    ENTRY_CREATED = "entry_created"
    ENTRY_INVALIDATED = "entry_invalidated"
    ENTRY_EXPIRED = "entry_expired"
    CACHE_CLEARED = "cache_cleared"


class CacheEventBus:
    """Simple event bus for cache events."""

    def __init__(self):
        self._subscribers: list[Callable[[str, Any], None]] = []
        self._lock = asyncio.Lock()

    async def subscribe(self, handler: Callable):
        """Subscribe to cache events."""
        async with self._lock:
            self._subscribers.append(handler)

    async def unsubscribe(self, handler: Callable):
        """Unsubscribe from cache events."""
        async with self._lock:
            if handler in self._subscribers:
                self._subscribers.remove(handler)

    async def publish(self, event: str, data: Any = None):
        """Publish an event to all subscribers."""
        async with self._lock:
            for handler in self._subscribers:
                try:
                    await handler(event, data)
                except Exception as e:
                    logger.debug(f"Event handler error: {e}")


class ResponseCache:
    """In-memory cache with event-based invalidation."""

    def __init__(self, config: CacheConfig | None = None):
        self.config = config or CacheConfig()
        if self.config.cache_dir is None:
            self.config.cache_dir = free_codex_dir() / "cache"
        self.config.cache_dir.mkdir(parents=True, exist_ok=True)

        self._cache: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
        self._persist_lock = asyncio.Lock()
        self._event_bus = CacheEventBus()

        # Start expiration checker task
        self._expiry_task: asyncio.Task | None = None

    @staticmethod
    def _hash_key(key: str) -> str:
        """Create a safe filename hash."""
        return hashlib.sha256(key.encode()).hexdigest()[:32]

    def _key_to_file(self, key: str) -> Path:
        """Get the file path for a cache key."""
        return self.config.cache_dir / f"{self._hash_key(key)}.json"

    async def subscribe(self, handler: Callable):
        """Subscribe to cache events."""
        await self._event_bus.subscribe(handler)

    async def invalidate(
        self,
        key: Optional[str] = None,
        tags: Optional[set[str]] = None,
        pattern: Optional[str] = None,
    ) -> int:
        """Invalidate cache entries.

        Args:
            key: Specific key to invalidate
            tags: Invalidate entries with any of these tags
            pattern: Invalidate entries whose keys match pattern

        Returns:
            Number of entries invalidated
        """
        count = 0
        async with self._lock:
            now = time.time()
            keys_to_delete = set()

            for k, entry in self._cache.items():
                should_delete = False

                if key and k == key:
                    should_delete = True

                if tags and entry.tags & tags:
                    should_delete = True

                if pattern and pattern in k:
                    should_delete = True

                if should_delete:
                    keys_to_delete.add(k)

            for k in keys_to_delete:
                del self._cache[k]
                count += 1
                # Publish event
                asyncio.create_task(
                    self._event_bus.publish(CacheEvent.ENTRY_INVALIDATED, k)
                )
                # Delete from disk
                file_path = self._key_to_file(k)
                if file_path.exists():
                    try:
                        file_path.unlink()
                    except Exception:
                        pass

        if count > 0:
            logger.info(f"Cache invalidated: {count} entries removed")
        return count

    async def invalidate_all(self) -> None:
        """Clear all cache entries."""
        async with self._lock:
            self._cache.clear()

        # Clear disk cache
        if self.config.cache_dir.exists():
            for f in self.config.cache_dir.glob("*.json"):
                try:
                    f.unlink()
                except Exception:
                    pass

        await self._event_bus.publish(CacheEvent.CACHE_CLEARED)
        logger.info("Cache cleared")

    async def get(self, key: str) -> Optional[Any]:
        """Get a value from cache."""
        if not self.config.enabled:
            return None

        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None

            now = time.time()
            if entry.is_expired(now):
                del self._cache[key]
                asyncio.create_task(
                    self._event_bus.publish(CacheEvent.ENTRY_EXPIRED, key)
                )
                return None

            entry.hit_count += 1
            logger.debug(f"Cache hit: {key[:50]}... (hits: {entry.hit_count})")
            return entry.value

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        tags: Optional[set[str]] = None,
    ) -> None:
        """Set a value in cache."""
        if not self.config.enabled:
            return

        ttl = ttl or self.config.ttl_seconds
        now = time.time()

        async with self._lock:
            # Evict if at capacity
            if len(self._cache) >= self.config.max_entries:
                await self._evict_oldest()

            entry = CacheEntry(
                key=key,
                value=value,
                created_at=now,
                expires_at=now + ttl,
                tags=tags or set(),
            )
            self._cache[key] = entry

            # Persist to disk asynchronously
            asyncio.create_task(self._persist_entry(entry))

            # Publish event
            asyncio.create_task(
                self._event_bus.publish(CacheEvent.ENTRY_CREATED, key)
            )

    async def delete(self, key: str) -> None:
        """Delete a key from cache."""
        await self.invalidate(key=key)

    async def clear(self) -> None:
        """Clear all cache entries."""
        await self.invalidate_all()

    async def _evict_oldest(self) -> None:
        """Evict the oldest entry (by hit count, then expiry)."""
        if not self._cache:
            return

        oldest_key = min(
            self._cache.keys(),
            key=lambda k: (self._cache[k].hit_count, self._cache[k].expires_at)
        )
        del self._cache[oldest_key]

    async def _persist_entry(self, entry: CacheEntry) -> None:
        """Persist a cache entry to disk."""
        async with self._persist_lock:
            try:
                file_path = self._key_to_file(entry.key)
                data = {
                    "key": entry.key,
                    "value": entry.value,
                    "created_at": entry.created_at,
                    "expires_at": entry.expires_at,
                    "hit_count": entry.hit_count,
                    "tags": list(entry.tags),
                }
                file_path.write_text(json.dumps(data, default=str), encoding="utf-8")
            except Exception as e:
                logger.debug(f"Failed to persist cache entry: {e}")

    async def load_from_disk(self) -> None:
        """Load cache entries from disk on startup."""
        if not self.config.cache_dir.exists():
            return

        async with self._lock:
            now = time.time()
            loaded = 0
            for file_path in self.config.cache_dir.glob("*.json"):
                try:
                    data = json.loads(file_path.read_text(encoding="utf-8"))
                    entry = CacheEntry(
                        key=data["key"],
                        value=data["value"],
                        created_at=data["created_at"],
                        expires_at=data["expires_at"],
                        hit_count=data.get("hit_count", 0),
                        tags=set(data.get("tags", [])),
                    )
                    if not entry.is_expired(now):
                        self._cache[entry.key] = entry
                        loaded += 1
                except Exception:
                    pass

        if loaded > 0:
            logger.info(f"Loaded {loaded} cache entries from disk")

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        now = time.time()
        total_hits = sum(e.hit_count for e in self._cache.values())
        expired = sum(1 for e in self._cache.values() if e.is_expired(now))

        return {
            "enabled": self.config.enabled,
            "entries": len(self._cache),
            "max_entries": self.config.max_entries,
            "ttl_seconds": self.config.ttl_seconds,
            "total_hits": total_hits,
            "expired_entries": expired,
            "cache_dir": str(self.config.cache_dir),
        }

    def get_keys_by_tag(self, tag: str) -> list[str]:
        """Get all cache keys with a specific tag."""
        return [k for k, e in self._cache.items() if tag in e.tags]


# Create request-aware cache configuration
def get_cache_for_request(request_body: dict[str, Any]) -> CacheConfig:
    """Get cache configuration based on request characteristics."""
    enabled = True
    ttl = 300

    if request_body.get("stream"):
        enabled = False

    if request_body.get("temperature", 0) > 0.8:
        ttl = 60

    return CacheConfig(enabled=enabled, ttl_seconds=ttl)


def cache_key_from_request(
    model: str,
    messages: list[dict],
    **kwargs
) -> str:
    """Generate a cache key from request parameters."""
    normalized = []
    for msg in messages:
        normalized_msg = {
            "role": msg.get("role"),
            "content": msg.get("content"),
        }
        if msg.get("tool_calls"):
            normalized_msg["tool_calls"] = [
                {"id": tc.get("id"), "function": tc.get("function", {}).get("name")}
                for tc in msg["tool_calls"]
            ]
        normalized.append(normalized_msg)

    key_data = {
        "model": model,
        "messages": normalized,
    }
    for param in ["temperature", "max_tokens", "top_p", "tools", "tool_choice"]:
        if param in kwargs and kwargs[param] is not None:
            key_data[param] = kwargs[param]

    return json.dumps(key_data, sort_keys=True, default=str)


# Global cache instance
response_cache = ResponseCache(CacheConfig(enabled=True, ttl_seconds=300))