"""JX3API.COM client.

API reference: https://www.jx3api.com/openapi
The endpoint catalog in ``data/endpoints.json`` is generated from the official
OpenAPI document by ``tools/build_catalog.py``.

Authentication model
--------------------
* ``token`` is required for LV.1 / LV.2 endpoints.  LV.0 endpoints are free.
* ``ticket`` is the 推栏 login ticket and is required by the endpoints marked
  ``[需ticket]`` (arena, card presets, school data, 资历 ...).
* Both credentials are sent as query parameters, exactly as documented by
  JX3API.  Secrets never appear in logs or in the admin API.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from . import catalog
from .cache import TTLCache
from .http import HTTPStatusError, HttpClient, HttpError, NetworkError
from .settings import Settings
from .telemetry import Telemetry


class MissingCredential(Exception):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


class JX3APIError(Exception):
    def __init__(self, code: int | str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


def describe_jx3_error(error: BaseException) -> str:
    if isinstance(error, MissingCredential):
        return error.message
    if isinstance(error, JX3APIError):
        try:
            code = int(error.code)
        except (TypeError, ValueError):
            code = 0
        message = str(error.message or "")
        lowered = message.lower()
        if code == 401:
            return "JX3API Token 无效或未填写，请在后台「接口配置」中检查。"
        if code == 403:
            if "ticket" in lowered or "推栏" in message:
                return (
                    "推栏 Ticket 无效或已过期，请在后台重新填写。"
                    "（Ticket 与 JX3API Token 是两种不同的凭证）"
                )
            if "level" in lowered or "等级" in message or "lv" in lowered:
                return f"当前 Token 等级不足，无法调用该接口。（JX3API：{message}）"
            return (
                "没有该接口权限：可能是 Token 等级不足，或推栏 Ticket 已失效。"
                f"（JX3API：{message}）"
            )
        if code == 404:
            return "JX3API 接口不存在或已下线，请更新插件。"
        if code == 429:
            return "请求过于频繁，请稍后再试或调大后台的缓存时间。"
        if code == 400:
            return f"参数不正确：{message}"
        if code >= 500:
            return f"JX3API 服务端错误（{code}），请稍后再试。"
        return f"JX3API 返回错误（{code}）：{message}"
    if isinstance(error, HTTPStatusError):
        if error.status == 401:
            return "JX3API 鉴权失败（HTTP 401），请检查 Token。"
        if error.status == 403:
            return "JX3API 拒绝访问（HTTP 403），请检查 Token 等级或推栏 Ticket。"
        if error.status == 429:
            return "请求过于频繁（HTTP 429），请稍后再试。"
        return f"JX3API 返回 HTTP {error.status}，请稍后再试。"
    if isinstance(error, NetworkError):
        return error.message
    if isinstance(error, HttpError):
        return error.message
    return "查询失败，请稍后再试。"


class JX3APIClient:
    def __init__(
        self,
        settings: Settings,
        http: HttpClient,
        cache: TTLCache,
        telemetry: Telemetry,
    ) -> None:
        self.settings = settings
        self.http = http
        self.cache = cache
        self.telemetry = telemetry
        self._token_stats_cache: tuple[float, dict[str, Any]] | None = None

    # ------------------------------------------------------------------ helpers
    @property
    def base(self) -> str:
        return self.settings.jx3api_base

    def _fingerprint(self) -> str:
        raw = f"{self.settings.token}|{self.settings.ticket}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    def _cache_key(self, path: str, params: dict[str, Any]) -> str:
        parts = [self.base, path, self._fingerprint()]
        for key in sorted(params):
            parts.append(f"{key}={params[key]}")
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    def _ttl(self) -> int:
        """Configured cache TTL; 0 really disables caching for every method."""

        return self.settings.get_int("jx3api_cache_ttl", minimum=0, maximum=86400)

    @staticmethod
    def _clean_params(params: dict[str, Any] | None) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        for key, value in (params or {}).items():
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            clean[str(key)] = value
        return clean

    # ----------------------------------------------------------------- request
    async def request(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        auth: str = "auto",
        use_cache: bool = True,
        ttl: int | None = None,
        source: str = "jx3api",
    ) -> Any:
        path = "/" + str(path or "").lstrip("/")
        entry = catalog.get_endpoint(path) or {}
        level = int(entry.get("level") or 0)
        ticket_required = bool(entry.get("ticket"))

        want_token = auth in {"token", "both"}
        want_ticket = auth in {"ticket", "both"}
        if auth == "auto":
            want_token = level > 0 or ticket_required
            want_ticket = ticket_required

        if want_token and not self.settings.token:
            raise MissingCredential(
                "token",
                "该功能需要 JX3API Token。请在后台「接口配置」中填写 Token 后重试。",
            )
        if want_ticket and not self.settings.ticket:
            raise MissingCredential(
                "ticket",
                "该功能需要推栏 Ticket。请在后台「接口配置 → 推栏 Ticket」中填写后重试。",
            )

        query = self._clean_params(params)
        if want_token:
            query["token"] = self.settings.token
        if want_ticket:
            query["ticket"] = self.settings.ticket

        cache_ttl = (
            self.settings.get_int("jx3api_cache_ttl", minimum=0, maximum=86400)
            if ttl is None
            else max(0, int(ttl))
        )
        cache_key = self._cache_key(path, query)
        async def fetch():
            result = await self.http.request_json(
                "GET", f"{self.base}{path}", params=query,
                timeout=self.settings.get_int("jx3api_timeout", minimum=3, maximum=180),
                retries=self.settings.get_int("jx3api_retries", minimum=0, maximum=5),
                source=source, telemetry=self.telemetry,
            )
            return self._parse_payload(result.data)
        if not use_cache:
            if path in {'/card/record', '/card/records', '/card/cached'}:
                return await self.cache.get_or_load("jx3api-fresh", cache_key, 0, fetch, share_inflight=True)
            return await fetch()
        return await self.cache.get_or_load("jx3api", cache_key, cache_ttl, fetch)

    @staticmethod
    def _parse_payload(payload: Any) -> Any:
        if not isinstance(payload, dict):
            raise JX3APIError(0, "JX3API 返回格式异常（不是 JSON 对象）")
        if "code" not in payload:
            return payload.get("data", payload)
        raw_code = payload.get("code", 0)
        try:
            code = int(raw_code)
        except (TypeError, ValueError):
            code = 0
        if code != 200:
            raise JX3APIError(code, str(payload.get("msg") or "未知错误"))
        return payload.get("data")

    # --------------------------------------------------------------- API calls
    async def calendar(self, num: int = 0, mode: str = "day") -> Any:
        return await self.request(
            "/active/calendar",
            {"num": max(0, min(15, int(num))), "mode": mode},
            auth="none",
            ttl=self._ttl(),
        )

    async def server_status(self, server: str = "") -> Any:
        return await self.request(
            "/server/status/check",
            {"server": server, "type": 1},
            auth="none",
            ttl=self._ttl(),
        )

    async def gold(self, server: str = "", limit: int = 10) -> Any:
        return await self.request(
            "/trade/demon",
            {"server": server, "limit": max(1, min(100, int(limit)))},
        )

    async def sand(self, server: str) -> Any:
        return await self.request("/sand/records", {"server": server})

    async def role_detail(self, server: str, name: str, history: int = 0) -> Any:
        return await self.request(
            "/role/detail",
            {"server": server, "name": name, "history": 1 if history else 0},
        )

    async def event_records(self, server: str, name: str, full: int = 0) -> Any:
        return await self.request(
            "/event/records",
            {"server": server, "name": name, "full": 1 if full else 0},
        )

    async def event_strategy(self, name: str) -> Any:
        return await self.request("/event/strategy", {"name": name})

    async def exam(self, subject: str, limit: int = 8) -> Any:
        return await self.request(
            "/exam/search",
            {"subject": subject, "limit": max(1, min(20, int(limit)))},
            auth="none",
            ttl=self._ttl(),
        )

    async def trade_records(self, name: str, server: str = "") -> Any:
        params: dict[str, Any] = {"name": name}
        if str(server or "").strip():
            params["server"] = server
        return await self.request("/trade/records", params)

    async def tuilan_achievement(
        self, server: str, name: str, cls: int = 1
    ) -> Any:
        return await self.request(
            "/tuilan/achievement",
            {"server": server, "name": name, "class": max(1, min(3, int(cls)))},
            ttl=min(120, self._ttl()),
        )

    async def news(self, limit: int = 8) -> Any:
        return await self.request(
            "/news/records",
            {"limit": max(1, min(50, int(limit)))},
            auth="none",
            ttl=self._ttl(),
        )

    async def announce(self, limit: int = 8) -> Any:
        return await self.request(
            "/news/announce",
            {"limit": max(1, min(50, int(limit)))},
            auth="none",
            ttl=self._ttl(),
        )

    async def skill_rework(self) -> Any:
        return await self.request("/skill/rework", auth="none", ttl=self._ttl())

    async def school_matrix(self, name: str) -> Any:
        return await self.request("/school/matrix", {"name": name})

    # --------------------------------------------------------------- token/app
    async def token_stats(self, *, force: bool = False) -> dict[str, Any]:
        token = self.settings.token
        if not token:
            raise MissingCredential("token", "尚未配置 JX3API Token。")
        if (
            not force
            and self._token_stats_cache is not None
            and time.monotonic() - self._token_stats_cache[0] < 60
        ):
            return dict(self._token_stats_cache[1])
        try:
            # JX3API's official SDK sends this endpoint form-encoded; use that
            # first so a valid token is not reported as broken by a JSON probe.
            result = await self.http.request_json(
                "POST",
                f"{self.base}/token/stats",
                form_body={"token": token},
                timeout=15,
                retries=0,
                source="jx3api-token",
                telemetry=self.telemetry,
            )
        except HTTPStatusError as exc:
            # Some deployments/proxies only accept JSON on the stats endpoint.
            if exc.status not in {400, 404, 405, 415, 422}:
                raise
            result = await self.http.request_json(
                "POST",
                f"{self.base}/token/stats",
                json_body={"token": token},
                timeout=15,
                retries=0,
                source="jx3api-token",
                telemetry=self.telemetry,
            )
        data = self._parse_payload(result.data)
        if not isinstance(data, dict):
            raise JX3APIError(0, "Token 用量返回格式异常")
        normalized: dict[str, Any] = {"raw": data}
        for key in ("level", "used", "remaining", "valid"):
            if key in data:
                normalized[key] = data[key]
        self._token_stats_cache = (time.monotonic(), normalized)
        return dict(normalized)

    def invalidate_token_stats(self) -> None:
        self._token_stats_cache = None

    async def probe_connect(self) -> dict[str, Any]:
        started = time.monotonic()
        data = await self.request(
            "/active/calendar", {"num": 0, "mode": "day"}, auth="none", use_cache=False
        )
        date = data.get("date") if isinstance(data, dict) else ""
        return {
            "ok": True,
            "message": f"JX3API 连接正常{f'（{date}）' if date else ''}",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }

    async def probe_token(self) -> dict[str, Any]:
        started = time.monotonic()
        try:
            stats = await self.token_stats(force=True)
            if stats.get("valid") is False:
                raise JX3APIError(401, "Token 已失效")
            level = stats.get("level")
            suffix = f"（LV.{level}）" if level is not None else ""
            return {
                "ok": True,
                "message": f"Token 有效{suffix}",
                "level": level,
                "stats": stats,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }
        except Exception:
            pass

        # Fallback for deployments without /token/stats: a real LV.1 request.
        try:
            await self.request(
                "/trade/demon",
                {"limit": 1},
                auth="token",
                use_cache=False,
            )
        except Exception as fallback_error:
            # Prefer the fallback error: /token/stats may be missing on a
            # deployment while /trade/demon gives the real auth/level reason.
            raise fallback_error
        return {
            "ok": True,
            "message": "Token 有效（已通过 LV.1 接口验证）",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }

    async def probe_ticket(self) -> dict[str, Any]:
        started = time.monotonic()
        # A token failure should not be reported as a ticket failure.
        await self.probe_token()
        await self.request(
            "/school/matrix",
            {"name": "万花"},
            auth="both",
            use_cache=False,
        )
        return {
            "ok": True,
            "message": "Token 与推栏 Ticket 均有效",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
