"""Chat output formatting helpers.

The JX3API and JX3BOX payloads are not fully uniform across endpoints (English
and camelCase aliases, lists wrapped in ``data``, ...).  The helpers below are
deliberately tolerant: they never raise on an unexpected shape, so a changed
upstream field degrades to a shorter answer instead of an exception.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterable

STATUS_LABELS = {0: "维护中", 1: "正常", 2: "繁忙", 3: "爆满"}
EVENT_STATUS_LABELS = {0: "未触发", 1: "已触发", 2: "已完成"}


def pick(data: Any, *keys: str, default: Any = "") -> Any:
    if not isinstance(data, dict):
        return default
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return default


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (list, tuple)):
        return "、".join(text(item) for item in value if text(item))
    return str(value).strip()


def as_list(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "list", "records", "items", "rows"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def clip(value: Any, limit: int = 120) -> str:
    result = " ".join(text(value).split())
    if len(result) <= limit:
        return result
    return result[: max(0, limit - 1)] + "…"


def join_values(value: Any, sep: str = "、") -> str:
    if isinstance(value, (list, tuple, set)):
        return sep.join(text(item) for item in value if text(item))
    return text(value)


def format_timestamp(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return clip(value, 40)
    if timestamp > 10_000_000_000:  # milliseconds
        timestamp /= 1000
    try:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError, OverflowError):
        return clip(value, 40)


def format_date(value: Any) -> str:
    timestamp = format_timestamp(value)
    return timestamp.split(" ")[0] if timestamp else ""


def format_gold(amount: Any) -> str:
    try:
        copper = max(0, int(amount))
    except (TypeError, ValueError):
        return text(amount)
    gold, rest = divmod(copper, 10000)
    silver, copper = divmod(rest, 100)
    parts: list[str] = []
    if gold:
        parts.append(f"{gold}金")
    if silver:
        parts.append(f"{silver}银")
    if copper or not parts:
        parts.append(f"{copper}铜")
    return "".join(parts)


def calendar(data: Any) -> str:
    if isinstance(data, dict) and isinstance(data.get("total"), list):
        return "\n\n".join(calendar(item) for item in data["total"])
    if isinstance(data, list):
        return "\n\n".join(calendar(item) for item in data)
    if not isinstance(data, dict):
        return "今天没有查询到活动日历。"
    lines = [
        f"📅 {text(pick(data, 'date'))} 星期{text(pick(data, 'week'))}",
        f"大战：{text(pick(data, 'war'))}",
        f"战场：{text(pick(data, 'battle'))}",
        f"矿车：{text(pick(data, 'orecar'))}",
        f"驰援：{text(pick(data, 'rescue'))}",
    ]
    school = text(pick(data, "school"))
    if school:
        lines.append(f"门派：{school}")
    lucky = join_values(pick(data, "lucky", "luck"))
    if lucky:
        lines.append(f"福缘：{lucky}")
    cards = join_values(pick(data, "card"))
    if cards:
        lines.append(f"副本：{cards}")
    draw = join_values(pick(data, "draw"))
    if draw:
        lines.append(f"美人图：{draw}")
    weekly = pick(data, "weekly")
    if isinstance(weekly, dict):
        conn = join_values(pick(weekly, "conn"))
        raid = join_values(pick(weekly, "raid"))
        if conn:
            lines.append(f"周常·五人：{conn}")
        if raid:
            lines.append(f"周常·团队：{raid}")
    return "\n".join(lines)


def server_status(data: Any, keyword: str = "") -> str:
    rows = as_list(data)
    if not rows and isinstance(data, dict):
        rows = [data]
    keyword = str(keyword or "").strip()
    if keyword:
        rows = [
            row
            for row in rows
            if isinstance(row, dict) and keyword in text(pick(row, "server"))
        ]
    if not rows:
        return f"没有找到区服「{keyword}」的状态，请检查区服名称。" if keyword else "没有查询到区服状态。"
    lines: list[str] = []
    zones: dict[str, list[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        server = text(pick(row, "server")) or "未知区服"
        raw_status = pick(row, "status", default=None)
        try:
            label = STATUS_LABELS.get(int(raw_status), f"状态 {raw_status}")
        except (TypeError, ValueError):
            label = text(raw_status) or "未知"
        zone = text(pick(row, "zone")) or "其他"
        zones.setdefault(zone, []).append(f"{server} {label}")
        last_time = format_timestamp(pick(row, "lasttime", "last_time", default=""))
        if last_time:
            lines.append(f"· {server}｜{label}｜最近开服 {last_time}")
        else:
            lines.append(f"· {server}｜{label}")
    if keyword and len(rows) == 1:
        return "\n".join(lines)
    summary = "  ".join(
        f"{zone} {len(items)} 个" for zone, items in zones.items() if items
    )
    header = f"🖥 区服状态（{len(rows)} 个）" + (f"\n{summary}" if summary else "")
    return header + "\n" + "\n".join(lines[:20])


def gold(data: Any, server: str = "") -> str:
    rows = as_list(data)
    if not rows and isinstance(data, dict):
        rows = [data]
    if not rows:
        return "没有查询到金价数据。"
    lines = [f"💰 金价行情{f'（{server}）' if server else ''}"]
    for row in rows[:10]:
        if not isinstance(row, dict):
            continue
        name = text(pick(row, "server")) or server or "未知区服"
        parts = [
            f"贴吧 {text(pick(row, 'tieba', default='-')) or '-'}",
            f"万宝楼 {text(pick(row, 'wanbaolou', default='-')) or '-'}",
            f"DD373 {text(pick(row, 'dd373', default='-')) or '-'}",
        ]
        date = format_date(pick(row, "date", "time", default=""))
        suffix = f"｜{date}" if date else ""
        lines.append(f"· {name}｜" + "｜".join(parts) + suffix)
    if len(rows) > 10:
        lines.append(f"…还有 {len(rows) - 10} 条")
    return "\n".join(lines)


def sand(data: Any, server: str = "") -> str:
    if not isinstance(data, dict):
        return "没有查询到沙盘数据。"
    rows = as_list(pick(data, "data"))
    lines = [
        f"🗺 阵营沙盘{f'（{server}）' if server else ''}",
        f"更新时间：{format_timestamp(pick(data, 'update', default='')) or '—'}",
        f"重置时间：{format_timestamp(pick(data, 'reset', default='')) or '—'}",
    ]
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        camp = text(pick(row, "campName", "camp_name")) or "未知阵营"
        groups.setdefault(camp, []).append(row)
    for camp, items in groups.items():
        lines.append(f"\n{camp}（{len(items)} 个据点）")
        for row in items[:8]:
            castle = text(pick(row, "castleName", "castle_name")) or "未知据点"
            guild = text(pick(row, "tongName", "tong_name")) or "无"
            master = text(pick(row, "masterName", "master_name")) or "-"
            lines.append(f"  · {castle}｜帮会 {guild}｜帮主 {master}")
        if len(items) > 8:
            lines.append(f"  …还有 {len(items) - 8} 个据点")
    if not rows:
        lines.append("暂无沙盘数据。")
    return "\n".join(lines)


def role(data: Any, server: str = "", name: str = "") -> str:
    if not isinstance(data, dict):
        return "没有查询到角色信息。"
    role_name = text(pick(data, "roleName", "role_name", "name")) or name
    zone = text(pick(data, 'zoneName', 'zone'))
    area = text(pick(data, 'serverName', 'server')) or server
    lines = [f"{role_name} · {area}", ' · '.join(v for v in [text(pick(data, 'forceName', 'force_name')), text(pick(data, 'bodyName', 'body_name'))] if v), '',
        f"阵营：{text(pick(data, 'campName', 'camp_name')) or '无'}", f"帮会：{text(pick(data, 'tongName', 'tong_name')) or '无'}"]
    if zone and zone != area: lines.append('大区：' + zone)
    role_id = text(pick(data, "roleId", "role_id"))
    if role_id:
        lines.append(f"\n角色 ID：{role_id}")
    history = pick(data, "history")
    if isinstance(history, list) and history:
        lines.append(f"历史记录：{len(history)} 条")
    return "\n".join(lines)


def events(data: Any, server: str = "", name: str = "") -> str:
    from .render import qiyu_context
    context = qiyu_context(data, server=server, name=name)
    rare = context["jsqy"]
    rows = sorted(rare + context["ptqy"], key=lambda row: row["time"], reverse=True)
    if not rows:
        return f"{server} · {name}：没有查到奇遇记录。"
    lines = [f"{server} · {name} · 奇遇记录", f"绝世 {len(rare)} · 普通 {len(context['ptqy'])}", ""]
    for row in rows:
        lines.append(row["event"] + ("〔绝世〕" if row in rare else "") + "  " + (row["time"][:16] or "—"))
    return "\n".join(lines)


def _summarize_mapping(data: dict[str, Any], limit: int = 12) -> list[str]:
    lines: list[str] = []
    for key, value in list(data.items())[:limit]:
        if isinstance(value, (str, int, float, bool)):
            if text(value):
                lines.append(f"{key}：{clip(value, 160)}")
        elif isinstance(value, list):
            names = [
                text(pick(item, "name", "title", "event", "desc"))
                if isinstance(item, dict)
                else text(item)
                for item in value[:5]
            ]
            names = [name for name in names if name]
            if names:
                lines.append(f"{key}：{join_values(names)}")
        elif isinstance(value, dict):
            nested = "、".join(
                f"{k}={clip(v, 30)}"
                for k, v in list(value.items())[:4]
                if isinstance(v, (str, int, float, bool)) and text(v)
            )
            if nested:
                lines.append(f"{key}：{nested}")
    return lines


def event_strategy(data: Any, name: str = "") -> str:
    if isinstance(data, dict):
        lines = [f"📖 {name or '奇遇'} 攻略"]
        lines.extend(_summarize_mapping(data, limit=14))
        if len(lines) == 1:
            lines.append(clip(json.dumps(data, ensure_ascii=False), 800))
            return "\n".join(lines)
    if isinstance(data, list):
        lines = [f"📖 {name or '奇遇'} 攻略"]
        for item in data[:10]:
            if isinstance(item, dict):
                title = text(pick(item, "name", "title", "event"))
                desc = clip(pick(item, "desc", "content", "tips"), 160)
                if title:
                    lines.append(f"· {title}" + (f"：{desc}" if desc else ""))
            elif text(item):
                lines.append(f"· {clip(item, 160)}")
        return "\n".join(lines)
    return clip(data, 1200) or "没有查询到攻略。"


def exam(data: Any, subject: str = "") -> str:
    rows = as_list(data)
    if not rows:
        return f"没有找到「{subject}」相关的科举答案。"
    lines = [f"📚 科举答案：{subject}"]
    for row in rows[:5]:
        if not isinstance(row, dict):
            continue
        question = clip(pick(row, "question", "q"), 160)
        answer = clip(pick(row, "answer", "a"), 160)
        if question:
            lines.append(f"\n题目：{question}")
        if answer:
            lines.append(f"答案：{answer}")
    return "\n".join(lines)


def trade(data: Any, name: str = "", server: str = "") -> str:
    lines = [f"🛒 物价：{name}" + (f"（{server}）" if server else "")]
    rows: list[Any] = []
    if isinstance(data, dict):
        title = text(pick(data, "name", "itemName"))
        if title:
            lines[0] = f"🛒 物价：{title}" + (f"（{server}）" if server else "")
        grouped: list[dict[str, Any]] = []
        for group in as_list(pick(data, "list")):
            if not isinstance(group, dict):
                continue
            group_name = text(pick(group, "name")) or "记录"
            for item in as_list(pick(group, "list")):
                if isinstance(item, dict):
                    grouped.append({**item, "group": group_name})
        rows = grouped or as_list(data)
        if not rows:
            rows = as_list(pick(data, "sales")) or [data]
    else:
        rows = as_list(data)
    if not rows:
        lines.append("没有查询到成交记录。")
        return "\n".join(lines)
    for row in rows[:10]:
        if not isinstance(row, dict):
            continue
        price = pick(row, "value", "price", "unit_price", "amount", default=None)
        try:
            price_text = f"{float(price):g} 元"
        except (TypeError, ValueError):
            price_text = text(price) if price not in (None, "") else "—"
        row_server = text(pick(row, "server", "zone")) or server or "—"
        when = format_timestamp(pick(row, "time", "date", default="")) or text(
            pick(row, "date", default="")
        )
        group = text(pick(row, "group", default=""))
        lines.append(
            f"· {row_server}｜{price_text}"
            + (f"｜{group}" if group else "")
            + (f"｜{when}" if when else "")
        )
    if len(rows) > 10:
        lines.append(f"…还有 {len(rows) - 10} 条")
    return "\n".join(lines)


def achievement(data: Any, server: str = "", name: str = "") -> str:
    lines = [f"🏅 {name} 的资历分布" + (f"（{server}）" if server else "")]
    if isinstance(data, dict):
        score = pick(data, "totalScore", "total_score", "score")
        if score not in (None, ""):
            lines.append(f"总资历：{text(score)}")
        speed = pick(data, "speed")
        if speed not in (None, ""):
            lines.append(f"速度：{text(speed)}")
        lines.extend(_summarize_mapping(data, limit=10))
        rows = as_list(pick(data, "data", "list", "classes"))
        for row in rows[:12]:
            if not isinstance(row, dict):
                continue
            bucket = text(pick(row, "name", "subclass", "class", "map"))
            total = pick(row, "total", "totalScore", "count", default="")
            if bucket:
                lines.append(f"· {bucket}" + (f"：{text(total)}" if total != "" else ""))
    else:
        lines.append(clip(data, 1000))
    lines.append("\n数据来源：JX3API · 推栏")
    return "\n".join(lines)


def news(data: Any, *, limit: int = 8, announce: bool = False) -> str:
    rows = as_list(data)
    title = "📰 维护公告" if announce else "📰 新闻资讯"
    if not rows:
        return f"{title}：暂时没有内容。"
    lines = [title]
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        item_title = clip(pick(row, "title", "name"), 80)
        kind = text(pick(row, "type", "category"))
        date = format_date(pick(row, "date", "time", default=""))
        url = text(pick(row, "url", "link"))
        meta = " · ".join(part for part in (kind, date) if part)
        lines.append(f"\n{item_title}" + (f"\n  {meta}" if meta else ""))
        if url:
            lines.append(f"  {url}")
    if len(rows) > limit:
        lines.append(f"…还有 {len(rows) - limit} 条")
    return "\n".join(lines)


def rework(data: Any) -> str:
    rows = as_list(data)
    if not rows:
        return "暂时没有技改记录。"
    lines = ["🛠 武学调整公告"]
    for row in rows[:10]:
        if not isinstance(row, dict):
            continue
        title = clip(pick(row, "title", "name"), 90)
        when = text(pick(row, "time", "date"))
        url = text(pick(row, "url", "link"))
        lines.append(f"\n{title}" + (f"\n  {when}" if when else ""))
        if url:
            lines.append(f"  {url}")
    return "\n".join(lines)


def builds(data: dict[str, Any]) -> str:
    kungfu = text(data.get("kungfu"))
    items = data.get("items") or []
    total = data.get("total") or len(items)
    lines = [f"🌸 {kungfu} 配装（共 {total} 套）"]
    if not items:
        lines.append("暂时没有找到配装方案。")
        return "\n".join(lines)
    for item in items[:6]:
        title = clip(item.get("title"), 50)
        tags = "、".join(item.get("tags") or [])
        lines.append(f"\n· {title}" + (f"  [{tags}]" if tags else ""))
        meta = []
        if item.get("author"):
            meta.append(f"作者 {item['author']}")
        if item.get("season"):
            meta.append(text(item["season"]))
        if meta:
            lines.append("  " + " · ".join(meta))
        if item.get("url"):
            lines.append(f"  {item['url']}")
    lines.append("\n数据来源：JX3BOX 魔盒")
    return "\n".join(lines)


def macros(data: dict[str, Any]) -> str:
    kungfu = text(data.get("kungfu"))
    lines = [f"📜 {kungfu} 一键宏", f"《{clip(data.get('title'), 60)}》 by {text(data.get('author'))}"]
    if data.get("url"):
        lines.append(str(data["url"]))
    for macro in (data.get("macros") or [])[:3]:
        name = clip(macro.get("name"), 40)
        desc = clip(macro.get("desc"), 120)
        code = str(macro.get("macro") or "").strip()
        lines.append(f"\n【{name}】" + (f"\n{desc}" if desc else ""))
        lines.append("```")
        lines.append(clip(code, 700))
        lines.append("```")
    lines.append("\n数据来源：JX3BOX 魔盒")
    return "\n".join(lines)


def auction(rows: list[dict[str, Any]], name: str = "", server: str = "") -> str:
    lines = [f"🏷 交易行：{name}" + (f"（{server}）" if server else "")]
    if not rows:
        lines.append("暂时没有报价。")
        return "\n".join(lines)
    for row in rows[:10]:
        lines.append(
            f"· {clip(row.get('name'), 40)}｜{format_gold(row.get('price'))}"
            f"｜样本 {row.get('sample', 0)}"
        )
    lines.append("\n数据来源：JX3BOX 魔盒 · 成交价按小时聚合")
    return "\n".join(lines)


def kungfu_list(query: str = "") -> str:
    from . import assets

    entries = list(assets.kungfu_entries())
    keyword = str(query or "").strip()
    if keyword:
        entries = [
            entry
            for entry in entries
            if keyword in entry["name"]
            or any(keyword in alias for alias in entry["aliases"])
        ]
    if not entries:
        return f"没有找到心法「{keyword}」。"
    lines = ["🎴 支持的心法 / 门派"]
    groups: dict[str, list[str]] = {}
    for entry in entries:
        role = entry["role"] or "其他"
        label = entry["name"]
        if entry["aliases"]:
            label += f"（{'/'.join(entry['aliases'][:2])}）"
        groups.setdefault(role, []).append(label)
    for role, names in groups.items():
        lines.append(f"\n{role}：" + "、".join(names))
    lines.append("\n用法：配装 花间 / 宏 奶花")
    return "\n".join(lines)


def ticket_status(summary: dict[str, Any], validation: dict[str, Any] | None = None) -> str:
    lines = ["🎫 推栏 Ticket"]
    if summary.get("configured"):
        lines.append(f"状态：已配置（{summary.get('masked')}，{summary.get('length')} 位）")
    else:
        lines.append("状态：未配置")
    if validation is not None:
        icon = "✅" if validation.get("ok") else "❌"
        lines.append(f"检测：{icon} {validation.get('message')}")
    lines.append(
        "\nTicket 用于名剑、名片、门派、资历等需要推栏数据的接口；"
        "与 JX3API Token 不同，两者都需要填写。"
    )
    lines.append("发送「推栏 帮助」查看抓包获取方法。")
    return "\n".join(lines)


def help_text(
    specs: Iterable[Any],
    *,
    version: str,
    token_configured: bool,
    ticket_configured: bool,
    default_server: str,
) -> str:
    lines = ["剑网3百宝箱", f"当前区服：{default_server}" if default_server else "", ""]
    categories: dict[str, list[Any]] = {}
    for spec in specs:
        categories.setdefault(spec.category, []).append(spec)
    for category, items in categories.items():
        lines.append(f"【{category}】")
        for spec in items:
            lines.append("· " + spec.usage.replace("<", "").replace(">", ""))
        lines.append("")
    return "\n".join(lines).strip()


def split_message(text_value: str, limit: int = 1800, max_parts: int = 4) -> list[str]:
    value = str(text_value or "").strip()
    if not value:
        return []
    parts: list[str] = []
    while len(value) > limit and len(parts) < max_parts:
        cut = value.rfind("\n", 0, limit)
        if cut < int(limit * 0.6):
            cut = limit
        parts.append(value[:cut].rstrip())
        value = value[cut:].lstrip("\n")
    if value:
        parts.append(value)
    if len(parts) > max_parts:
        parts = parts[:max_parts]
        parts[-1] = parts[-1][: max(0, limit - 20)] + "\n…内容过长已截断"
    return [part for part in parts if part.strip()]
