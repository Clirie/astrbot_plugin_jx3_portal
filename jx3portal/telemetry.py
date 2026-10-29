"""Runtime counters and a bounded request log for the admin dashboard."""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Iterable


class Telemetry:
    def __init__(self, max_logs: int = 400) -> None:
        self.max_logs = max(50, int(max_logs))
        self._lock = threading.Lock()
        self._logs: deque[dict[str, Any]] = deque(maxlen=self.max_logs)
        self._log_id = 0
        self.started_at = time.time()
        self.started_monotonic = time.monotonic()
        self.total_requests = 0
        self.ok_requests = 0
        self.failed_requests = 0
        self.total_duration_ms = 0
        self.commands: dict[str, int] = {}
        self.command_timings: dict[str, deque] = {}
        self.sources: dict[str, dict[str, int]] = {}

    # ------------------------------------------------------------------ write
    def record_http(
        self,
        *,
        source: str,
        path: str,
        ok: bool,
        status: int | None,
        duration_ms: float,
        message: str = "",
    ) -> None:
        with self._lock:
            self.total_requests += 1
            self.total_duration_ms += int(duration_ms)
            bucket = self.sources.setdefault(
                source, {"total": 0, "ok": 0, "failed": 0}
            )
            bucket["total"] += 1
            if ok:
                self.ok_requests += 1
                bucket["ok"] += 1
            else:
                self.failed_requests += 1
                bucket["failed"] += 1
            level = "info" if ok else ("warn" if status and status < 500 else "error")
            self._append_locked(
                level=level,
                source=source,
                message=message or path,
                status=status,
                duration_ms=duration_ms,
                path=path,
            )

    def record_command(self, key: str) -> None:
        with self._lock:
            self.commands[key] = self.commands.get(key, 0) + 1

    def record_command_duration(self, key: str, duration_ms: float, phase: str = 'handler') -> None:
        with self._lock:
            self.command_timings.setdefault(key + ':' + phase, deque(maxlen=200)).append(round(duration_ms, 1))

    def log(
        self,
        level: str,
        source: str,
        message: str,
        *,
        status: int | None = None,
        duration_ms: float | None = None,
    ) -> None:
        with self._lock:
            self._append_locked(
                level=level,
                source=source,
                message=message,
                status=status,
                duration_ms=duration_ms,
            )

    def _append_locked(
        self,
        *,
        level: str,
        source: str,
        message: str,
        status: int | None = None,
        duration_ms: float | None = None,
        path: str = "",
    ) -> None:
        self._log_id += 1
        entry = {
            "id": self._log_id,
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "level": level,
            "source": source,
            "message": str(message)[:500],
            "status": status,
            "duration_ms": int(duration_ms) if duration_ms is not None else None,
            "path": path,
        }
        self._logs.appendleft(entry)

    # ------------------------------------------------------------------- read
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            total = self.total_requests
            average = round(self.total_duration_ms / total, 1) if total else 0.0
            success_rate = round(self.ok_requests / total, 4) if total else 0.0
            commands = sorted(
                (
                    {"key": key, "count": count}
                    for key, count in self.commands.items()
                ),
                key=lambda item: item["count"],
                reverse=True,
            )
            return {
                "started_at": datetime.fromtimestamp(self.started_at)
                .astimezone()
                .isoformat(timespec="seconds"),
                "uptime_seconds": int(time.monotonic() - self.started_monotonic),
                "requests": {
                    "total": total,
                    "ok": self.ok_requests,
                    "failed": self.failed_requests,
                    "success_rate": success_rate,
                    "avg_ms": average,
                },
                "sources": {key: dict(value) for key, value in self.sources.items()},
                "commands": commands,
                "command_timings": {key: {"samples": len(values), "median_ms": sorted(values)[len(values)//2], "p95_ms": sorted(values)[min(len(values)-1, int(len(values)*.95))], "max_ms": max(values)} for key, values in self.command_timings.items()},
                "log_count": len(self._logs),
            }

    def logs(
        self,
        *,
        limit: int = 100,
        level: str | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(500, int(limit)))
        level = (level or "").strip().lower()
        query = (query or "").strip().lower()
        with self._lock:
            items: Iterable[dict[str, Any]] = list(self._logs)
        result: list[dict[str, Any]] = []
        for entry in items:
            if level and level != "all" and entry["level"] != level:
                continue
            if query and query not in (
                f"{entry['source']} {entry['message']} {entry.get('path', '')}"
            ).lower():
                continue
            result.append(dict(entry))
            if len(result) >= limit:
                break
        return result

    def clear_logs(self) -> int:
        with self._lock:
            count = len(self._logs)
            self._logs.clear()
            return count

    def reset_stats(self) -> None:
        with self._lock:
            self.started_at = time.time()
            self.started_monotonic = time.monotonic()
            self.total_requests = 0
            self.ok_requests = 0
            self.failed_requests = 0
            self.total_duration_ms = 0
            self.commands.clear()
            self.command_timings.clear()
            self.sources.clear()
