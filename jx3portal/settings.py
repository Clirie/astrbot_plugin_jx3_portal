"""Configuration handling for the JX3 Portal plugin.

AstrBot stores plugin configuration in ``config.json`` and exposes it through
``AstrBotConfig``.  The admin dashboard writes the same flat keys, so a value
changed in either place is immediately visible to the other one.

Command switches (enable / cooldown / permission) are intentionally stored in
the plugin data directory instead of AstrBot's config: they are a list edited
at runtime and the ``_conf_schema.json`` editor cannot represent them nicely.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import urllib.parse
from pathlib import Path
from typing import Any, Callable

from .storage import write_json
from .tuilan import normalize_ticket

logger = logging.getLogger("astrbot.plugin.jx3_portal.settings")

from .event_catalog import DEFAULT_WSS_URL, EVENT_NAMES, FREE_EVENT_ACTIONS

DEFAULT_JX3API_BASE = "https://www.jx3api.com"
JX3BOX_CMS_BASE = "https://cms.jx3box.com"
JX3BOX_NODE_BASE = "https://node.jx3box.com"
JX3BOX_AUCTION_BASE = "https://next2.jx3box.com"
DEFAULT_DOUBAO_BASE = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_DOUBAO_MODEL = "doubao-seedream-5-0-flash-260915"
DEFAULT_DOUBAO_SIZE = "1024x1024"

# Every key is flat on purpose.  Flat keys work with every AstrBot 4.x config
# editor and keep the dashboard mapping trivial.
DEFAULTS: dict[str, Any] = {
    # ------------------------------------------------------------------ JX3API
    "jx3api_base_url": DEFAULT_JX3API_BASE,
    "jx3api_token": "",
    "jx3api_ticket": "",
    "jx3api_timeout": 20,
    "jx3api_retries": 1,
    "jx3api_cache_ttl": 60,
    "default_server": "",
    # ------------------------------------------------ JX3BOX (fixed in code)
    "jx3box_timeout": 25,
    "jx3box_cache_ttl": 300,
    "jx3box_client": "std",
    "jx3box_global_level": 130,
    # ----------------------------------------------------------- 角色在线服务
    "online_api_url": "",
    "online_api_token": "",
    # ---------------------------------------------------------------- 事件推送
    "event_push_enabled": False,
    "event_push_wss_url": DEFAULT_WSS_URL,
    "event_push_token": "",
    "event_push_actions": sorted(FREE_EVENT_ACTIONS),
    "event_push_sessions": [],
    # ---------------------------------------------------------------- 付费授权
    "paid_enabled": False,
    # ------------------------------------------------------------------ 豆包
    "doubao_api_key": "",
    "doubao_base_url": DEFAULT_DOUBAO_BASE,
    "doubao_model": DEFAULT_DOUBAO_MODEL,
    "doubao_size": DEFAULT_DOUBAO_SIZE,
    "doubao_watermark": False,
    "doubao_timeout": 180,
    # ------------------------------------------------------------------- admin
    "admin_log_limit": 300,
}

SECRET_KEYS = (
    "jx3api_token",
    "jx3api_ticket",
    "online_api_token",
    "event_push_token",
    "doubao_api_key",
)
SECRET_LABELS = {
    "jx3api_token": "JX3API Token",
    "jx3api_ticket": "推栏 Ticket",
    "online_api_token": "在线查询令牌",
    "event_push_token": "事件推送令牌",
    "doubao_api_key": "豆包 API Key",
}

# group -> {field: flat_key}
GROUPS: dict[str, dict[str, str]] = {
    "jx3api": {
        "base_url": "jx3api_base_url",
        "token": "jx3api_token",
        "ticket": "jx3api_ticket",
        "timeout": "jx3api_timeout",
        "retries": "jx3api_retries",
        "cache_ttl": "jx3api_cache_ttl",
    },
    "jx3box": {
        "timeout": "jx3box_timeout",
        "cache_ttl": "jx3box_cache_ttl",
        "client": "jx3box_client",
        "global_level": "jx3box_global_level",
    },
    "online": {
        "api_url": "online_api_url",
        "token": "online_api_token",
    },
    "event_push": {
        "enabled": "event_push_enabled",
        "wss_url": "event_push_wss_url",
        "token": "event_push_token",
        "actions": "event_push_actions",
        "sessions": "event_push_sessions",
    },
    "paid": {
        "enabled": "paid_enabled",
    },
    "doubao": {
        "api_key": "doubao_api_key",
        "base_url": "doubao_base_url",
        "model": "doubao_model",
        "size": "doubao_size",
        "watermark": "doubao_watermark",
        "timeout": "doubao_timeout",
    },
    "admin": {
        "log_limit": "admin_log_limit",
        "default_server": "default_server",
    },
}

DEFAULT_COMMAND_OVERRIDES: dict[str, Any] = {
    "disabled": [],
    "cooldowns": {},
    "permissions": {},
}

_MISSING = object()
_URL_KEYS = {
    "jx3api_base_url",
    "doubao_base_url",
}
_URL_LABELS = {
    "jx3api_base_url": "JX3API 地址",
    "doubao_base_url": "豆包 API 地址",
}
_SECRET_PLACEHOLDER = re.compile(r"^\*{4,}")
_DOUBAO_SIZE_RE = re.compile(
    r"^(?:(?:1|2|3|4)K|\d{3,4}x\d{3,4})$", re.IGNORECASE
)


class SettingsError(ValueError):
    """A configuration value is invalid and should be shown to the admin."""


def _as_int(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int,
    label: str,
) -> int:
    if isinstance(value, bool):
        raise SettingsError(f"{label}必须是整数")
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise SettingsError(f"{label}必须是整数") from exc
    if parsed < minimum or parsed > maximum:
        raise SettingsError(f"{label}必须在 {minimum} 到 {maximum} 之间")
    return parsed


def _as_bool(value: Any, *, label: str, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on", "是", "开"}:
            return True
        if lowered in {"0", "false", "no", "off", "否", "关"}:
            return False
    if value is None:
        return default
    raise SettingsError(f"{label}必须是布尔值")


def normalize_token(value: Any) -> str:
    """Normalise a copied JX3API / third-party token.

    Accepts raw tokens as well as ``Bearer xxx``, ``token=xxx`` and
    ``Authorization: Bearer xxx`` fragments.  Tokens are opaque: never strip
    characters beyond the known wrappers.
    """

    text = str(value or "").strip().strip("\"'")
    lowered = text.lower()
    for prefix in (
        "authorization: bearer ",
        "authorization:",
        "bearer ",
        "token=",
        "token: ",
    ):
        if lowered.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    if text.lower().startswith("token="):
        text = text[len("token=") :].split("&", 1)[0].strip()
    return text


def _clean_optional_url(value: Any, *, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    parsed = urllib.parse.urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SettingsError(f"{label}必须是域名或 http(s) 完整地址")
    if parsed.fragment:
        raise SettingsError(f"{label}不能包含 fragment")
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), parsed.query, "")
    )


def _clean_ws_url(value: Any, *, label: str) -> str:
    text = str(value or "").strip() or DEFAULT_WSS_URL
    if "://" not in text:
        text = "wss://" + text
    parsed = urllib.parse.urlsplit(text)
    if parsed.scheme not in {"ws", "wss"} or not parsed.netloc:
        raise SettingsError(f"{label}必须是 ws:// 或 wss:// 地址")
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")
    )


def _clean_text_list(value: Any, *, label: str, max_items: int = 200) -> list[str]:
    if isinstance(value, str):
        raw_items = re.split(r"[\n,，;；]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raise SettingsError(f"{label}必须是列表")
    result: list[str] = []
    for item in raw_items:
        text = str(item or "").replace("\x00", "").strip()
        if not text:
            continue
        if len(text) > 512:
            raise SettingsError(f"{label}中的单项不能超过 512 个字符")
        if text not in result:
            result.append(text)
    if len(result) > max_items:
        raise SettingsError(f"{label}最多 {max_items} 项")
    return result


def _clean_actions(value: Any, *, label: str) -> list[int]:
    if isinstance(value, str):
        raw_items: list[Any] = re.split(r"[\s,，;；]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raise SettingsError(f"{label}必须是列表")
    result: list[int] = []
    for item in raw_items:
        if isinstance(item, bool):
            raise SettingsError(f"{label}包含无效事件编号")
        try:
            action = int(item)
        except (TypeError, ValueError) as exc:
            raise SettingsError(f"{label}包含无效事件编号") from exc
        if action not in EVENT_NAMES:
            raise SettingsError(f"{label}包含未知事件编号 {action}")
        if action not in result:
            result.append(action)
    return sorted(result)


def _clean_size(value: Any, *, label: str) -> str:
    text = str(value or "").strip().upper().replace("×", "x")
    if not text:
        return DEFAULT_DOUBAO_SIZE
    if not _DOUBAO_SIZE_RE.match(text):
        raise SettingsError(f"{label}格式应为 1024x1024 或 2K")
    if "X" in text:
        width_text, height_text = text.lower().split("x", 1)
        try:
            width, height = int(width_text), int(height_text)
        except ValueError as exc:
            raise SettingsError(f"{label}格式不正确") from exc
        if not (512 <= width <= 4096 and 512 <= height <= 4096):
            raise SettingsError(f"{label}的宽高必须在 512 到 4096 之间")
        if width % 2 or height % 2:
            raise SettingsError(f"{label}的宽高必须是偶数")
        return f"{width}x{height}"
    return text


def _clean_url(value: Any, *, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise SettingsError(f"{label}不能为空")
    parsed = urllib.parse.urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SettingsError(f"{label}必须是 http:// 或 https:// 开头的完整地址")
    if parsed.query or parsed.fragment:
        raise SettingsError(f"{label}不能包含 query 或 fragment")
    path = parsed.path.rstrip("/")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _clean_text(value: Any, *, label: str, max_length: int, allow_empty: bool = False) -> str:
    text = str(value or "").replace("\x00", "").strip()
    if not allow_empty and not text:
        raise SettingsError(f"{label}不能为空")
    if len(text) > max_length:
        raise SettingsError(f"{label}不能超过 {max_length} 个字符")
    return text


def mask_secret(value: Any, *, keep: int = 4) -> str:
    """Return a display-only masked secret (never the raw value)."""

    text = str(value or "")
    if not text:
        return ""
    if len(text) <= keep:
        return "****"
    return "****" + text[-keep:]


class Settings:
    """Validated access to plugin configuration and runtime command switches."""

    @property
    def weibo_configured(self):
        return (self.data_dir / 'weibo-auth.json').is_file()

    def __init__(
        self,
        config: Any,
        data_dir: str | Path,
        save_callback: Callable[[], Any] | None = None,
    ) -> None:
        self._config = config if config is not None else {}
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._save_callback = save_callback
        self._commands_path = self.data_dir / "commands.json"
        self._overrides = self._load_overrides()

    # ------------------------------------------------------------------ read
    def get(self, key: str) -> Any:
        default = DEFAULTS.get(key)
        try:
            value = self._config.get(key, _MISSING)
        except Exception:  # pragma: no cover - exotic mapping implementations
            value = _MISSING
        if value is _MISSING:
            return copy.deepcopy(default)
        return value

    def get_int(self, key: str, *, minimum: int = 0, maximum: int = 10**9) -> int:
        default = int(DEFAULTS.get(key, 0))
        try:
            value = int(str(self.get(key)).strip())
        except (TypeError, ValueError):
            return default
        return max(minimum, min(maximum, value))

    def get_bool(self, key: str) -> bool:
        try:
            return _as_bool(self.get(key), label=key, default=bool(DEFAULTS.get(key)))
        except SettingsError:
            return bool(DEFAULTS.get(key))

    def get_list(self, key: str) -> list[str]:
        value = self.get(key)
        if isinstance(value, str):
            return [item.strip() for item in re.split(r"[\n,，;；]+", value) if item.strip()]
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    @property
    def token(self) -> str:
        return normalize_token(self.get("jx3api_token") or "")

    @property
    def ticket(self) -> str:
        # Users often paste a whole Cookie header or "ticket=..." fragment
        # into the AstrBot config page; normalise it at read time as well.
        return normalize_ticket(self.get("jx3api_ticket") or "")

    @property
    def jx3api_base(self) -> str:
        return str(self.get("jx3api_base_url") or DEFAULT_JX3API_BASE).rstrip("/")

    @property
    def jx3box_cms(self) -> str:
        return JX3BOX_CMS_BASE

    @property
    def jx3box_node(self) -> str:
        return JX3BOX_NODE_BASE

    @property
    def jx3box_auction(self) -> str:
        return JX3BOX_AUCTION_BASE

    @property
    def default_server(self) -> str:
        return str(self.get("default_server") or "").strip()

    @property
    def online_api_url(self) -> str:
        return str(self.get("online_api_url") or "").strip()

    @property
    def online_api_token(self) -> str:
        return normalize_token(self.get("online_api_token") or "")

    @property
    def event_push_enabled(self) -> bool:
        return self.get_bool("event_push_enabled")

    @property
    def event_push_wss_url(self) -> str:
        return str(self.get("event_push_wss_url") or DEFAULT_WSS_URL).strip()

    @property
    def event_push_token(self) -> str:
        return normalize_token(self.get("event_push_token") or "")

    @property
    def event_push_effective_token(self) -> str:
        """Event channel token; an empty override reuses the JX3API token."""

        return self.event_push_token or self.token

    @property
    def event_push_actions(self) -> list[int]:
        raw = self.get("event_push_actions")
        if not isinstance(raw, (list, tuple)):
            return sorted(FREE_EVENT_ACTIONS)
        result = []
        for item in raw:
            try:
                action = int(item)
            except (TypeError, ValueError):
                continue
            if action in EVENT_NAMES and action not in result:
                result.append(action)
        return sorted(result)

    @property
    def event_push_sessions(self) -> list[str]:
        return self.get_list("event_push_sessions")

    @property
    def paid_enabled(self) -> bool:
        return self.get_bool("paid_enabled")

    @property
    def doubao_api_key(self) -> str:
        return normalize_token(self.get("doubao_api_key") or "")

    @property
    def doubao_base(self) -> str:
        return str(self.get("doubao_base_url") or DEFAULT_DOUBAO_BASE).rstrip("/")

    @property
    def doubao_model(self) -> str:
        return str(self.get("doubao_model") or DEFAULT_DOUBAO_MODEL).strip()

    @property
    def doubao_size(self) -> str:
        return str(self.get("doubao_size") or DEFAULT_DOUBAO_SIZE).strip()

    @property
    def doubao_watermark(self) -> bool:
        return self.get_bool("doubao_watermark")

    @property
    def doubao_timeout(self) -> int:
        return self.get_int("doubao_timeout", minimum=10, maximum=300)

    def public(self) -> dict[str, Any]:
        """A JSON-safe snapshot with secrets replaced by a masked value."""

        token = self.token
        ticket = self.ticket
        online_token = self.online_api_token
        event_token = self.event_push_token
        effective_event_token = self.event_push_effective_token
        doubao_key = self.doubao_api_key
        return {
            "jx3api": {
                "base_url": self.jx3api_base,
                "timeout": self.get_int("jx3api_timeout", minimum=3, maximum=180),
                "retries": self.get_int("jx3api_retries", minimum=0, maximum=5),
                "cache_ttl": self.get_int("jx3api_cache_ttl", minimum=0, maximum=86400),
                "token_configured": bool(token),
                "token_masked": mask_secret(token),
                "token_length": len(token),
                "ticket_configured": bool(ticket),
                "ticket_masked": mask_secret(ticket),
                "ticket_length": len(ticket),
            },
            "jx3box": {
                "cms_base": self.jx3box_cms,
                "node_base": self.jx3box_node,
                "auction_base": self.jx3box_auction,
                "timeout": self.get_int("jx3box_timeout", minimum=3, maximum=180),
                "cache_ttl": self.get_int("jx3box_cache_ttl", minimum=0, maximum=86400),
                "client": str(self.get("jx3box_client") or "std"),
                "global_level": self.get_int(
                    "jx3box_global_level", minimum=1, maximum=999
                ),
            },
            "online": {
                "api_url": self.online_api_url,
                "token_configured": bool(online_token),
                "token_masked": mask_secret(online_token),
                "token_length": len(online_token),
            },
            "event_push": {
                "enabled": self.event_push_enabled,
                "wss_url": self.event_push_wss_url,
                "token_configured": bool(event_token),
                "token_masked": mask_secret(event_token),
                "token_fallback": not event_token and bool(token),
                "effective_token_masked": mask_secret(effective_event_token),
                "actions": self.event_push_actions,
                "sessions": self.event_push_sessions,
            },
            "paid": {
                "enabled": self.paid_enabled,
            },
            "doubao": {
                "enabled": bool(doubao_key),
                "base_url": self.doubao_base,
                "model": self.doubao_model,
                "size": self.doubao_size,
                "watermark": self.doubao_watermark,
                "timeout": self.doubao_timeout,
                "key_configured": bool(doubao_key),
                "key_masked": mask_secret(doubao_key),
                "key_length": len(doubao_key),
            },
            "admin": {
                "log_limit": self.get_int("admin_log_limit", minimum=50, maximum=1000),
                "default_server": self.default_server,
            },
        }

    # ----------------------------------------------------------------- write
    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate and persist a dashboard payload.

        Secrets are only written when a new non-masked value is supplied.  An
        empty string means "leave unchanged"; clearing is an explicit action
        through :meth:`clear_secret`.
        """

        if not isinstance(payload, dict):
            raise SettingsError("请求体必须是 JSON 对象")

        updates: dict[str, Any] = {}
        for group, fields in GROUPS.items():
            block = payload.get(group)
            if block is None:
                continue
            if not isinstance(block, dict):
                raise SettingsError(f"{group} 配置必须是对象")
            for field, flat_key in fields.items():
                if field not in block:
                    continue
                raw = block[field]
                if flat_key in SECRET_KEYS:
                    text = str(raw or "").strip()
                    if not text or _SECRET_PLACEHOLDER.match(text):
                        continue
                    text = (
                        normalize_ticket(text)
                        if flat_key == "jx3api_ticket"
                        else normalize_token(text)
                    )
                    if len(text) > 4096:
                        raise SettingsError(f"{SECRET_LABELS[flat_key]}过长")
                    updates[flat_key] = text
                    continue
                updates[flat_key] = self._validate_value(flat_key, raw)

        # Also accept flat keys, useful for scripts and tests.
        for flat_key in DEFAULTS:
            if flat_key in payload and flat_key not in updates:
                raw = payload[flat_key]
                if flat_key in SECRET_KEYS:
                    text = str(raw or "").strip()
                    if not text or _SECRET_PLACEHOLDER.match(text):
                        continue
                    text = (
                        normalize_ticket(text)
                        if flat_key == "jx3api_ticket"
                        else normalize_token(text)
                    )
                    updates[flat_key] = text
                else:
                    updates[flat_key] = self._validate_value(flat_key, raw)

        previous = {key: (key in self._config, self._config.get(key)) for key in updates}
        changed: list[str] = []
        for key, value in updates.items():
            if self.get(key) != value:
                try:
                    self._config[key] = value
                except Exception as exc:  # pragma: no cover - exotic config
                    raise SettingsError(f"无法写入配置项 {key}") from exc
                changed.append(key)

        if changed:
            try:
                self._persist_config()
            except SettingsError:
                for key, (existed, value) in previous.items():
                    if existed:
                        self._config[key] = value
                    else:
                        self._config.pop(key, None)
                raise
        return {
            "changed": changed,
            "message": "配置已保存" if changed else "没有检测到修改",
            "settings": self.public(),
        }

    def clear_secret(self, field: str) -> dict[str, Any]:
        if field not in SECRET_KEYS:
            raise SettingsError("未知的密钥字段")
        if self.get(field):
            previous = self._config.get(field)
            try:
                self._config[field] = ""
            except Exception as exc:  # pragma: no cover
                raise SettingsError("无法写入配置") from exc
            try:
                self._persist_config()
            except SettingsError:
                self._config[field] = previous
                raise
        return {
            "message": f"{SECRET_LABELS[field]} 已清除",
            "settings": self.public(),
        }

    def _validate_value(self, key: str, raw: Any) -> Any:
        if key in _URL_KEYS:
            return _clean_url(raw, label=_URL_LABELS.get(key, key))
        if key == "online_api_url":
            return _clean_optional_url(raw, label="在线查询服务地址")
        if key == "event_push_wss_url":
            return _clean_ws_url(raw, label="事件推送地址")
        if key == "event_push_actions":
            return _clean_actions(raw, label="事件推送订阅")
        if key == "event_push_sessions":
            return _clean_text_list(raw, label="事件推送目标会话")
        if key in {"event_push_enabled", "paid_enabled", "doubao_watermark"}:
            return _as_bool(raw, label=key)
        if key == "doubao_model":
            return _clean_text(raw, label="豆包模型", max_length=128)
        if key == "doubao_size":
            return _clean_size(raw, label="豆包图片尺寸")
        if key == "doubao_timeout":
            return _as_int(raw, default=180, minimum=10, maximum=300, label="豆包超时")
        if key == "default_server":
            return _clean_text(
                raw, label="默认区服", max_length=64, allow_empty=True
            )
        if key == "jx3box_client":
            text = _clean_text(raw, label="JX3BOX 客户端", max_length=16)
            if text not in {"std", "origin"}:
                raise SettingsError("JX3BOX 客户端只能是 std 或 origin")
            return text
        if key == "jx3api_timeout":
            return _as_int(raw, default=20, minimum=3, maximum=180, label="JX3API 超时")
        if key == "jx3box_timeout":
            return _as_int(raw, default=25, minimum=3, maximum=180, label="JX3BOX 超时")
        if key == "jx3api_retries":
            return _as_int(raw, default=1, minimum=0, maximum=5, label="重试次数")
        if key == "jx3api_cache_ttl":
            return _as_int(raw, default=60, minimum=0, maximum=86400, label="JX3API 缓存时间")
        if key == "jx3box_cache_ttl":
            return _as_int(raw, default=300, minimum=0, maximum=86400, label="JX3BOX 缓存时间")
        if key == "jx3box_global_level":
            return _as_int(raw, default=130, minimum=1, maximum=999, label="JX3BOX 装等")
        if key == "admin_log_limit":
            return _as_int(raw, default=300, minimum=50, maximum=1000, label="日志保留条数")
        return raw

    def _persist_config(self) -> None:
        if not self._save_callback:
            return
        try:
            result = self._save_callback()
        except Exception as exc:
            logger.warning("保存 AstrBot 配置失败: %s", exc)
            raise SettingsError("AstrBot 配置保存失败，请查看控制台日志") from exc
        if result is False:
            raise SettingsError("AstrBot 配置保存失败（save_config 返回 False）")

    # -------------------------------------------------------- command switches
    def _load_overrides(self) -> dict[str, Any]:
        data = copy.deepcopy(DEFAULT_COMMAND_OVERRIDES)
        try:
            raw = json.loads(self._commands_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return data
        except Exception as exc:
            logger.warning("读取指令配置失败，使用默认值: %s", exc)
            return data
        if not isinstance(raw, dict):
            return data
        disabled = raw.get("disabled")
        if isinstance(disabled, list):
            data["disabled"] = [
                str(item).strip() for item in disabled if str(item).strip()
            ]
        cooldowns = raw.get("cooldowns")
        if isinstance(cooldowns, dict):
            for key, value in cooldowns.items():
                try:
                    number = int(value)
                except (TypeError, ValueError):
                    continue
                data["cooldowns"][str(key)] = max(0, min(3600, number))
        permissions = raw.get("permissions")
        if isinstance(permissions, dict):
            for key, value in permissions.items():
                if value in {"all", "admin"}:
                    data["permissions"][str(key)] = value
        return data

    def command_overrides(self) -> dict[str, Any]:
        return copy.deepcopy(self._overrides)

    def migrate_command_keys(self):
        marker = self.data_dir / 'command-keys-v1.json'
        if marker.is_file(): return
        mapping = json.loads((Path(__file__).parent.parent / 'data/command_key_migrations.json').read_text())
        before = self.command_overrides()
        after = copy.deepcopy(before)
        for old, new in mapping.items():
            if old in before['disabled'] and new not in after['disabled']: after['disabled'].append(new)
            for field in ('cooldowns','permissions'):
                if old in before[field] and new not in after[field]: after[field][new] = before[field][old]
                if old != new: after[field].pop(old, None)
            if old != new and old in after['disabled']: after['disabled'].remove(old)
        if after != before: self.save_command_overrides(after)
        self._atomic_write_json(marker, {'version':1})

    def save_command_overrides(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise SettingsError("请求体必须是 JSON 对象")
        disabled = payload.get("disabled", [])
        cooldowns = payload.get("cooldowns", {})
        permissions = payload.get("permissions", {})
        if not isinstance(disabled, list):
            raise SettingsError("disabled 必须是列表")
        if not isinstance(cooldowns, dict):
            raise SettingsError("cooldowns 必须是对象")
        if not isinstance(permissions, dict):
            raise SettingsError("permissions 必须是对象")

        clean: dict[str, Any] = {
            "disabled": sorted({str(item).strip() for item in disabled if str(item).strip()}),
            "cooldowns": {},
            "permissions": {},
        }
        for key, value in cooldowns.items():
            if isinstance(value, bool):
                raise SettingsError("冷却时间必须是整数")
            try:
                number = int(value)
            except (TypeError, ValueError) as exc:
                raise SettingsError("冷却时间必须是整数") from exc
            if number < 0 or number > 3600:
                raise SettingsError("冷却时间必须在 0 到 3600 秒之间")
            clean["cooldowns"][str(key)] = number
        for key, value in permissions.items():
            if value not in {"all", "admin"}:
                raise SettingsError("权限只能是 all 或 admin")
            clean["permissions"][str(key)] = value

        self._atomic_write_json(self._commands_path, clean)
        self._overrides = clean
        return self.command_overrides()

    def reset_command_overrides(self) -> dict[str, Any]:
        clean = copy.deepcopy(DEFAULT_COMMAND_OVERRIDES)
        self._atomic_write_json(self._commands_path, clean)
        self._overrides = clean
        return self.command_overrides()

    _atomic_write_json = staticmethod(write_json)
