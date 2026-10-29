"""区服别名：把「双梦」「华乾」等群内简称解析成正式区服名。

数据保存在插件数据目录的 ``server_aliases.json``，首次运行从随包
``data/server_aliases.json`` 复制一份。后台可以增删别名，也可以恢复种子。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from . import assets
from .storage import write_json as _atomic_write


class AliasError(ValueError):
    pass




class ServerAliasService:
    def __init__(self, data_dir: str | Path, seed_path: str | Path | None = None) -> None:
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "server_aliases.json"
        self.seed_path = (
            Path(seed_path)
            if seed_path is not None
            else Path(__file__).resolve().parent.parent / "data" / "server_aliases.json"
        )
        self._lock = threading.RLock()
        if not self.path.exists():
            self._copy_seed()
        self._rows = self._load()

    # ------------------------------------------------------------------ storage
    def _copy_seed(self) -> None:
        try:
            if self.seed_path.exists():
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_bytes(self.seed_path.read_bytes())
        except OSError:
            pass

    def _load(self) -> list[dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            raw = []
        if not isinstance(raw, list):
            raw = []
        aliases_by_server: dict[str, list[str]] = {}
        for row in raw:
            if not isinstance(row, dict):
                continue
            server = str(row.get("server") or "").strip()
            if not server:
                continue
            values = row.get("aliases")
            if not isinstance(values, list):
                values = []
            cleaned: list[str] = []
            for value in values:
                alias = str(value or "").strip()
                if alias and alias not in cleaned:
                    cleaned.append(alias)
            aliases_by_server[server] = cleaned
        result: list[dict[str, Any]] = []
        for item in assets.servers():
            server = item["server"]
            result.append(
                {
                    "server": server,
                    "zone": item["zone"],
                    "aliases": aliases_by_server.pop(server, []),
                }
            )
        # Keep custom servers that are not in the bundled catalog.
        for server, aliases in aliases_by_server.items():
            result.append({"server": server, "zone": "", "aliases": aliases})
        return result

    # -------------------------------------------------------------------- query
    def summary(self) -> dict[str, Any]:
        with self._lock:
            rows = [
                {
                    "server": row["server"],
                    "zone": row.get("zone", ""),
                    "aliases": list(row["aliases"]),
                }
                for row in self._rows
            ]
        return {
            "rows": rows,
            "servers": [row["server"] for row in rows],
            "alias_count": sum(len(row["aliases"]) for row in rows),
        }

    def resolve(self, text: Any) -> str:
        value = str(text or "").strip()
        if not value:
            return ""
        found = self.lookup(value)
        return found or value

    def lookup(self, text: Any) -> str | None:
        value = str(text or "").strip()
        if not value:
            return None
        lowered = value.lower()
        with self._lock:
            for row in self._rows:
                if row["server"].lower() == lowered:
                    return row["server"]
            for row in self._rows:
                if any(alias.lower() == lowered for alias in row["aliases"]):
                    return row["server"]
        return None

    def alias_owner(self, alias: str) -> str | None:
        lowered = str(alias or "").strip().lower()
        if not lowered:
            return None
        with self._lock:
            for row in self._rows:
                if any(item.lower() == lowered for item in row["aliases"]):
                    return row["server"]
        return None

    # -------------------------------------------------------------------- admin
    def save(self, payload: dict[str, Any] | list[Any]) -> dict[str, Any]:
        raw_rows = payload.get("rows") if isinstance(payload, dict) else payload
        if not isinstance(raw_rows, list):
            raise AliasError("rows 必须是列表")
        known = {row["server"]: row for row in self._rows}
        seen_alias: dict[str, str] = {}
        new_rows: list[dict[str, Any]] = []
        for raw in raw_rows:
            if not isinstance(raw, dict):
                raise AliasError("每一行必须是对象")
            server = str(raw.get("server") or "").strip()
            if not server:
                raise AliasError("区服名不能为空")
            if not assets.is_server(server) and server not in known:
                raise AliasError(f"未知区服：{server}")
            aliases = raw.get("aliases")
            if not isinstance(aliases, list):
                raise AliasError(f"{server} 的 aliases 必须是列表")
            cleaned: list[str] = []
            for item in aliases:
                alias = str(item or "").strip()
                if not alias:
                    continue
                if len(alias) > 32:
                    raise AliasError("别名不能超过 32 个字符")
                if alias in cleaned:
                    continue
                if alias == server:
                    raise AliasError(f"别名不能和区服名相同：{alias}")
                if assets.is_server(alias):
                    raise AliasError(f"别名不能和正式区服重名：{alias}")
                owner = seen_alias.get(alias.lower())
                if owner and owner != server:
                    raise AliasError(f"别名「{alias}」已被 {owner} 使用")
                seen_alias[alias.lower()] = server
                cleaned.append(alias)
            if len(cleaned) > 30:
                raise AliasError(f"{server} 的别名不能超过 30 个")
            new_rows.append(
                {
                    "server": server,
                    "zone": known.get(server, {}).get("zone", ""),
                    "aliases": cleaned,
                }
            )
        if not new_rows:
            raise AliasError("至少保留一个区服")
        with self._lock:
            _atomic_write(self.path, [{"server": row["server"], "aliases": row["aliases"]} for row in new_rows])
            self._rows = new_rows
        return {"ok": True, "message": "区服别名已保存", **self.summary()}

    def reset(self) -> dict[str, Any]:
        with self._lock:
            rows = json.loads(self.seed_path.read_text(encoding="utf-8"))
            return self.save(rows)
        return {"ok": True, "message": "已恢复默认区服别名", **self.summary()}
