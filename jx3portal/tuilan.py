"""推栏 (Tuilan) ticket helpers.

JX3API uses two independent credentials:

* ``token``  - a JX3API subscription token (LV.1 / LV.2);
* ``ticket`` - the login ticket of the official 推栏 App, forwarded to the
  endpoints that need 推栏 data (arena, cards, schools, 资历, ...).

This module normalises what users paste (raw ticket, ``ticket=...`` fragment,
a whole Cookie header or a copied URL) and validates it through a ticket
required JX3API endpoint.  The plugin never talks to 推栏 directly; that keeps
the implementation stable when 推栏 changes its private API.
"""

from __future__ import annotations

import re
import time
import urllib.parse
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .jx3api import JX3APIClient

_TICKET_PAIR = re.compile(r"(?:^|[;\s])ticket=([^;\s&]+)", re.IGNORECASE)

TICKET_GUIDE = """\
推栏 Ticket 获取方法：
1. 手机安装「推栏」App 并登录剑网3账号；
2. 用抓包工具（如 Reqable / Stream）抓取推栏的 HTTPS 请求；
3. 在请求头 Cookie 或 URL 参数中找到 ticket=...，复制等号后面的值；
4. 粘贴到后台「接口配置 → 推栏 Ticket」，保存后点击「检测 Ticket」。

说明：
· Ticket 是推栏登录凭证，不是 JX3API Token，两者都要填写；
· Ticket 会过期，失效后名剑、名片、门派、资历等接口会返回 403；
· Ticket 等同于登录态，请勿发给他人，后台只显示掩码。
"""


def normalize_ticket(value: Any) -> str:
    """Accept a raw ticket, ``ticket=...`` or a full Cookie/URL string."""

    text = str(value or "").strip().strip("\"'")
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith("cookie:"):
        text = text[len("cookie:") :].strip()
    if lowered.startswith("ticket="):
        text = text[len("ticket=") :].strip()
        # A copied query fragment such as ``ticket=abc&device=pc`` should keep
        # only the ticket value.  Do not URL-decode it: JX3API expects the same
        # raw value that the 推栏 client sends (the reference plugin forwards it
        # verbatim), and decoding would turn e.g. %2B into a literal plus.
        text = re.split(r"[;&\s]", text, maxsplit=1)[0].strip()
        return text
    if text.startswith("http://") or text.startswith("https://"):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(text).query)
        candidate = (query.get("ticket") or [""])[0]
        if candidate:
            return candidate.strip()
    match = _TICKET_PAIR.search(text)
    if match:
        return match.group(1).strip()
    if "ticket" in lowered and "=" in text:
        # A Cookie header with other pairs, or a malformed copy/paste.
        for part in re.split(r"[;\s]+", text):
            if part.lower().startswith("ticket="):
                return part.split("=", 1)[1].strip()
    # A raw ticket may contain characters such as '=' or '%'; keep it intact.
    return text


def mask_ticket(value: Any, keep: int = 4) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= keep:
        return "****"
    return "****" + text[-keep:]


class TuilanService:
    """Ticket status / validation shared by chat commands and the dashboard."""

    def __init__(self, settings: Any, api: "JX3APIClient") -> None:
        self.settings = settings
        self.api = api
        self._checked_at = 0.0
        self._last_result: dict[str, Any] | None = None

    def summary(self) -> dict[str, Any]:
        ticket = self.settings.ticket
        return {
            "configured": bool(ticket),
            "masked": mask_ticket(ticket),
            "length": len(ticket),
            "checked_at": self._checked_at or None,
            "last_result": self._last_result,
        }

    def reset_last_result(self) -> None:
        self._checked_at = 0.0
        self._last_result = None

    async def validate(self) -> dict[str, Any]:
        started = time.monotonic()
        try:
            result = await self.api.probe_ticket()
            payload = {
                "ok": True,
                "message": result.get("message") or "Token 与推栏 Ticket 均有效",
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }
        except Exception as exc:  # converted by callers into a friendly text
            from .jx3api import describe_jx3_error

            payload = {
                "ok": False,
                "message": describe_jx3_error(exc),
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }
        self._checked_at = time.time()
        self._last_result = payload
        return payload
