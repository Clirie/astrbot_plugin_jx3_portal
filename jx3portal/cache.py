"""A small in-process TTL cache with per-namespace statistics."""

from __future__ import annotations

import asyncio
import copy
import time
from typing import Any


class TTLCache:
    """Bounded TTL cache.

    JX3API responses are small JSON documents; an in-process cache avoids a
    database dependency while still protecting the upstream API from chat
    bursts.  Entries are evicted when expired or when the total limit is hit.
    """

    def __init__(self, max_entries: int = 800) -> None:
        self.max_entries = max(50, int(max_entries))
        self._items: dict[tuple[str, str], tuple[float, float, Any]] = {}
        self._hits: dict[str, int] = {}
        self._misses: dict[str, int] = {}
        self._pending: dict[tuple, asyncio.Task] = {}
        self._generation = 0
        self._namespace_generation: dict[str, int] = {}

    def _bucket(self, mapping: dict[str, int], namespace: str) -> int:
        return mapping.get(namespace, 0)

    def get(self, namespace: str, key: str) -> Any | None:
        item = self._items.get((namespace, key))
        if item is None:
            self._misses[namespace] = self._bucket(self._misses, namespace) + 1
            return None
        expires_at, _created, value = item
        if time.monotonic() >= expires_at:
            self._items.pop((namespace, key), None)
            self._misses[namespace] = self._bucket(self._misses, namespace) + 1
            return None
        self._hits[namespace] = self._bucket(self._hits, namespace) + 1
        return copy.deepcopy(value)

    def set(self, namespace: str, key: str, value: Any, ttl: float) -> None:
        if ttl <= 0:
            return
        now = time.monotonic()
        self._items[(namespace, key)] = (now + float(ttl), now, copy.deepcopy(value))
        if len(self._items) > self.max_entries:
            self._prune()

    def _prune(self) -> None:
        now = time.monotonic()
        expired = [key for key, item in self._items.items() if item[0] <= now]
        for key in expired:
            self._items.pop(key, None)
        overflow = len(self._items) - self.max_entries
        if overflow <= 0:
            return
        oldest = sorted(self._items.items(), key=lambda pair: pair[1][1])[:overflow]
        for key, _ in oldest:
            self._items.pop(key, None)

    def clear(self, namespace: str | None = None) -> int:
        if namespace is None:
            self._generation += 1
            self._namespace_generation.clear()
            removed = len(self._items)
            self._items.clear()
        else:
            self._namespace_generation[namespace] = self._namespace_generation.get(namespace, 0) + 1
            removed = 0
            for key in [key for key in self._items if key[0] == namespace]:
                self._items.pop(key, None)
                removed += 1
        return removed

    async def get_or_load(self, namespace: str, key: str, ttl: float, loader, *, share_inflight=False):
        if ttl <= 0 and not share_inflight:
            return await loader()
        cached = self.get(namespace, key) if ttl > 0 else None
        if cached is not None:
            return cached
        generation = (self._generation, self._namespace_generation.get(namespace, 0))
        identity = (namespace, key, generation)
        task = self._pending.get(identity)
        if task is None:
            async def load():
                value = await loader()
                if value is not None and generation == (self._generation, self._namespace_generation.get(namespace, 0)):
                    self.set(namespace, key, value, ttl)
                return value
            task = asyncio.create_task(load())
            self._pending[identity] = task
            def finished(done):
                if self._pending.get(identity) is done:
                    self._pending.pop(identity, None)
                if not done.cancelled():
                    done.exception()
            task.add_done_callback(finished)
        return copy.deepcopy(await asyncio.shield(task))

    async def close(self):
        tasks = list(self._pending.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._pending.clear()

    def stats(self) -> dict[str, Any]:
        self._prune()
        namespaces: dict[str, dict[str, Any]] = {}
        for namespace, _key in self._items:
            namespaces.setdefault(
                namespace,
                {"entries": 0, "hits": 0, "misses": 0, "hit_rate": 0.0},
            )["entries"] += 1
        for namespace, hits in self._hits.items():
            namespaces.setdefault(
                namespace,
                {"entries": 0, "hits": 0, "misses": 0, "hit_rate": 0.0},
            )["hits"] = hits
        for namespace, misses in self._misses.items():
            namespaces.setdefault(
                namespace,
                {"entries": 0, "hits": 0, "misses": 0, "hit_rate": 0.0},
            )["misses"] = misses
        for row in namespaces.values():
            total = row["hits"] + row["misses"]
            row["hit_rate"] = round(row["hits"] / total, 4) if total else 0.0
        total_hits = sum(self._hits.values())
        total_misses = sum(self._misses.values())
        total = total_hits + total_misses
        return {
            "entries": len(self._items),
            "max_entries": self.max_entries,
            "hits": total_hits,
            "misses": total_misses,
            "hit_rate": round(total_hits / total, 4) if total else 0.0,
            "namespaces": dict(sorted(namespaces.items())),
        }
