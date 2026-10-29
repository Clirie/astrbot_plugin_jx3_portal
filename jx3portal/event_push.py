"""JX3API WebSocket 事件推送。

移植自参考插件 ``astrbot_plugin_jx3_miemie/core/event_push.py`` 的事件目录、
字段排版和连接方式，但订阅模型简化为「全局目标会话 + 全局事件选择」：

* 后台「事件推送」选择要接收的事件和群会话；
* WebSocket 地址默认 ``wss://socket.nicemoe.cn``，可在后台修改；
* 令牌留空时自动复用 JX3API Token（用户可在后台单独覆盖）；
* 免费事件 2001~2006；其他事件在付费授权开启时只推送给授权有效的群。

传输层依赖 AstrBot 自带的 ``aiohttp``；缺失时事件推送自动禁用，不影响
查询指令。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from .cache import TTLCache
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from .event_catalog import (
    DEFAULT_WSS_URL,
    LOCAL_EVENT_ACTIONS,
    EVENT_ACTIONS,
    EVENT_FIELDS,
    EVENT_INTERFACES,
    EVENT_NAMES,
    FREE_EVENT_ACTIONS,
)
from .paid import PaidService
from .storage import write_json
from .settings import Settings


def format_timestamp(value: Any) -> str:
    try:
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return str(value or "未知")


def format_field(value: Any, value_type: str) -> str:
    if value_type == "time":
        return format_timestamp(value)
    if value_type == "status":
        if value in (0, "0"):
            return "维护"
        if value in (1, "1"):
            return "开服"
        return str(value if value is not None and value != "" else "未知")
    if value_type == "list":
        if isinstance(value, (list, tuple)):
            values = [str(item).strip() for item in value if str(item).strip()]
            return "、".join(values) if values else "无"
    return str(value if value is not None and value != "" else "未知")


def format_event(action: int, detail: dict[str, Any]) -> str:
    fields = EVENT_FIELDS.get(action)
    if not fields:
        return (
            f"【事件推送 · {action}】\n"
            + json.dumps(detail, ensure_ascii=False, indent=2)
        )
    lines = [f"【{EVENT_NAMES[action]}】"]
    for label, key, value_type in fields:
        lines.append(f"{label}：{format_field(detail.get(key), value_type)}")
    return "\n".join(lines)


def _catalog_item(action: int) -> dict[str, Any]:
    label, endpoint = EVENT_INTERFACES.get(action, ("—", ""))
    return {
        "action": action,
        "name": EVENT_NAMES[action],
        "interface": label,
        "endpoint": endpoint,
    }


def event_catalog() -> dict[str, Any]:
    free = [_catalog_item(action) for action in sorted(FREE_EVENT_ACTIONS)]
    paid = [
        _catalog_item(action)
        for action in EVENT_ACTIONS
        if action not in FREE_EVENT_ACTIONS
    ]
    return {"free": free, "paid": paid, "total": len(EVENT_ACTIONS)}


SendCallback = Callable[[str, str], Awaitable[None]]


class EventPushService:
    def __init__(
        self,
        settings: Settings,
        paid: PaidService,
        send_callback: SendCallback | None = None,
        data_dir: str | Any | None = None,
        preview_callback=None,
        server_filter=None,
    ) -> None:
        self.settings = settings
        self.paid = paid
        self.send_callback = send_callback
        self.preview_callback = preview_callback
        self.server_filter = server_filter
        self.news_readings = TTLCache(max_entries=200)
        self._news_tasks: set[asyncio.Task] = set()
        self.data_dir = data_dir
        self._sub_path = (
            Path(data_dir) / "event_subscriptions.json" if data_dir else None
        )
        self._subscriptions: dict[str, set[int]] = self._load_subscriptions()
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._websocket: Any = None
        self._connected = False
        self._last_error = ""
        self._last_event: dict[str, Any] | None = None
        self._received = 0
        self._started_at = 0.0
        self._send_slots = asyncio.Semaphore(8)
        self._recent: dict[str, float] = {}
        self._reload_lock = asyncio.Lock()
        self._reload_task = None
        self._closed = False
        self.on_change = None

    # ------------------------------------------------------------------ lifecycle
    @property
    def aiohttp_available(self) -> bool:
        try:
            import importlib.util

            return importlib.util.find_spec("aiohttp") is not None
        except Exception:  # pragma: no cover - defensive
            return False

    async def start(self) -> None:
        if self.on_change: self.on_change()
        if self._closed or not self.settings.event_push_enabled:
            await self.stop()
            return
        if not self.aiohttp_available:
            self._last_error = "未安装 aiohttp，事件推送不可用（AstrBot 通常自带）"
            return
        if self._task and not self._task.done():
            return
        self._stopping.clear()
        self._started_at = time.time()
        self._task = asyncio.create_task(self._run(), name="jx3-event-push")

    async def stop(self) -> None:
        self._stopping.set()
        if self._websocket is not None:
            with contextlib.suppress(Exception):
                await self._websocket.close()
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        self._websocket = None
        self._connected = False
        tasks = list(self._news_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._news_tasks.clear()

    async def reload(self) -> None:
        async with self._reload_lock:
            await self.stop()
            await self.start()

    def request_reload(self) -> None:
        if self._closed or (self._reload_task and not self._reload_task.done()):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._reload_task = loop.create_task(self.reload())

    async def close(self) -> None:
        self._closed = True
        if self._reload_task and not self._reload_task.done():
            self._reload_task.cancel()
            await asyncio.gather(self._reload_task, return_exceptions=True)
        await self.stop()

    # ------------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.settings.event_push_enabled,
            "running": bool(self._task and not self._task.done()),
            "connected": self._connected,
            "url": self.settings.event_push_wss_url,
            "token_configured": bool(self.settings.event_push_effective_token),
            "token_fallback": not self.settings.event_push_token
            and bool(self.settings.token),
            "actions": self.settings.event_push_actions,
            "sessions": self.settings.event_push_sessions,
            "subscriptions": self.subscriptions_summary(),
            "aiohttp_available": self.aiohttp_available,
            "last_error": self._last_error,
            "last_event": self._last_event,
            "received": self._received,
            "started_at": self._started_at,
        }

    def summary(self) -> dict[str, Any]:
        return {
            "status": self.status(),
            "catalog": event_catalog(),
            "free_actions": sorted(FREE_EVENT_ACTIONS),
            "subscriptions": {
                session: sorted(actions)
                for session, actions in self._subscriptions.items()
            },
        }

    # ------------------------------------------------------------ subscriptions
    def _load_subscriptions(self) -> dict[str, set[int]]:
        if self._sub_path is None or not self._sub_path.is_file():
            return {}
        try:
            raw = json.loads(self._sub_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        result: dict[str, set[int]] = {}
        if isinstance(raw, dict):
            for session, actions in raw.items():
                if not isinstance(actions, list):
                    continue
                cleaned = {
                    int(action)
                    for action in actions
                    if str(action).lstrip("-").isdigit() and int(action) in EVENT_NAMES
                }
                if session:
                    result[str(session)] = cleaned
        return result

    def _save_subscriptions(self, subscriptions) -> None:
        if self._sub_path is not None:
            try:
                write_json(self._sub_path, {session: sorted(actions) for session, actions in subscriptions.items()})
            except OSError as exc:
                raise ValueError("订阅保存失败，请稍后再试。") from exc
        self._subscriptions = subscriptions
        if self.on_change: self.on_change()

    def session_actions(self, session_id: str) -> set[int]:
        return set(self._subscriptions.get(str(session_id), set()))

    def is_subscribed(self, session_id: str, action: int) -> bool:
        actions = self._subscriptions.get(str(session_id))
        if actions is None:
            return int(action) in self.settings.event_push_actions
        return int(action) in actions

    def set_action(self, session_id: str, action: int, enabled: bool) -> None:
        session = str(session_id or "").strip()
        action = int(action)
        if not session or action not in EVENT_NAMES:
            raise ValueError("无效的会话或事件编号")
        actions = set(self._subscriptions.get(session, self.settings.event_push_actions if session in self.settings.event_push_sessions else set()))
        if enabled:
            actions.add(action)
        else:
            actions.discard(action)
        self._save_subscriptions({**self._subscriptions, session: actions})

    def set_all(self, session_id: str, enabled: bool) -> None:
        session = str(session_id or "").strip()
        if not session:
            raise ValueError("会话 ID 不能为空")
        self._save_subscriptions({**self._subscriptions, session: set(self.settings.event_push_actions) if enabled else set()})

    def set_session_actions(self, session_id: str, actions: list[Any]) -> None:
        session = str(session_id or "").strip()
        if not session:
            raise ValueError("会话 ID 不能为空")
        cleaned = {
            int(action)
            for action in actions
            if str(action).lstrip("-").isdigit() and int(action) in EVENT_NAMES
        }
        self._save_subscriptions({**self._subscriptions, session: cleaned})

    def status_rows(self, session_id: str) -> list[dict[str, Any]]:
        actions = self._subscriptions.get(str(session_id))
        source = actions if actions is not None else self.settings.event_push_actions
        return [
            {
                "action": action,
                "name": EVENT_NAMES[action],
                "free": action in FREE_EVENT_ACTIONS,
                "enabled": action in source,
            }
            for action in EVENT_ACTIONS
        ]

    def subscriptions_summary(self) -> list[dict[str, Any]]:
        sessions = sorted(
            set(self._subscriptions) | set(self.settings.event_push_sessions)
        )
        rows = []
        for session in sessions:
            rows.append(
                {
                    "session_id": session,
                    "enabled": sorted(self._subscriptions.get(session, set())),
                    "using_global": session not in self._subscriptions,
                    "count": len(
                        self._subscriptions.get(session)
                        if session in self._subscriptions
                        else self.settings.event_push_actions
                    ),
                }
            )
        return rows

    def _usage_text(self) -> str:
        return (
            "推送 <事件名> 开启 / 关闭\n"
            "推送 开启 / 关闭（当前会话总开关）\n"
            "推送列表（查看全部事件状态）\n"
            "事件名支持中文，例如：推送 开服状态 开启"
        )

    def configure(self, session_id: str, first: str = "", second: str = "") -> str:
        first = str(first or "").strip()
        second = str(second or "").strip()
        lowered = first.lower()
        enable_words = {"开启", "启用", "开", "on"}
        disable_words = {"关闭", "禁用", "关", "off"}
        if not first or lowered in {"状态", "查看", "status"}:
            enabled = [item for item in self.status_rows(session_id) if item["enabled"]]
            return (
                f"当前会话事件推送：{len(enabled)} 个事件开启\n"
                + ("、".join(item["name"] for item in enabled) or "无")
                + "\n\n"
                + self._usage_text()
            )
        if lowered in {"列表", "list"}:
            return self.format_status_list(session_id)
        if not second and lowered in enable_words | disable_words:
            self.set_all(session_id, lowered in enable_words)
            return f"当前会话事件推送已{'开启' if lowered in enable_words else '关闭'}。"
        action_text, switch_text = first, second
        if lowered in enable_words | disable_words and second:
            action_text, switch_text = second, first
        action = self._resolve_action(action_text)
        if action is None:
            return f"未找到事件「{action_text}」。\n" + self._usage_text()
        if switch_text.lower() not in enable_words | disable_words:
            return self._usage_text()
        enabled = switch_text.lower() in enable_words
        self.set_action(session_id, action, enabled)
        return (
            f"已{'开启' if enabled else '关闭'}{EVENT_NAMES[action]}推送。"
        )

    def format_status_list(self, session_id: str) -> str:
        rows = self.status_rows(session_id)
        lines = [f"📡 当前会话事件推送（{len([r for r in rows if r['enabled']])}/{len(rows)}）"]
        for item in rows:
            lines.append(
                f"{'已开' if item['enabled'] else '已关'} · {item['name']}"
                + ("" if item["free"] else "（令牌）")
            )
        lines.append("")
        lines.append(self._usage_text())
        return "\n".join(lines)

    @staticmethod
    def _resolve_action(text: str) -> int | None:
        value = str(text or "").strip()
        if value.isdigit():
            action = int(value)
            return action if action in EVENT_NAMES else None
        matched = [action for action, name in EVENT_NAMES.items() if name == value]
        if not matched:
            matched = [
                action for action, name in EVENT_NAMES.items() if value and value in name
            ]
        return matched[0] if matched else None

    # -------------------------------------------------------------------- socket
    def _connection_url(self) -> str:
        url = self.settings.event_push_wss_url or DEFAULT_WSS_URL
        token = self.settings.event_push_effective_token
        if not token:
            return url
        parts = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
        # JX3API 官方 SDK 使用的事件令牌参数名就是 toekn（历史拼写）。
        query["toekn"] = token
        return urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment)
        )

    async def _run(self) -> None:
        import aiohttp
        from aiohttp import WSMsgType

        timeout = aiohttp.ClientTimeout(total=None, sock_connect=20)
        retry = 0
        while not self._stopping.is_set():
            heartbeat_task: asyncio.Task | None = None
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.ws_connect(
                        self._connection_url(),
                        heartbeat=45,
                        autoping=True,
                        ssl=True,
                    ) as websocket:
                        self._websocket = websocket
                        self._connected = True
                        self._last_error = ""
                        retry = 0
                        heartbeat_task = asyncio.create_task(
                            self._heartbeat(websocket),
                            name="jx3-event-heartbeat",
                        )
                        async for message in websocket:
                            if message.type == WSMsgType.TEXT:
                                await self.handle_payload(message.data)
                            elif message.type in {
                                WSMsgType.CLOSE,
                                WSMsgType.CLOSED,
                                WSMsgType.ERROR,
                            }:
                                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self._stopping.is_set():
                    text = str(exc)
                    token = self.settings.event_push_effective_token
                    if token:
                        text = text.replace(token, "***")
                    self._last_error = f"{type(exc).__name__}: {text[:300]}"
            finally:
                self._connected = False
                self._websocket = None
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await heartbeat_task

            if self._stopping.is_set():
                break
            delay = min(2**retry, 30)
            retry += 1
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    async def _heartbeat(self, websocket: Any) -> None:
        while not self._stopping.is_set() and not websocket.closed:
            await asyncio.sleep(30)
            if not websocket.closed:
                await websocket.send_json({"action": -1})

    # -------------------------------------------------------------------- events
    async def handle_payload(self, payload: str | bytes) -> None:
        try:
            message = json.loads(payload)
        except (TypeError, ValueError):
            return
        if not isinstance(message, dict):
            return
        try:
            action = int(message.get("action"))
        except (TypeError, ValueError):
            return
        if action not in EVENT_NAMES or action in LOCAL_EVENT_ACTIONS:
            return
        if str(message.get("status", "success")).lower() != "success":
            return
        detail = message.get("detail")
        if not isinstance(detail, dict):
            detail = message.get("data")
        if not isinstance(detail, dict):
            return

        self._received += 1
        self._last_event = {
            "action": action,
            "name": EVENT_NAMES[action],
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "detail": detail,
        }

        # A session may opt in/out independently; sessions without an explicit
        # subscription continue to use the global event selection in settings.
        # Deduplicate explicit message ids.
        identity = next(
            (
                message.get(key)
                for key in ("event_id", "eventId", "message_id")
                if message.get(key) is not None
            ),
            None,
        )
        if identity is None and action in {2002, 2003}:
            identity = detail.get("url") or detail.get("title")
        if identity is not None:
            key = f"{action}:{identity}"
            now = time.monotonic()
            self._recent = {
                item: expires for item, expires in self._recent.items() if expires > now
            }
            if key in self._recent:
                return
            self._recent[key] = now + 300

        text = format_event(action, detail)
        sessions = sorted(
            set(self.settings.event_push_sessions) | set(self._subscriptions)
        )
        if not sessions:
            return
        targets = [session for session in sessions if self.is_subscribed(session, action) and (action in FREE_EVENT_ACTIONS or not self.settings.paid_enabled or self.paid.can_use_paid(session))]
        if action == 2001:
            server = str(detail.get("server") or "").strip()
            if not server or self.server_filter is None:
                return
            targets = [session for session in targets if await self.server_filter(session, server)]
        if not targets:
            return
        if action in {2002, 2003} and self.preview_callback and len(self._news_tasks) < 8:
            # Article work must not hold up the socket reader or game events.
            task = asyncio.create_task(self._deliver_news(action, detail, targets, text))
            self._news_tasks.add(task)
            task.add_done_callback(self._news_tasks.discard)
        else:
            await asyncio.gather(*(self._deliver(session, text, action=action) for session in targets))

    async def _deliver_news(self, action, detail, sessions, text):
        images = []
        try:
            images = await asyncio.wait_for(self.preview_callback(action, detail), timeout=55)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._last_error = "新闻配图失败：" + type(exc).__name__
        if action == 2002 and len(images) > 2:
            for session in sessions: self.news_readings.set('push', session, {'paths': list(images), 'caption': text}, 1200)
            images = images[:2]
            text += '\n后续正文：新闻 续看'
        await asyncio.gather(*(self._deliver(session, text, images, action=action) for session in sessions))

    async def _deliver(self, session_id: str, text: str, images: list[str] | None = None, *, action: int) -> None:
        if self.send_callback is None:
            return
        async with self._send_slots:
            if self._stopping.is_set() or not self.is_subscribed(session_id, action):
                return
            if action not in FREE_EVENT_ACTIONS and self.settings.paid_enabled and not self.paid.can_use_paid(session_id):
                return
            try:
                delivery = self.send_callback(session_id, text, images) if images else self.send_callback(session_id, text)
                await asyncio.wait_for(delivery, timeout=20)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - platform specific
                self._last_error = f"推送发送失败：{type(exc).__name__}"
