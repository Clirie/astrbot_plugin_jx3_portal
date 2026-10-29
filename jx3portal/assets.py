"""Static game data bundled with the plugin (心法 / 区服)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=1)
def kungfu_entries() -> tuple[dict[str, Any], ...]:
    try:
        raw = json.loads((DATA_DIR / "kungfu.json").read_text(encoding="utf-8"))
    except Exception:
        return ()
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        result.append(
            {
                "pzid": int(item.get("pzid") or 0),
                "name": name,
                "role": str(item.get("role") or ""),
                "aliases": [str(alias) for alias in item.get("aliases") or []],
            }
        )
    return tuple(result)


def find_kungfu(text: str) -> dict[str, Any] | None:
    query = str(text or "").strip()
    if not query:
        return None
    lowered = query.lower()
    for entry in kungfu_entries():
        if entry["name"].lower() == lowered or str(entry["pzid"]) == query:
            return entry
    for entry in kungfu_entries():
        if any(alias.lower() == lowered for alias in entry["aliases"]):
            return entry
    for entry in kungfu_entries():
        if lowered in entry["name"].lower() or any(
            lowered in alias.lower() for alias in entry["aliases"]
        ):
            return entry
    return None


@lru_cache(maxsize=1)
def servers() -> tuple[dict[str, str], ...]:
    try:
        raw = json.loads((DATA_DIR / "servers.json").read_text(encoding="utf-8"))
    except Exception:
        return ()
    result: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            name = str(item.get("server") or "").strip()
            zone = str(item.get("zone") or "").strip()
            if name:
                result.append({"server": name, "zone": zone})
        elif isinstance(item, str) and item.strip():
            result.append({"server": item.strip(), "zone": ""})
    return tuple(result)


def server_names() -> tuple[str, ...]:
    return tuple(item["server"] for item in servers())


def is_server(name: str) -> bool:
    text = str(name or "").strip()
    return any(item["server"] == text for item in servers())


def kungfu_summary() -> dict[str, Any]:
    entries = kungfu_entries()
    roles: dict[str, int] = {}
    for entry in entries:
        role = entry["role"] or "其他"
        roles[role] = roles.get(role, 0) + 1
    return {"count": len(entries), "roles": roles}
