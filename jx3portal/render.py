"""HTML/Jinja2 图片渲染：复用参考插件的 templates/pages 页面。

渲染回调把 HTML+Jinja2 截成图片；本模块负责：

* 读取 ``templates/pages`` 页面；
* 套用 ``layouts/base.html`` + ``styles``；
* 使用版本化的本机字体和图标地址，外部渲染服务则使用 data URI；
* 处理页面里的 ``__INK_CSS__`` / ``__DAILY_CSS__`` 占位符。

渲染器不依赖 AstrBot 才能做模板组装，测试可直接调用 ``build_html``。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import shutil
import time
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote
from .cache import TTLCache

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
PAGE_DIR = TEMPLATE_DIR / "pages"
LAYOUT_DIR = TEMPLATE_DIR / "layouts"
STYLE_DIR = TEMPLATE_DIR / "styles"

RenderCallback = Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[Any]]

_TITLE_RE = re.compile(r"\{#\s*template-title:\s*(.*?)\s*#\}", re.DOTALL)
_ASSET_URL_RE = re.compile(
    r"url\(\s*['\"]?(?:daily|ink)-asset:([^'\")]+)['\"]?\s*\)", re.IGNORECASE
)
_ICON_GROUP_RE = re.compile(r"icons\.(img|sand|sect|serendipity)\b")


class RenderError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@lru_cache(maxsize=256)
def _asset_version(path: Path, modified: int, size: int) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _data_uri(path: Path, origin: str = "") -> str:
    if origin:
        stat = path.stat()
        version = _asset_version(path, stat.st_mtime_ns, stat.st_size)
        return origin.rstrip('/') + '/' + quote(path.relative_to(TEMPLATE_DIR).as_posix()) + '?v=' + version
    suffix = path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".woff2": "font/woff2",
        ".woff": "font/woff",
    }.get(suffix, "application/octet-stream")
    raw = path.read_bytes()
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


@lru_cache(maxsize=8)
def _icon_group(group: str, origin: str = "") -> dict[str, str]:
    folder = {
        "img": TEMPLATE_DIR / "img",
        "sand": TEMPLATE_DIR / "img" / "sand",
        "sect": TEMPLATE_DIR / "sect",
        "serendipity": TEMPLATE_DIR / "serendipity",
    }.get(group)
    if folder is None or not folder.is_dir():
        return {}
    result: dict[str, str] = {}
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            try:
                result[path.stem] = _data_uri(path, origin)
            except OSError:
                continue
    return result


def icon_groups() -> dict[str, dict[str, str]]:
    return {
        "img": dict(_icon_group("img")),
        "sand": dict(_icon_group("sand")),
        "sect": dict(_icon_group("sect")),
        "serendipity": dict(_icon_group("serendipity")),
    }


def _icons_for_page(page_id: str, origin: str = "") -> dict[str, dict[str, str]]:
    content = _read(PAGE_DIR / f"{page_id}.html")
    groups = set(_ICON_GROUP_RE.findall(content))
    return {group: dict(_icon_group(group, origin)) for group in groups}


@lru_cache(maxsize=128)
def _read_version(path: Path, modified: int, size: int) -> str:
    return path.read_text(encoding="utf-8-sig")


def _read(path: Path) -> str:
    try:
        stat = path.stat()
        return _read_version(path, stat.st_mtime_ns, stat.st_size)
    except OSError:
        return ""


def _resolve_css(css: str, origin: str = "") -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        for folder in (
            TEMPLATE_DIR / "assets" / "ink",
            TEMPLATE_DIR / "assets" / "daily",
            TEMPLATE_DIR / "img",
        ):
            for candidate in (name, name.rsplit(".", 1)[0] + ".jpg"):
                path = folder / candidate
                if path.is_file() and path.stat().st_size <= 16 * 1024 * 1024:
                    try:
                        return f"url('{_data_uri(path, origin)}')"
                    except OSError:
                        break
        return "url('')"

    return _ASSET_URL_RE.sub(replace, css)


def _title_for(page_id: str, content: str) -> str:
    match = _TITLE_RE.search(content)
    if not match:
        return page_id
    title = re.sub(r"\{\{.*?\}\}", "", match.group(1)).strip()
    return title or page_id


def _page_css(page_id: str, origin: str = "") -> str:
    parts = [
        _read(STYLE_DIR / "tokens.css"),
        _read(STYLE_DIR / "base.css"),
        _read(STYLE_DIR / "components.css"),
    ]
    page_css = STYLE_DIR / "pages" / f"{page_id}.css"
    if page_css.is_file():
        parts.append(_read(page_css))
    if page_id in {"richangyuche", "daily"}:
        parts.append(_read(STYLE_DIR / "daily.css"))
    if page_id.startswith(("juesheqiyu", "qiyu", "jinqiqiyu", "weizuoqiyu")):
        parts.append(_read(STYLE_DIR / "ink.css"))
    return _resolve_css("\n".join(part for part in parts if part), origin)


@lru_cache(maxsize=64)
def _build_html(page_id: str, revision: tuple, origin: str = "") -> str:
    page_path = PAGE_DIR / f"{page_id}.html"
    if not page_path.is_file():
        raise RenderError(f"模板不存在：{page_id}")
    content = _read(page_path)
    title = _title_for(page_id, content)
    for marker, sheet in (("__INK_CSS__", "ink.css"), ("__DAILY_CSS__", "daily.css")):
        if marker in content:
            css = _resolve_css(_read(STYLE_DIR / sheet), origin)
            content = content.replace("/*" + marker + "*/", css).replace(marker, css)

    if re.search(r"<!doctype|<html", content, re.IGNORECASE):
        return content

    layout = _read(LAYOUT_DIR / "base.html")
    if not layout:
        return (
            f"<!doctype html><html><head><meta charset='utf-8'><style>{_page_css(page_id, origin)}</style>"
            f"</head><body>{content}</body></html>"
        )
    layout = layout.replace("<!--__PAGE_TITLE__-->", "__PAGE_TITLE__")
    layout = layout.replace("<!--__PAGE_CONTENT__-->", "__PAGE_CONTENT__")
    return (
        layout.replace("__PAGE_TITLE__", title)
        .replace("__PAGE_ID__", page_id)
        .replace("__PAGE_CONTENT__", content)
        .replace("/*__TOKENS_CSS__*/", _resolve_css(_read(STYLE_DIR / "tokens.css"), origin))
        .replace("/*__PAGE_CSS__*/", _resolve_css(_read(STYLE_DIR / "pages" / f"{page_id}.css"), origin))
        .replace("/*__INK_CSS__*/", _resolve_css(_read(STYLE_DIR / "ink.css"), origin))
        .replace("/*__HIERARCHY_CSS__*/", _resolve_css(_read(STYLE_DIR / "hierarchy.css"), origin))
        .replace("/*__BASE_CSS__*/", _resolve_css(_read(STYLE_DIR / "base.css"), origin))
        .replace(
            "/*__COMPONENTS_CSS__*/", _resolve_css(_read(STYLE_DIR / "components.css"), origin)
        )
    )


def list_templates() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not PAGE_DIR.is_dir():
        return result
    for path in sorted(PAGE_DIR.glob("*.html")):
        content = _read(path)
        result.append(
            {
                "id": path.stem,
                "title": _title_for(path.stem, content),
                "size": path.stat().st_size,
            }
        )
    return result


def asset_summary() -> dict[str, int]:
    def count(folder: Path, suffixes: set[str] | None = None) -> int:
        if not folder.is_dir():
            return 0
        return sum(
            1
            for path in folder.rglob("*")
            if path.is_file()
            and (suffixes is None or path.suffix.lower() in suffixes)
        )

    return {
        "pages": count(PAGE_DIR, {".html"}),
        "styles": count(STYLE_DIR, {".css"}),
        "sect": count(TEMPLATE_DIR / "sect", {".png", ".jpg", ".jpeg"}),
        "serendipity": count(
            TEMPLATE_DIR / "serendipity", {".png", ".jpg", ".jpeg"}
        ),
        "sand": count(TEMPLATE_DIR / "img" / "sand", {".png", ".jpg", ".jpeg"}),
        "icons": count(
            TEMPLATE_DIR / "img", {".png", ".jpg", ".jpeg"}
        ),
    }


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def daily_context(data: Any) -> dict[str, Any]:
    meta = data.get("today", {}) if isinstance(data, dict) else {}
    rows = data.get("total", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    current = str(meta.get("date") or date.today().isoformat())
    today = next((row for row in rows if isinstance(row, dict) and row.get("date") == current), {})
    today = {**today, **(data.get("today_detail", {}) if isinstance(data, dict) else {})}
    items = [dict(row, is_today=row.get("date") == current) for row in rows if isinstance(row, dict) and _parse_date(row.get("date"))]
    items.sort(key=lambda row: row["date"])
    return {"items": items, "today": today, "date": current, "data_time": datetime.now().strftime("%Y-%m-%d %H:%M")}


def sand_context(data: Any, *, server: str = "") -> dict[str, Any]:
    """把 /sand/records 的返回值转成 shapan.html 数据。"""

    records: list[Any] = []
    zone = ""
    update_time = ""
    if isinstance(data, dict):
        records = data.get("data") or data.get("list") or []
        zone = str(data.get("zone") or "")
        server = str(data.get("server") or server)
        raw_update = data.get("update")
        try:
            timestamp = float(raw_update)
            update_time = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, OSError, OverflowError):
            update_time = str(raw_update or "")
    elif isinstance(data, list):
        records = data
    items: list[dict[str, Any]] = []
    for row in records:
        if not isinstance(row, dict):
            continue
        try:
            camp_id = int(row.get("campId") or row.get("camp_id") or 0)
        except (TypeError, ValueError):
            camp_id = 0
        if camp_id not in (1, 2):
            continue
        castle = str(row.get("castleName") or row.get("castle_name") or "").strip()
        if not castle:
            continue
        items.append(
            {
                "castle_name": castle,
                "camp_key": "浩" if camp_id == 1 else "恶",
                "camp_name": str(row.get("campName") or row.get("camp_name") or ""),
                "tong_name": str(row.get("tongName") or row.get("tong_name") or ""),
                "master_name": str(
                    row.get("masterName") or row.get("master_name") or ""
                ),
                "ride_piece": int(row.get("ridePiece") or row.get("ride_piece") or 0),
                "defend_count": int(
                    row.get("defendCount") or row.get("defend_count") or 0
                ),
            }
        )
    return {
        "zone": zone,
        "server": server,
        "update_time": update_time,
        "items": items,
        "data_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _day(value: Any) -> str:
    text = str(value or "")[:10].replace("/", "-")
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return ""


def _price_rows(items: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        day = _day(item.get("date"))
        value = _number(item.get("value", item.get("price")))
        if not day or value is None or value <= 0:
            continue
        remaining = item.get("remaining") or item.get("remaining_time")
        if not remaining and _number(item.get("remainingTime")) is not None:
            seconds = int(float(item["remainingTime"]))
            days, seconds = divmod(seconds, 86400)
            hours, seconds = divmod(seconds, 3600)
            minutes = seconds // 60
            remaining = f"{days}天{hours}时" if days else f"{hours}时{minutes}分"
        rows.append(
            {
                "date": day,
                "value": value,
                "server": str(item.get("server") or ""),
                "status": {1: "出售", 2: "收购", 3: "出售", 4: "收购", 5: "成交", 6: "在售", 7: "公示"}.get(item.get("sale"), str(item.get("status") or "记录")),
                "remaining": str(remaining).removeprefix("剩余") if remaining else "",
            }
        )
    return rows


def _market_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["display_date"] = row["date"][5:].replace("-", ".")
        result.append(item)
    return result


def _price_trend(rows: list[dict[str, Any]], title: str = "出售报价走势") -> dict[str, Any] | None:
    from statistics import median
    grouped = {}
    for row in rows:
        grouped.setdefault(row["date"], []).append(row["value"])
    points = [(day, median(values)) for day, values in sorted(grouped.items())]
    if len(points) < 2:
        return None
    values = [value for _, value in points]
    low, high = min(values), max(values)
    spread = max(high - low, high * 0.12, 1)
    floor, ceiling = max(0, low - spread * 0.18), high + spread * 0.18
    start, end = date.fromisoformat(points[0][0]), date.fromisoformat(points[-1][0])
    span = max(1, (end - start).days)
    xy = [(48 + (date.fromisoformat(day) - start).days / span * 904, 180 - (value - floor) / (ceiling - floor) * 142) for day, value in points]
    path = " ".join(("M" if i == 0 else "L") + f"{x:.1f},{y:.1f}" for i, (x, y) in enumerate(xy))
    svg = '<svg class="chart" viewBox="0 0 1000 230" role="img" aria-label="' + title + '">'
    for value in (low, (low + high) / 2, high):
        y = 180 - (value - floor) / (ceiling - floor) * 142
        svg += f'<path d="M48 {y:.1f} H952" stroke="#bcc8ca" stroke-width="1" opacity=".55"/>'
    svg += f'<path d="{path} L952 190 L48 190 Z" fill="#607f87" opacity=".14"/>'
    svg += f'<path d="{path}" fill="none" stroke="#496c78" stroke-width="2.5" stroke-linejoin="round"/>'
    selected = sorted({0, values.index(low), values.index(high), len(points)-1})
    placed = []
    for index in selected:
        x, y = xy[index]; value = values[index]
        svg += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#496c78" stroke="#f4f4f0" stroke-width="2"/>'
        if all(abs(x-px) > 62 or abs(y-py) > 35 for px,py in placed):
            anchor = "start" if index == 0 else "end" if index == len(points)-1 else "middle"
            svg += f'<text x="{x:.1f}" y="{y-12:.1f}" text-anchor="{anchor}" fill="#293b44" font-size="19">{value:g}</text>'
            placed.append((x,y))
    svg += f'<text x="48" y="220" fill="#586974" font-size="18">{start:%Y.%m.%d}</text>'
    svg += f'<text x="952" y="220" text-anchor="end" fill="#586974" font-size="18">{end:%Y.%m.%d}</text></svg>'
    return {"svg": svg, "title": title, "context": "每日报价中位数 / 元", "period": f"{start:%Y.%m.%d} — {end:%Y.%m.%d}", "change_pct": None, "fused": False, "series": [], "has_gaps": False}


def price_context(data: Any, *, server: str = "") -> dict[str, Any]:
    """把 /trade/records 的 list 分组转成 hangqing.html 的数据。"""

    if not isinstance(data, dict):
        data = {}
    groups = data.get("list")
    if not isinstance(groups, list):
        groups = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        grouped[str(group.get("name") or "")] = _price_rows(group.get("list"))
    notice = grouped.get("公示期", [])
    sale = grouped.get("在售期", [])
    deals = [row for group, rows in grouped.items() if group not in {"公示期", "在售期", "贴吧"} for row in rows]
    tieba = grouped.get("贴吧", [])
    if server:
        notice, sale, deals, tieba = [[row for row in rows if row.get("server") == server] for rows in (notice, sale, deals, tieba)]
    if not notice and not sale:
        # Some deployments return a flat list of records.
        flat = _price_rows(data.get("data") or data.get("records") or [])
        sale = flat

    markets: list[dict[str, Any]] = []
    for title, rows in (("万宝楼公示", notice), ("万宝楼在售", sale)):
        rows = _market_rows(sorted(rows, key=lambda row: (row["date"], row["value"])))
        asof = max((row["date"] for row in rows), default=None)
        values = [row["value"] for row in rows if row["date"] == asof] if asof else []
        markets.append(
            {
                "title": title,
                "rows": sorted(rows, key=lambda row: row["date"], reverse=True)[:10][::-1],
                "asof": asof,
                "minimum": min(values) if values else None,
                "has_remaining": any(row.get("remaining") for row in rows),
                "date_heading": "日期",
            }
        )

    players: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for source, rows in (("交易", deals), ("贴吧", tieba)):
        for row in _price_rows(rows):
            status = row.get("status") or "记录"
            kind = (
                "done"
                if status == "成交"
                else "buy"
                if status in {"收购", "想收"}
                else "sell"
                if status in {"出售", "想出", "正出"}
                else "other"
            )
            label = {"done": "成交", "buy": "收购报价", "sell": "出售报价"}.get(
                kind, status
            )
            key = (row["date"], row.get("server", ""), row["value"], kind, source)
            if key in seen:
                continue
            seen.add(key)
            players.append(
                dict(
                    row,
                    source=source,
                    kind=kind,
                    label=label,
                    display_date=row["date"].replace("-", "."),
                )
            )
    players.sort(key=lambda item: item["date"])
    player_total = len(players)
    players = players[-10:]
    facts: list[dict[str, str]] = []
    for label, key in (
        ("分类", "category"),
        ("售卖日期", "date"),
        ("获取方式", "method"),
        ("不绑定限时", "unbound_duration"),
        ("不绑定限量", "unbound_limit"),
        ("绑定限时", "bound_duration"),
    ):
        value = data.get(key)
        if value not in (None, ""):
            facts.append({"label": label, "value": str(value)})
    trend_rows = [row for row in deals + tieba if row["status"] in {"出售", "想出", "正出"}]
    trend = _price_trend(trend_rows)
    if trend is None:
        trend = _price_trend(sale, "万宝楼在售走势")
    if trend is None:
        trend = _price_trend([row for row in deals + tieba if row["status"] == "成交"], "成交价走势")
    product = {
        "name": str(data.get("name") or "外观价格"),
        "alias": str(data.get("alias") or ""),
        "retail": _number(data.get("retail")),
        "description": str(data.get("desc") or ""),
        "facts": facts,
        "image": (
            {"src": str(data["view"]), "alt": str(data.get("name") or "商品图")}
            if data.get("view")
            else None
        ),
    }
    return {
        "product": product,
        "fact_columns": 2 if len(facts) == 4 else min(3, max(1, len(facts))),
        "markets": markets,
        "players": players,
        "player_total": player_total,
        "player_asof": players[-1]["date"].replace("-", ".") if players else None,
        "has_source": len({player.get("source") for player in players}) > 1,
        "cross_server": len({player.get("server") for player in players}) > 1,
        "trend": trend,
        "server": server,
        "data_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def qiyu_context(data: Any, *, server: str, name: str) -> dict[str, Any]:
    """把 /event/records 的返回值转成 juesheqiyu.html 数据。"""

    rows = data if isinstance(data, list) else []
    if isinstance(data, dict):
        rows = data.get("data") or data.get("list") or []
    rare: list[dict[str, Any]] = []
    normal: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            level = int(row.get("level") or 0)
        except (TypeError, ValueError):
            level = 0
        if level == 0:
            continue
        raw_time = row.get("time")
        try:
            timestamp = float(raw_time)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            time_text = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S") if timestamp > 0 else ""
        except (TypeError, ValueError, OSError, OverflowError):
            time_text = str(raw_time)[:19] if _parse_date(raw_time) else ""
        item = {
            "event": str(row.get("event") or row.get("name") or "奇遇"),
            "time": time_text,
        }
        if level == 2:
            rare.append(item)
        else:
            normal.append(item)
    return {
        "name": name,
        "server": server,
        "jsqy": rare,
        "ptqy": normal,
        "data_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


class ImageRenderer:
    def __init__(self, render_callback: RenderCallback | None = None, cache_dir: Path | None = None, *, asset_origin="") -> None:
        self.render_callback = render_callback
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache = TTLCache(max_entries=100)
        self._slots = asyncio.Semaphore(2)
        self._pending = 0
        self.asset_origin = asset_origin

    @property
    def available(self) -> bool:
        return callable(self.render_callback) and PAGE_DIR.is_dir()

    def build_html(self, page_id: str, data: dict[str, Any] | None = None) -> str:
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", page_id):
            raise RenderError("模板名称无效")
        paths = [PAGE_DIR / f"{page_id}.html", LAYOUT_DIR / "base.html", *STYLE_DIR.rglob("*.css"), *(TEMPLATE_DIR / "assets/ink").glob("*")]
        revision = tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in paths if path.is_file())
        origin = self.asset_origin() if callable(self.asset_origin) else self.asset_origin
        return _build_html(page_id, revision, origin)

    async def render(self, page_id: str, data: dict[str, Any] | None = None, options: dict[str, Any] | None = None, *, use_cache=True) -> str:
        if not self.available:
            raise RenderError("图片暂时无法生成")
        payload = dict(data or {})
        html = "{% autoescape true %}" + self.build_html(page_id) + "{% endautoescape %}"
        width = {"help_dynamic": 1040, "game_records": 1040, "equipment": 1440, "richangyuche": 1040, "shapan": 1339, "juesheqiyu": 960, "hangqing": 1180}.get(page_id, 1200)
        options = {"height": 600, "full_page": True, "type": "jpeg", "quality": 88, "width": width, **(options or {})}
        if '--brush:' in html or '<script' not in html.lower():
            options.setdefault('ready_mode', 'document')
        stable = {key: value for key, value in payload.items() if key != "data_time"}
        key = hashlib.sha256((html + json.dumps([stable, options], sort_keys=True, ensure_ascii=False, default=str)).encode()).hexdigest()
        ttl = 86400 * 30 if page_id == "help_dynamic" else 86400 if page_id in {'article','news_summary'} else 60
        path = self.cache_dir / f"{key}.jpg" if self.cache_dir else None
        if use_cache and path and path.is_file() and time.time() - path.stat().st_mtime < ttl:
            return str(path)
        payload.setdefault("data_time", datetime.now().strftime("%Y-%m-%d %H:%M"))
        origin = self.asset_origin() if callable(self.asset_origin) else self.asset_origin
        payload.setdefault("icons", _icons_for_page(page_id, origin))
        async def create():
            if self._pending >= 16: raise RenderError("出图的人较多，请稍后再试。")
            self._pending += 1
            try:
                async with asyncio.timeout(15):
                    async with self._slots:
                        result = str(await self.render_callback(html, payload, options))
            except TimeoutError as exc:
                raise RenderError("图片生成超时") from exc
            finally:
                self._pending -= 1
            if not result or result in {"None", "False"}:
                raise RenderError("图片生成失败")
            if path and Path(result).is_file():
                temporary = path.with_suffix(".tmp")
                await asyncio.to_thread(shutil.copyfile, result, temporary)
                temporary.replace(path)
                files = sorted(self.cache_dir.glob("*.jpg"), key=lambda item: item.stat().st_mtime, reverse=True)
                for old in files[100:]:
                    if time.time() - old.stat().st_mtime > 3600:
                        old.unlink(missing_ok=True)
                return str(path)
            return result
        if not use_cache:
            return await create()
        # Disk paths are checked on every call; pending tasks still coalesce.
        return await self.cache.get_or_load("render", key, 1 if path else ttl, create)

    async def close(self):
        await self.cache.close()

    def clear_cache(self):
        self.cache.clear()
        if self.cache_dir:
            for path in self.cache_dir.glob("*.jpg"):
                path.unlink(missing_ok=True)

    async def daily(self, data: Any) -> str:
        return await self.render("richangyuche", daily_context(data))

    async def qiyu(self, data: Any, *, server: str, name: str) -> str:
        return await self.render("juesheqiyu", qiyu_context(data, server=server, name=name))

    async def sand(self, data: Any, *, server: str = "") -> str:
        return await self.render("shapan", sand_context(data, server=server))

    async def price(self, data: Any, *, server: str = "") -> str:
        return await self.render("hangqing", price_context(data, server=server))

    async def help(self, context: dict[str, Any]) -> str:
        return await self.render("help_dynamic", context)
