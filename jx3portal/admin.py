"""Backend logic for the visual admin dashboard.

The controller is framework agnostic: every method returns plain Python data
and raises :class:`AdminError` for invalid input.  ``main.py`` only adapts it to
``astrbot.api.web`` request/response helpers, which keeps this file testable.
"""

from __future__ import annotations

import json
import platform
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import PLUGIN_DESC, PLUGIN_NAME, PLUGIN_VERSION, assets, catalog
from .aliases import AliasError, ServerAliasService
from .cache import TTLCache
from .commands import COMMAND_MAP, CommandService
from .doubao import DoubaoClient, DoubaoError
from .event_push import EventPushService
from .http import HTTPStatusError, HttpError, NetworkError
from .jx3api import JX3APIError, JX3APIClient, MissingCredential, describe_jx3_error
from .jx3box import JX3BOXClient, JX3BOXError
from .online import OnlineError, OnlineService
from .paid import PaidError, PaidService
from .render import ImageRenderer, RenderError, asset_summary, list_templates
from .settings import Settings, SettingsError
from .telemetry import Telemetry
from .tuilan import TuilanService


class AdminError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AdminController:
    def __init__(
        self,
        *,
        settings: Settings,
        api: JX3APIClient,
        box: JX3BOXClient,
        tuilan: TuilanService,
        cache: TTLCache,
        telemetry: Telemetry,
        commands: CommandService,
        paid: PaidService | None = None,
        events: EventPushService | None = None,
        doubao: DoubaoClient | None = None,
        online: OnlineService | None = None,
        aliases: ServerAliasService | None = None,
        renderer: ImageRenderer | None = None,
        astrbot_version: str = "",
        data_dir: str | Path | None = None,
    ) -> None:
        self.settings = settings
        self.api = api
        self.box = box
        self.tuilan = tuilan
        self.cache = cache
        self.telemetry = telemetry
        self.commands = commands
        self.paid = paid
        self.events = events
        self.doubao = doubao
        self.online = online
        self.aliases = aliases
        self.renderer = renderer
        self.astrbot_version = astrbot_version
        self.data_dir = data_dir
        # 名片生图模板库：直接用 data_dir 创建，不依赖外部注入 ✅
        self.card_styles: Any = None
        try:
            if data_dir:
                from .card_styles import CardStyleStore
                self.card_styles = CardStyleStore(data_dir)
        except Exception:
            self.card_styles = None
        self.data_dir = Path(data_dir or settings.data_dir)
        self._servers_cache: tuple[float, list[dict[str, Any]]] | None = None

    # ------------------------------------------------------------------ shared
    def _meta(self) -> dict[str, Any]:
        stats = self.telemetry.snapshot()
        return {
            "name": PLUGIN_NAME,
            "display_name": "剑网3百宝箱",
            "description": PLUGIN_DESC,
            "version": PLUGIN_VERSION,
            "python": platform.python_version(),
            "platform": platform.system(),
            "astrbot_version": self.astrbot_version or "—",
            "started_at": stats["started_at"],
            "uptime_seconds": stats["uptime_seconds"],
            "now": datetime.now().astimezone().isoformat(timespec="seconds"),
            "data_dir": str(self.data_dir),
            "endpoint_count": len(catalog.endpoints()),
            "endpoint_categories": len(catalog.categories()),
            "command_count": len(COMMAND_MAP),
            "kungfu_count": len(assets.kungfu_entries()),
            "server_count": len(assets.servers()),
        }

    def _stats(self) -> dict[str, Any]:
        return {
            "runtime": self.telemetry.snapshot(),
            "cache": self.cache.stats(),
            "ticket": self.tuilan.summary(),
        }

    def bootstrap(self) -> dict[str, Any]:
        return {
            "ok": True,
            "meta": self._meta(),
            "settings": self.settings.public(),
            "commands": self.commands.public_catalog(),
            "stats": self._stats(),
            "logs": self.telemetry.logs(limit=40),
            "ticket": self.tuilan.summary(),
            "servers": list(assets.servers()),
            "kungfu": {
                "count": len(assets.kungfu_entries()),
                "roles": assets.kungfu_summary()["roles"],
            },
            "endpoints": {
                "count": len(catalog.endpoints()),
                "categories": catalog.categories(),
            },
            "paid": self.paid.summary() if self.paid else {"enabled": False},
            "events": self.events_summary() if self.events else {"status": {}},
            "aliases": self.aliases.summary() if self.aliases else {"rows": []},
            "render": {
                "available": bool(self.renderer and self.renderer.available),
                "templates": list_templates(),
                "assets": asset_summary(),
            },
            "doubao": self.settings.public()["doubao"],
            "online": self.settings.public()["online"],
        }

    def system(self) -> dict[str, Any]:
        commands_path = self.data_dir / "commands.json"
        return {
            "meta": self._meta(),
            "stats": self._stats(),
            "paths": {
                "data_dir": str(self.data_dir),
                "commands_file": str(commands_path),
                "commands_file_exists": commands_path.exists(),
            },
            "config": {
                "token_configured": bool(self.settings.token),
                "ticket_configured": bool(self.settings.ticket),
                "default_server": self.settings.default_server,
                "jx3api_base": self.settings.jx3api_base,
                "jx3box_cms": self.settings.jx3box_cms,
                "event_push_enabled": self.settings.event_push_enabled,
                "paid_enabled": self.settings.paid_enabled,
                "doubao_configured": bool(self.settings.doubao_api_key),
            },
            "paid": self.paid.summary() if self.paid else {"enabled": False},
            "events": self.events.summary() if self.events else {"status": {}},
        }

    # --------------------------------------------------------------- settings
    def save_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self.settings.save(payload)
        except SettingsError as exc:
            raise AdminError(str(exc)) from exc
        changed = result.get("changed") or []
        self._invalidate_after_config(changed)
        if self.events and any(
            key
            in {
                "event_push_enabled",
                "event_push_wss_url",
                "event_push_token",
                "jx3api_token",
            }
            for key in changed
        ):
            self.events.request_reload()
        self.telemetry.log(
            "info",
            "admin",
            "配置已更新：" + ("、".join(changed) if changed else "无变化"),
        )
        return {
            "ok": True,
            "message": result.get("message", "配置已保存"),
            "changed": changed,
            "settings": self.settings.public(),
        }

    def clear_secret(self, payload: dict[str, Any]) -> dict[str, Any]:
        field = str(payload.get("field") or "").strip()
        try:
            result = self.settings.clear_secret(field)
        except SettingsError as exc:
            raise AdminError(str(exc)) from exc
        self._invalidate_after_config([field])
        self.telemetry.log("warn", "admin", f"已清除 {field}")
        return {"ok": True, "message": result["message"], "settings": self.settings.public()}

    def _invalidate_after_config(self, changed: list[str]) -> None:
        if not changed:
            return
        self.cache.clear("jx3api")
        self.box.clear_local_cache()
        self.api.invalidate_token_stats()
        if any(key in {"jx3api_token", "jx3api_ticket", "jx3api_base_url"} for key in changed):
            self.tuilan.reset_last_result()

    # ------------------------------------------------------------------- test
    async def test(self, payload: dict[str, Any]) -> dict[str, Any]:
        target = str(payload.get("target") or "connect").strip().lower()
        started = time.monotonic()
        try:
            if target in {"connect", "jx3api", "api"}:
                result = await self.api.probe_connect()
            elif target == "token":
                result = await self.api.probe_token()
            elif target == "ticket":
                result = await self.tuilan.validate()
            elif target in {"jx3box", "box"}:
                result = await self.box.probe()
            elif target in {"doubao", "ark"}:
                if self.doubao is None:
                    raise AdminError("豆包服务未初始化")
                result = await self.doubao.probe()
            elif target == "online":
                if self.online is None:
                    raise AdminError("在线查询服务未初始化")
                server = str(payload.get("server") or "").strip()
                name = str(payload.get("name") or "").strip()
                if not server or not name:
                    raise AdminError("请填写测试用的区服和角色名")
                result = await self.online.probe(server, name)
            elif target == "events":
                if self.events is None:
                    raise AdminError("事件推送服务未初始化")
                result = {
                    "ok": bool(self.events.status().get("connected")),
                    "message": (
                        "事件通道已连接"
                        if self.events.status().get("connected")
                        else (self.events.status().get("last_error") or "事件通道未连接")
                    ),
                }
            elif target == "all":
                result = {"ok": True, "message": "全部检查完成", "checks": []}
                checks = [
                    ("connect", self.api.probe_connect),
                    ("token", self.api.probe_token),
                    ("ticket", self.api.probe_ticket),
                    ("jx3box", self.box.probe),
                ]
                if self.doubao is not None and self.doubao.enabled:
                    checks.append(("doubao", self.doubao.probe))
                for label, probe in checks:
                    try:
                        item = await probe()
                        result["checks"].append({"target": label, "ok": True, **item})
                    except Exception as exc:
                        result["checks"].append(
                            {
                                "target": label,
                                "ok": False,
                                "message": _describe(exc),
                            }
                        )
                result["ok"] = all(item["ok"] for item in result["checks"])
            else:
                raise AdminError("未知的测试类型")
        except AdminError:
            raise
        except Exception as exc:
            elapsed = int((time.monotonic() - started) * 1000)
            message = _describe(exc)
            payload_result: dict[str, Any] = {
                "ok": False,
                "target": target,
                "message": message,
                "elapsed_ms": elapsed,
            }
            if isinstance(exc, JX3APIError):
                payload_result["upstream"] = {
                    "code": exc.code,
                    "message": exc.message,
                }
            elif isinstance(exc, HTTPStatusError) and exc.body is not None:
                payload_result["upstream"] = exc.body
            self.telemetry.log("warn", "admin-test", f"{target} 检查失败：{message}")
            return payload_result
        elapsed = int((time.monotonic() - started) * 1000)
        result.setdefault("elapsed_ms", elapsed)
        result["target"] = target
        if result.get("ok"):
            self.telemetry.log(
                "info",
                "admin-test",
                f"{target} 检查成功：{result.get('message', '')}",
            )
        else:
            self.telemetry.log(
                "warn",
                "admin-test",
                f"{target} 检查失败：{result.get('message', '')}",
            )
        return result

    async def token_stats(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        force = bool((payload or {}).get("force"))
        try:
            stats = await self.api.token_stats(force=force)
        except Exception as exc:
            return {"ok": False, "message": _describe(exc), "stats": {}}
        return {"ok": True, "stats": stats}

    # ----------------------------------------------------------- event push
    def events_summary(self) -> dict[str, Any]:
        if self.events is None:
            return {"ok": False, "message": "事件推送服务未初始化"}
        summary = self.events.summary()
        sessions = sorted(
            set(summary.get("subscriptions") or {})
            | set(self.settings.event_push_sessions)
        )
        summary["session_status"] = {
            session: self.events.status_rows(session) for session in sessions
        }
        return {"ok": True, **summary, "settings": self.settings.public()["event_push"]}

    def events_session_save(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.events is None:
            raise AdminError("事件推送服务未初始化")
        session = str((payload or {}).get("session_id") or "").strip()
        actions = (payload or {}).get("actions")
        if not isinstance(actions, list):
            raise AdminError("actions 必须是事件编号列表")
        try:
            self.events.set_session_actions(session, actions)
        except ValueError as exc:
            raise AdminError(str(exc)) from exc
        self.telemetry.log("info", "admin", f"事件订阅已更新 {session}")
        result = self.events_summary()
        result["message"] = "会话推送订阅已保存"
        return result

    async def events_reload(self) -> dict[str, Any]:
        if self.events is None:
            raise AdminError("事件推送服务未初始化")
        await self.events.reload()
        return {"ok": True, "message": "事件通道已重新连接", **self.events.summary()}

    # --------------------------------------------------------------- 区服别名
    def aliases_summary(self) -> dict[str, Any]:
        if self.aliases is None:
            return {"ok": False, "message": "区服别名服务未初始化", "rows": []}
        return {"ok": True, **self.aliases.summary()}

    def save_aliases(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.aliases is None:
            raise AdminError("区服别名服务未初始化")
        try:
            result = self.aliases.save(payload)
        except AliasError as exc:
            raise AdminError(str(exc)) from exc
        self.telemetry.log("info", "admin", "区服别名已保存")
        return result

    def reset_aliases(self) -> dict[str, Any]:
        if self.aliases is None:
            raise AdminError("区服别名服务未初始化")
        result = self.aliases.reset()
        self.telemetry.log("info", "admin", "区服别名已恢复默认")
        return result

    # --------------------------------------------------------------- 图片模板
    def render_summary(self) -> dict[str, Any]:
        return {
            "ok": True,
            "available": bool(self.renderer and self.renderer.available),
            "templates": list_templates(),
            "assets": asset_summary(),
        }

    async def render_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.renderer is None or not self.renderer.available:
            raise AdminError("当前 AstrBot 未启用 html_render，无法预览图片")
        page = str((payload or {}).get("page") or "richangyuche").strip()
        data = (payload or {}).get("data")
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise AdminError("data 必须是 JSON 对象")
        try:
            url = await self.renderer.render(page, data, use_cache=False)
            if Path(url).is_file():
                from .render import _data_uri
                url = _data_uri(Path(url))
        except RenderError as exc:
            raise AdminError(exc.message) from exc
        except Exception as exc:
            raise AdminError(f"图片渲染失败：{exc}") from exc
        return {"ok": True, "page": page, "url": url}

    # --------------------------------------------------------------- 付费授权
    def paid_summary(self) -> dict[str, Any]:
        if self.paid is None:
            return {"ok": False, "message": "付费授权服务未初始化"}
        return {"ok": True, **self.paid.summary()}

    def paid_group_save(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.paid is None:
            raise AdminError("付费授权服务未初始化")
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            raise AdminError("会话 ID 不能为空")
        try:
            if payload.get("extend_days") not in (None, ""):
                result = self.paid.extend_group(session_id, payload["extend_days"])
            else:
                result = self.paid.add_group(
                    session_id=session_id,
                    note=str(payload.get("note") or ""),
                    expires_at=payload.get("expires_at") or None,
                    active=bool(payload.get("active", True)),
                )
        except PaidError as exc:
            raise AdminError(str(exc)) from exc
        self.telemetry.log("info", "admin", f"付费授权保存：{session_id}")
        return {"ok": True, **result, **self.paid.summary()}

    def paid_group_delete(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.paid is None:
            raise AdminError("付费授权服务未初始化")
        try:
            result = self.paid.delete_group(str(payload.get("session_id") or ""))
        except PaidError as exc:
            raise AdminError(str(exc)) from exc
        self.telemetry.log("warn", "admin", "付费授权删除")
        return {"ok": True, **result, **self.paid.summary()}

    def paid_codes_generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.paid is None:
            raise AdminError("付费授权服务未初始化")
        try:
            created = self.paid.generate_codes(
                days=payload.get("days", 30),
                count=payload.get("count", 1),
                note=str(payload.get("note") or ""),
            )
        except PaidError as exc:
            raise AdminError(str(exc)) from exc
        self.telemetry.log("info", "admin", f"生成激活码 {len(created)} 个")
        return {
            "ok": True,
            "message": f"已生成 {len(created)} 个激活码",
            "created": created,
            **self.paid.summary(),
        }

    def paid_codes_delete(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.paid is None:
            raise AdminError("付费授权服务未初始化")
        try:
            result = self.paid.delete_code(str(payload.get("code") or ""))
        except PaidError as exc:
            raise AdminError(str(exc)) from exc
        return {"ok": True, **result, **self.paid.summary()}

    # ------------------------------------------------------------- 豆包 / 在线
    async def doubao_test(self) -> dict[str, Any]:
        if self.doubao is None:
            raise AdminError("豆包服务未初始化")
        result = await self.doubao.probe()
        return {"ok": bool(result.get("ok")), **result}

    async def online_test(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.online is None:
            raise AdminError("在线查询服务未初始化")
        server = str(payload.get("server") or "").strip()
        name = str(payload.get("name") or "").strip()
        if not server or not name:
            raise AdminError("请填写测试用的区服和角色名")
        try:
            result = await self.online.probe(server, name)
        except OnlineError as exc:
            raise AdminError(str(exc)) from exc
        return {"ok": True, **result}

    # --------------------------------------------------------------- commands
    def save_commands(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise AdminError("请求体必须是 JSON 对象")
        if payload.get("reset"):
            try:
                self.settings.reset_command_overrides()
            except SettingsError as exc:
                raise AdminError(str(exc)) from exc
            self.commands.reset_runtime()
            self.telemetry.log("info", "admin", "指令配置已恢复默认")
            return {
                "ok": True,
                "message": "指令配置已恢复默认",
                "commands": self.commands.public_catalog(),
            }

        disabled = payload.get("disabled") or []
        cooldowns = payload.get("cooldowns") or {}
        permissions = payload.get("permissions") or {}
        if not isinstance(disabled, list):
            raise AdminError("disabled 必须是列表")
        valid_keys = set(COMMAND_MAP)
        for key in disabled:
            if key not in valid_keys:
                raise AdminError(f"未知指令：{key}")
        for mapping, label in ((cooldowns, "冷却"), (permissions, "权限")):
            if not isinstance(mapping, dict):
                raise AdminError(f"{label}配置必须是对象")
            for key in mapping:
                if key not in valid_keys:
                    raise AdminError(f"未知指令：{key}")
        try:
            self.settings.save_command_overrides(
                {
                    "disabled": disabled,
                    "cooldowns": cooldowns,
                    "permissions": permissions,
                }
            )
        except SettingsError as exc:
            raise AdminError(str(exc)) from exc
        self.commands.reset_runtime()
        self.telemetry.log(
            "info",
            "admin",
            f"指令配置已保存（关闭 {len(disabled)} 个）",
        )
        return {
            "ok": True,
            "message": "指令配置已保存",
            "commands": self.commands.public_catalog(),
        }

    # ------------------------------------------------------------------ cache
    def cache_stats(self) -> dict[str, Any]:
        return {"ok": True, "cache": self.cache.stats()}

    def clear_cache(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        scope = str((payload or {}).get("scope") or "all").strip().lower()
        if scope in {"all", ""}:
            removed = self.cache.clear()
            self.box.clear_local_cache()
            if self.renderer:
                self.renderer.clear_cache()
            message = f"已清空全部缓存（{removed} 条）"
        elif scope == "jx3api":
            removed = self.cache.clear("jx3api")
            message = f"已清空 JX3API 缓存（{removed} 条）"
        elif scope in {"jx3box", "box"}:
            removed = 0
            for namespace in list(self.cache.stats()["namespaces"]):
                if namespace.startswith("jx3box"):
                    removed += self.cache.clear(namespace)
            self.box.clear_local_cache()
            message = f"已清空 JX3BOX 缓存（{removed} 条）"
        else:
            raise AdminError("未知的缓存范围")
        self.telemetry.log("info", "admin", message)
        return {"ok": True, "message": message, "cache": self.cache.stats()}

    # ------------------------------------------------------------------- logs
    def logs(self, query: dict[str, Any] | None = None) -> dict[str, Any]:
        params = query or {}
        try:
            limit = int(params.get("limit") or 100)
        except (TypeError, ValueError):
            limit = 100
        level = str(params.get("level") or "").strip().lower()
        search = str(params.get("q") or "").strip()
        items = self.telemetry.logs(limit=limit, level=level or None, query=search or None)
        return {"ok": True, "logs": items, "count": len(items)}

    def clear_logs(self) -> dict[str, Any]:
        removed = self.telemetry.clear_logs()
        # Do not append an "admin cleared logs" entry: the user explicitly
        # asked for an empty log and the UI already shows a toast.
        return {"ok": True, "message": f"已清空 {removed} 条日志"}

    def reset_stats(self) -> dict[str, Any]:
        self.telemetry.reset_stats()
        self.telemetry.log("info", "admin", "统计数据已重置")
        return {"ok": True, "message": "统计数据已重置", "stats": self._stats()}

    # --------------------------------------------------------------- endpoints
    def endpoints(self, query: dict[str, Any] | None = None) -> dict[str, Any]:
        params = query or {}
        search = str(params.get("q") or "").strip()
        items = catalog.search(search, limit=120)
        return {
            "ok": True,
            "count": len(items),
            "total": len(catalog.endpoints()),
            "categories": catalog.categories(),
            "items": items,
        }

    async def servers(self, *, force: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if (
            not force
            and self._servers_cache is not None
            and now - self._servers_cache[0] < 600
        ):
            return {
                "ok": True,
                "cached": True,
                "servers": self._servers_cache[1],
            }
        try:
            data = await self.api.server_status()
            rows = data if isinstance(data, list) else []
            servers: list[dict[str, Any]] = []
            zones = {item["server"]: item["zone"] for item in assets.servers()}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("server") or "").strip()
                if not name:
                    continue
                servers.append(
                    {
                        "server": name,
                        "zone": str(row.get("zone") or zones.get(name, "")),
                        "status": row.get("status"),
                        "lasttime": row.get("lasttime"),
                    }
                )
            if servers:
                servers.sort(key=lambda item: (item["zone"], item["server"]))
                self._servers_cache = (now, servers)
                return {"ok": True, "cached": False, "servers": servers}
            raise AdminError("JX3API 未返回区服数据")
        except Exception as exc:
            fallback = [dict(item) for item in assets.servers()]
            return {
                "ok": False,
                "cached": True,
                "servers": fallback,
                "message": _describe(exc),
                "fallback": True,
            }

    # ------------------------------------------------------------------ debug
    async def debug_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise AdminError("请求体必须是 JSON 对象")
        path = str(payload.get("path") or "").strip()
        if not path.startswith("/"):
            path = "/" + path
        if "://" in path or ".." in path or len(path) > 200 or " " in path:
            raise AdminError("接口路径不合法")
        auth = str(payload.get("auth") or "auto").strip().lower()
        if auth not in {"auto", "none", "token", "both", "ticket"}:
            raise AdminError("auth 只能是 auto / none / token / both")
        raw_params = payload.get("params") or {}
        if not isinstance(raw_params, dict):
            raise AdminError("params 必须是对象")
        if len(raw_params) > 40:
            raise AdminError("参数过多")
        params: dict[str, Any] = {}
        for key, value in raw_params.items():
            name = str(key).strip()
            if not name or not all(ch.isalnum() or ch in "_-" for ch in name):
                raise AdminError(f"参数名不合法：{key}")
            if value is None or value == "":
                continue
            if isinstance(value, (dict, list)):
                raise AdminError(f"参数 {name} 只能是字符串或数字")
            params[name] = value

        started = time.monotonic()
        try:
            data = await self.api.request(
                path,
                params,
                auth=auth,
                use_cache=False,
                source="admin-debug",
            )
        except Exception as exc:
            elapsed = int((time.monotonic() - started) * 1000)
            result = {
                "ok": False,
                "path": path,
                "auth": auth,
                "elapsed_ms": elapsed,
                "message": _describe(exc),
            }
            if isinstance(exc, HTTPStatusError) and exc.body is not None:
                result["upstream"] = exc.body
            self.telemetry.log("warn", "admin-debug", f"{path} 调试失败：{result['message']}")
            return result
        elapsed = int((time.monotonic() - started) * 1000)
        preview = _json_preview(data)
        self.telemetry.log("info", "admin-debug", f"{path} 调试成功（{elapsed}ms）")
        return {
            "ok": True,
            "path": path,
            "auth": auth,
            "elapsed_ms": elapsed,
            "data": data,
            "preview": preview,
        }

    # ----------------------------------------------------------------- export
    def export_config(self) -> dict[str, Any]:
        return {
            "plugin": PLUGIN_NAME,
            "version": PLUGIN_VERSION,
            "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "note": "此文件不包含 Token / Ticket 明文，可安全分享或备份。",
            "settings": self.settings.public(),
            "commands": self.commands.public_catalog(),
        }

    # ------------------------------------------------------- 名片生图模板
    def card_styles_summary(self) -> dict[str, Any]:
        store = getattr(self, "card_styles", None)
        if store is None:
            # 兜底：现场创建一个 ✅
            try:
                from .card_styles import CardStyleStore
                d = getattr(self, "_data_dir", None) or getattr(self, "data_dir", None)
                if d:
                    store = CardStyleStore(d)
                    self.card_styles = store
            except Exception as exc:
                return {"ok": False, "message": f"模板库初始化失败：{type(exc).__name__}", "rows": []}
        if store is None:
            return {"ok": False, "message": "模板库未初始化（缺少 data_dir）", "rows": []}
        rows = store.all()
        return {"ok": True, "rows": rows, "count": len(rows)}

    def card_styles_save(self, payload: dict[str, Any]) -> dict[str, Any]:
        store = getattr(self, "card_styles", None)
        if store is None:
            raise AdminError("模板库未初始化")
        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise AdminError("rows 必须是数组")
        results = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = str(row.get("key") or "").strip()
            if not key:
                key = str(row.get("label") or "").strip() or f"style{len(results)+1}"
            if store.get(key) is None:
                status, _ = store.add({**row, "key": key})
            else:
                store.update(key, row)
                status = "ok"
            results.append({"key": key, "status": status})
        self.telemetry.log("info", "admin", f"名片模板已保存 {len(results)} 条")
        return {"ok": True, "rows": store.all(), "saved": results}

    def card_styles_delete(self, payload: dict[str, Any]) -> dict[str, Any]:
        store = getattr(self, "card_styles", None)
        if store is None:
            raise AdminError("模板库未初始化")
        key = str(payload.get("key") or "").strip()
        if not key:
            raise AdminError("请提供要删除的模板 key")
        removed = store.delete(key)
        if removed is None:
            raise AdminError(f"没有找到模板 {key}")
        self.telemetry.log("info", "admin", f"名片模板已删除：{key}")
        return {"ok": True, "rows": store.all(), "removed": removed}

    def card_styles_reset(self) -> dict[str, Any]:
        store = getattr(self, "card_styles", None)
        if store is None:
            raise AdminError("模板库未初始化")
        n = store.reset()
        self.telemetry.log("info", "admin", f"名片模板已恢复默认（{n} 个）")
        return {"ok": True, "rows": store.all(), "count": n}



def _describe(exc: BaseException) -> str:
    if isinstance(exc, (JX3APIError, MissingCredential)):
        return describe_jx3_error(exc)
    if isinstance(exc, JX3BOXError):
        return exc.message
    if isinstance(exc, (PaidError, OnlineError, DoubaoError)):
        return str(exc)
    if isinstance(exc, NetworkError):
        return exc.message
    if isinstance(exc, HttpError):
        return exc.message
    if isinstance(exc, AdminError):
        return exc.message
    return str(exc) or type(exc).__name__


def _json_preview(data: Any, limit: int = 100_000) -> str:
    try:
        text = json.dumps(data, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        text = str(data)
    if len(text) > limit:
        text = text[:limit] + "\n…（已截断）"
    return text
