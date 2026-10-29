"""JX3BOX (魔盒) client: 配装、一键宏、交易行.

JX3BOX has no official public API key; the endpoints below are the ones used by
the website itself and are stable enough for read-only queries:

======================  =============================================  ==========================
功能                    接口                                            说明
======================  =============================================  ==========================
配装列表                ``GET cms/api/cms/app/pz``                      mount = 心法 pzid
宏/攻略                 ``GET cms/api/cms/posts?subtype=心法``           post_type=macro 携带宏
物品库                  ``GET cms/api/cms/pvx/item/group``              按职业/材料分组
交易行成交价            ``POST next2/api/auction/``                     item_ids + server
======================  =============================================  ==========================

All responses are ``{"code": 0, "msg": "Success", "data": ...}``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from . import assets
from .cache import TTLCache
from .http import HttpClient, HttpError
from .settings import Settings
from .telemetry import Telemetry


class JX3BOXError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class JX3BOXClient:
    def __init__(
        self,
        settings: Settings,
        http: HttpClient,
        cache: TTLCache,
        telemetry: Telemetry,
        base_urls: dict[str, str] | None = None,
    ) -> None:
        self.settings = settings
        self.http = http
        self.cache = cache
        self.telemetry = telemetry
        # JX3BOX 地址固定在代码里；base_urls 仅用于测试注入本地 mock。
        self._base_urls = base_urls or {
            "cms": settings.jx3box_cms,
            "node": settings.jx3box_node,
            "auction": settings.jx3box_auction,
        }

    def _base(self, key: str) -> str:
        if key in self._base_urls:
            return self._base_urls[key]
        raise JX3BOXError(f"未知的 JX3BOX 服务：{key}")

    async def _request(
        self,
        base_key: str,
        path: str,
        *,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        ttl: int = 300,
        namespace: str = "jx3box:api",
    ) -> Any:
        method = method.upper()
        url = f"{self._base(base_key)}{path}"
        clean = {
            str(key): value
            for key, value in (params or {}).items()
            if value is not None and value != ""
        }
        cache_key = hashlib.sha256(
            json.dumps(
                [url, method, sorted(clean.items()), json_body],
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        async def fetch():
            try:
                result = await self.http.request_json(
                    method,
                    url,
                    params=clean if method == "GET" else None,
                    json_body=json_body if method != "GET" else None,
                    timeout=self.settings.get_int(
                        "jx3box_timeout", minimum=3, maximum=180
                    ),
                    retries=1,
                    source="jx3box",
                    telemetry=self.telemetry,
                )
            except HttpError as exc:
                raise JX3BOXError(_describe_box_http_error(exc)) from exc
    
            payload = result.data
            if isinstance(payload, dict):
                if "statusCode" in payload and int(payload.get("statusCode") or 0) >= 400:
                    raise JX3BOXError(
                        f"JX3BOX 请求失败：{payload.get('message') or payload.get('statusCode')}"
                    )
                if "code" in payload:
                    try:
                        code = int(payload.get("code"))
                    except (TypeError, ValueError):
                        code = 0
                    if code != 0:
                        raise JX3BOXError(
                            f"JX3BOX 返回错误：{payload.get('msg') or code}"
                        )
                    data = payload.get("data")
                else:
                    data = payload
            else:
                data = payload
            return data
        ttl = min(ttl, self.settings.get_int("jx3box_cache_ttl", minimum=0, maximum=86400))
        return await self.cache.get_or_load(namespace, cache_key, ttl, fetch)

    # ------------------------------------------------------------------ 配装
    async def builds(
        self, kungfu: str, tags: str = "", limit: int = 6
    ) -> dict[str, Any]:
        entry = assets.find_kungfu(kungfu)
        if entry is None:
            raise JX3BOXError(
                "未找到该心法，请发送「心法」查看支持的心法名称。"
            )
        params: dict[str, Any] = {
            "per": max(1, min(20, int(limit))),
            "page": 1,
            "client": str(self.settings.get("jx3box_client") or "std"),
            "global_level": self.settings.get_int(
                "jx3box_global_level", minimum=1, maximum=999
            ),
            "mount": entry["pzid"],
            "star": 1,
        }
        if tags:
            params["tags"] = tags
        data = await self._request(
            "cms",
            "/api/cms/app/pz",
            params=params,
            ttl=self.settings.get_int("jx3box_cache_ttl", minimum=0, maximum=86400),
            namespace="jx3box:builds",
        )
        if not isinstance(data, dict):
            raise JX3BOXError("配装数据格式异常")
        rows = data.get("list")
        if not isinstance(rows, list):
            raise JX3BOXError("配装数据缺少列表")
        items: list[dict[str, Any]] = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            author = row.get("pz_author_info")
            author_name = (
                str(author.get("display_name") or "")
                if isinstance(author, dict)
                else str(row.get("author") or "")
            )
            items.append(
                {
                    "id": row.get("id"),
                    "title": str(row.get("title") or "未命名配装"),
                    "author": author_name,
                    "tags": [str(tag) for tag in row.get("tags") or []],
                    "level": row.get("global_level"),
                    "season": str(row.get("zlp") or ""),
                    "updated": str(row.get("updated_at") or ""),
                    "url": f"https://www.jx3box.com/pz/{row.get('id')}",
                }
            )
        return {
            "kungfu": entry["name"],
            "total": int(data.get("total") or len(items)),
            "items": items,
        }

    # -------------------------------------------------------------------- 宏
    async def macros(self, kungfu: str) -> dict[str, Any]:
        entry = assets.find_kungfu(kungfu)
        if entry is None:
            raise JX3BOXError(
                "未找到该心法，请发送「心法」查看支持的心法名称。"
            )
        tops = await self._request("auction", "/api/macro/tops", params={"kungfu": entry["name"], "size": 3, "client": self.settings.get("jx3box_client")}, namespace="jx3box:macro")
        candidates = [row for row in tops if isinstance(row, dict) and row.get("pid")] if isinstance(tops, list) else []
        if not candidates:
            raise JX3BOXError("没有找到该心法的一键宏。")
        post = await self._request("cms", f"/api/cms/post/{int(candidates[0]['pid'])}", namespace="jx3box:macro")
        if not isinstance(post, dict):
            raise JX3BOXError("宏数据格式异常")
        blocks = (post.get("post_meta") or {}).get("data") or []
        macros: list[dict[str, str]] = []
        for block in blocks[:3]:
            if not isinstance(block, dict):
                continue
            code = str(block.get("macro") or "").strip()
            if not code:
                continue
            macros.append(
                {
                    "name": str(block.get("name") or "宏"),
                    "desc": str(block.get("desc") or "").strip(),
                    "macro": code,
                }
            )
        if not macros:
            raise JX3BOXError("该一键宏没有正文数据。")
        return {
            "kungfu": entry["name"],
            "title": str(post.get("post_title") or f"{entry['name']} 一键宏"),
            "author": str(post.get("author") or "未知"),
            "id": post.get("ID"),
            "url": f"https://www.jx3box.com/macro/{post.get('ID')}",
            "macros": macros,
        }

    async def guide(self, name: str) -> dict[str, Any]:
        found = await self._request("node", "/serendipities", params={"name": name}, ttl=3600, namespace="jx3box:guide")
        rows = found.get("list", []) if isinstance(found, dict) else found if isinstance(found, list) else []
        if not rows:
            raise JX3BOXError("未找到这个奇遇，请检查名称。")
        row = next((item for item in rows if item.get("szName") == name or item.get("name") == name), rows[0])
        identity = row.get("dwID")
        if identity is None:
            raise JX3BOXError("奇遇攻略暂时不可用。")
        achievement = await self._request("node", f"/serendipity/{int(identity)}/achievement", ttl=3600, namespace="jx3box:guide")
        source = achievement.get("achievement_id") if isinstance(achievement, dict) else None
        if source is None:
            raise JX3BOXError("这个奇遇暂时没有攻略。")
        article = await self._request("cms", f"/api/cms/wiki/post/type/achievement/source/{int(source)}", ttl=3600, namespace="jx3box:guide")
        content = (article.get("post") or {}).get("content") if isinstance(article, dict) else ""
        if not content:
            raise JX3BOXError("这个奇遇暂时没有攻略。")
        return {"title": name, "content": content, "source": "魔盒奇遇攻略", "date": "", "url": f"https://www.jx3box.com/serendipity/{int(identity)}"}

    # ----------------------------------------------------------------- 交易行
    async def _item_groups(self) -> list[dict[str, Any]]:
        data = await self._request(
            "cms",
            "/api/cms/pvx/item/group",
            params={"client": str(self.settings.get("jx3box_client") or "std")},
            ttl=86400,
            namespace="jx3box:items",
        )
        if not isinstance(data, list):
            raise JX3BOXError("交易行物品库格式异常")
        groups = [item for item in data if isinstance(item, dict)]
        return groups

    async def item_search(self, name: str, limit: int = 20) -> list[dict[str, Any]]:
        query = str(name or "").strip()
        if not query:
            raise JX3BOXError("请输入物品名称。")
        groups = await self._item_groups()
        lowered = query.lower()
        ranked: list[tuple[int, int, dict[str, Any], dict[str, Any]]] = []
        seen: set[str] = set()
        for group in groups:
            for item in group.get("items") or []:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or "")
                item_id = str(item.get("item_id") or "")
                if not label or not item_id or item_id in seen:
                    continue
                haystack = label.lower()
                if lowered == haystack:
                    rank = 0
                elif haystack.startswith(lowered):
                    rank = 1
                elif lowered in haystack:
                    rank = 2
                else:
                    continue
                seen.add(item_id)
                ranked.append(
                    (
                        rank,
                        len(label),
                        {
                            "item_id": item_id,
                            "label": label,
                            "icon": str(item.get("icon") or ""),
                        },
                        group,
                    )
                )
        ranked.sort(key=lambda row: (row[0], row[1], row[2]["label"]))
        return [
            {**row[2], "group": str(row[3].get("label") or "")}
            for row in ranked[: max(1, min(50, int(limit)))]
        ]

    async def auction(self, name: str, server: str) -> list[dict[str, Any]]:
        if not server:
            raise JX3BOXError("交易行查询需要区服名称。")
        matches = await self.item_search(name, limit=12)
        if not matches:
            raise JX3BOXError("未找到匹配的交易行物品，请换一个关键词。")
        # Keep the request small; JX3BOX accepts a list of item ids.
        selected = matches[:6]
        data = await self._request(
            "auction",
            "/api/auction/",
            method="POST",
            json_body={
                "item_ids": [item["item_id"] for item in selected],
                "server": server,
                "aggregate_type": "hourly",
            },
            ttl=60,
            namespace="jx3box:auction",
        )
        rows = data if isinstance(data, list) else []
        labels = {item["item_id"]: item for item in selected}
        result: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            item_id = str(row.get("item_id") or "")
            base = labels.get(item_id)
            if not base:
                continue
            try:
                price = int(row.get("price") or 0)
            except (TypeError, ValueError):
                price = 0
            try:
                sample = int(row.get("sample") or 0)
            except (TypeError, ValueError):
                sample = 0
            result.append(
                {
                    "item_id": item_id,
                    "name": base["label"],
                    "server": str(row.get("server") or server),
                    "price": max(0, price),
                    "sample": max(0, sample),
                }
            )
        if not result:
            raise JX3BOXError("交易行暂时没有该物品的成交记录。")
        result.sort(key=lambda item: (item["price"], item["name"]))
        return result

    # ------------------------------------------------------------------ 探活
    async def probe(self) -> dict[str, Any]:
        data = await self._request(
            "cms",
            "/api/cms/app/pz",
            params={
                "per": 1,
                "page": 1,
                "client": str(self.settings.get("jx3box_client") or "std"),
                "global_level": self.settings.get_int(
                    "jx3box_global_level", minimum=1, maximum=999
                ),
                "mount": 10021,
                "star": 1,
            },
            ttl=0,
            namespace="jx3box:probe",
        )
        total = data.get("total") if isinstance(data, dict) else 0
        return {
            "ok": True,
            "message": f"JX3BOX 连接正常（花间配装 {total} 套）",
        }

    def clear_local_cache(self) -> None:
        """Drop the in-memory item group index after a config/cache reset."""

        for namespace in self.cache.stats()["namespaces"]:
            if namespace.startswith("jx3box"):
                self.cache.clear(namespace)

    async def close(self) -> None:  # pragma: no cover - symmetry with clients
        return None


def _describe_box_http_error(exc: HttpError) -> str:
    if exc.status == 404:
        return "JX3BOX 接口不存在，可能已调整，请反馈给插件作者。"
    if exc.status in {502, 503, 504}:
        return "JX3BOX 服务暂时不可用，请稍后再试。"
    if exc.status == 429:
        return "JX3BOX 请求过于频繁，请稍后再试。"
    return f"JX3BOX 请求失败：{exc.message}"
