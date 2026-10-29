"""角色在线查询：JX3API 角色详情 + 第三方在线接口。

JX3API 本身没有“角色是否在线”接口；名片的 ``showActive`` 只表示名片是否在
展示，不是游戏在线。这里按参考插件的约定接入第三方在线服务：

    GET https://<host>/role_online
        ?zone=电信区&server=梦江南&name=张三
        &role_id=...&global_role_id=...&token=<第三方令牌>

响应约定：

    {"code": 0, "data": [{"gameLogin": true}]}

只接受明确的 ``gameLogin`` 布尔/0/1/"true"/"false" 证据，避免把“名片展示中”
误报成在线。
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from .http import HttpClient, HttpError, NetworkError
from .jx3api import JX3APIClient, describe_jx3_error
from .settings import Settings, mask_secret
from .telemetry import Telemetry


class OnlineError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def parse_online(payload: Any) -> bool | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("code", 0) not in (0, 200, "0", "200"):
        return None
    rows = payload.get("data")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        return None
    value = rows[0].get("gameLogin")
    if type(value) is bool:
        return value
    if type(value) is int and value in (0, 1):
        return value == 1
    if isinstance(value, str):
        return {"true": True, "false": False, "1": True, "0": False}.get(
            value.strip().lower()
        )
    return None


class OnlineService:
    def __init__(
        self,
        settings: Settings,
        api: JX3APIClient,
        http: HttpClient,
        telemetry: Telemetry | None = None,
    ) -> None:
        self.settings = settings
        self.api = api
        self.http = http
        self.telemetry = telemetry

    def summary(self) -> dict[str, Any]:
        token = self.settings.online_api_token
        return {
            "configured": bool(self.settings.online_api_url and token),
            "api_url": self.settings.online_api_url,
            "token_configured": bool(token),
            "token_masked": mask_secret(token),
        }

    @staticmethod
    def _endpoint(base: str) -> str:
        text = str(base or "").strip()
        if "://" not in text:
            text = "https://" + text
        parsed = urllib.parse.urlsplit(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise OnlineError("在线查询服务地址无效，请填写域名或完整接口地址")
        if parsed.path.strip("/"):
            return urllib.parse.urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")
            )
        return urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, "/role_online", parsed.query, "")
        )

    async def query(self, server: str, name: str) -> dict[str, Any]:
        name = str(name or "").strip()
        server = str(server or "").strip()
        if not name:
            raise OnlineError("请提供角色名，例如：在线 梦江南 张三")
        if not self.settings.online_api_url:
            raise OnlineError(
                "尚未配置角色在线查询地址。请在后台「接口配置 → 角色在线」填写第三方服务地址。"
            )
        if not self.settings.online_api_token:
            raise OnlineError(
                "尚未配置在线查询令牌。请在后台「接口配置 → 角色在线」填写第三方服务令牌。"
            )
        try:
            detail = await self.api.role_detail(server, name)
        except Exception as exc:
            raise OnlineError(f"查询角色信息失败：{describe_jx3_error(exc)}") from exc
        if not isinstance(detail, dict) or not detail.get("roleName"):
            raise OnlineError(f"没有找到角色「{name}」，请检查区服和角色名。")
        zone = str(detail.get("zoneName") or detail.get("zone") or "")
        server_name = str(detail.get("serverName") or detail.get("server") or server)
        params = {
            "zone": zone,
            "server": server_name,
            "name": str(detail.get("roleName") or name),
            "role_id": detail.get("roleId") or detail.get("role_id") or "",
            "global_role_id": detail.get("globalId") or detail.get("global_role_id") or "",
            "token": self.settings.online_api_token,
        }
        endpoint = self._endpoint(self.settings.online_api_url)
        try:
            result = await self.http.request_json(
                "GET",
                endpoint,
                params=params,
                timeout=15,
                retries=0,
                source="online",
                telemetry=self.telemetry,
            )
        except NetworkError as exc:
            raise OnlineError(f"在线服务连接失败：{exc.message}") from exc
        except HttpError as exc:
            raise OnlineError(f"在线服务返回 HTTP {exc.status or '错误'}") from exc
        online = parse_online(result.data)
        if online is None:
            raise OnlineError("在线服务没有返回可识别的在线状态（gameLogin 字段缺失）。")
        return {
            "online": online,
            "zone": zone,
            "server": server_name,
            "name": str(detail.get("roleName") or name),
            "role_id": params["role_id"],
            "endpoint": endpoint,
        }

    async def probe(self, server: str, name: str) -> dict[str, Any]:
        result = await self.query(server, name)
        return {
            "ok": True,
            "message": (
                f"[{result['server']}·{result['name']}] "
                f"当前{'在线' if result['online'] else '离线'}"
            ),
            "online": result["online"],
            "detail": result,
        }
