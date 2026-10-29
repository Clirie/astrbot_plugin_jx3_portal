"""JX3API endpoint catalog used by help text and the admin debug console."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .assets import DATA_DIR


@lru_cache(maxsize=1)
def endpoints() -> tuple[dict[str, Any], ...]:
    path = DATA_DIR / "endpoints.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ()
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or not str(item.get("path") or "").startswith("/"):
            continue
        result.append(
            {
                "path": str(item.get("path")),
                "summary": str(item.get("summary") or item.get("path")),
                "category": str(item.get("category") or "其他"),
                "level": int(item.get("level") or 0),
                "ticket": bool(item.get("ticket")),
                "params": [
                    {
                        "name": str(param.get("name") or ""),
                        "type": str(param.get("type") or "string"),
                        "required": bool(param.get("required")),
                        "description": str(param.get("description") or ""),
                    }
                    for param in item.get("params") or []
                    if isinstance(param, dict)
                ],
            }
        )
    return tuple(result)


@lru_cache(maxsize=1)
def endpoint_map() -> dict[str, dict[str, Any]]:
    return {item["path"]: item for item in endpoints()}


def get_endpoint(path: str) -> dict[str, Any] | None:
    normalized = str(path or "").strip()
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    return endpoint_map().get(normalized)


def categories() -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in endpoints():
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    return [
        {"name": name, "count": count}
        for name, count in sorted(counts.items(), key=lambda pair: pair[0])
    ]


def search(query: str = "", *, limit: int = 60) -> list[dict[str, Any]]:
    text = str(query or "").strip().lower()
    result: list[dict[str, Any]] = []
    for item in endpoints():
        haystack = f"{item['path']} {item['summary']} {item['category']}".lower()
        if text and text not in haystack:
            continue
        result.append(item)
        if len(result) >= limit:
            break
    return result


def public_catalog() -> dict[str, Any]:
    return {
        "count": len(endpoints()),
        "categories": categories(),
        "items": list(endpoints()),
    }
