"""JX3 Portal - a JX3API + JX3BOX toolkit for AstrBot.

The package is deliberately importable without AstrBot so that the HTTP
clients, formatting and admin controller can be tested with plain ``unittest``.
Only :mod:`main` imports ``astrbot``.
"""

from __future__ import annotations

__all__ = ["PLUGIN_NAME", "PLUGIN_VERSION", "PLUGIN_DESC"]

PLUGIN_NAME = "astrbot_plugin_jx3_portal"
PLUGIN_VERSION = "1.4.7"
PLUGIN_DESC = (
    "剑网3百宝箱：JX3API + JX3BOX 查询、推栏 Ticket、事件推送、角色在线、"
    "付费授权、豆包生图与可视化后台"
)
