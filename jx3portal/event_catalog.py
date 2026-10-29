"""JX3API WebSocket event catalog (ported from astrbot_plugin_jx3_miemie).

Action 9001 is a local Weibo subscription. Other action IDs and display fields follow the official
JX3API event channel.  Keep this file data-only: the transport lives in
`event_push.py` so the catalog can be tested without aiohttp/AstrBot.
"""

from __future__ import annotations

DEFAULT_WSS_URL = "wss://socket.nicemoe.cn"
FREE_EVENT_ACTIONS = frozenset({2001, 2002, 2003, 2004, 2005, 2006, 9001})
LOCAL_EVENT_ACTIONS = frozenset({9001})
EVENT_NAMES = {
    9001: "微博动态",
    1001: "奇遇触发",
    1002: "马驹刷新",
    1003: "马驹捕获",
    1004: "扶摇预告",
    1005: "扶摇开启",
    1006: "扶摇点名",
    1007: "烟花报时",
    1008: "的卢预告",
    1009: "的卢刷新",
    1010: "的卢捕获",
    1011: "的卢拍卖",
    1012: "玄晶报时",
    1013: "阵营拍卖",
    1014: "诛恶事件",
    1015: "追魂点名",
    1016: "阵营祭天预告",
    1017: "阵营祭天终点",
    1101: "领地宣战·开始",
    1102: "领地宣战·结束",
    1108: "帮会野外宣战·开始",
    1109: "帮会野外宣战·结束",
    1111: "抢占粮仓",
    1112: "大旗重置",
    1113: "大旗被夺",
    1114: "据点占领",
    1115: "据点占领（无帮会）",
    1116: "小攻防贡献（非开战）",
    1117: "小攻防贡献",
    1118: "大攻防贡献",
    1119: "战利品竞拍",
    1120: "小攻防分红",
    1121: "大攻防分红",
    1122: "大攻防分红（含指挥）",
    2001: "开服状态",
    2002: "官方新闻",
    2003: "版本更新",
    2004: "八卦速报",
    2005: "关隘首领",
    2006: "云丛预告",
}
EVENT_ACTIONS = tuple(EVENT_NAMES)

# action -> (JX3API 接口中文名, 接口路径)
# 事件推送本身走 WebSocket；这里标出同源数据在 JX3API 的查询接口，
# 后台事件列表会同时显示「中文名 + 对应接口」，便于排查和订阅。
EVENT_INTERFACES = {
    9001: ("剑网3官方、余玉贤、邓毅微博", ""),
    1001: ("奇遇记录", "/event/records"),
    1002: ("马场事件", "/ranch/records"),
    1003: ("马场事件", "/ranch/records"),
    1004: ("地图活动", "/active/celebs"),
    1005: ("地图活动", "/active/celebs"),
    1006: ("地图活动", "/active/celebs"),
    1007: ("烟花记录", "/firework/records"),
    1008: ("的卢拍卖", "/steed/records"),
    1009: ("的卢拍卖", "/steed/records"),
    1010: ("的卢拍卖", "/steed/records"),
    1011: ("的卢拍卖", "/steed/records"),
    1012: ("阵营拍卖", "/auction/records"),
    1013: ("阵营拍卖", "/auction/records"),
    1014: ("诛恶事件", "/wicked/records"),
    1015: ("近期奇遇", "/event/recent"),
    1016: ("地图活动", "/active/celebs"),
    1017: ("地图活动", "/active/celebs"),
    1101: ("帮战记录", "/battle/records"),
    1102: ("帮战记录", "/battle/records"),
    1108: ("帮战记录", "/battle/records"),
    1109: ("帮战记录", "/battle/records"),
    1111: ("沙盘据点", "/sand/records"),
    1112: ("沙盘据点", "/sand/records"),
    1113: ("沙盘据点", "/sand/records"),
    1114: ("沙盘据点", "/sand/records"),
    1115: ("沙盘据点", "/sand/records"),
    1116: ("沙盘据点", "/sand/records"),
    1117: ("沙盘据点", "/sand/records"),
    1118: ("沙盘据点", "/sand/records"),
    1119: ("沙盘据点", "/sand/records"),
    1120: ("沙盘据点", "/sand/records"),
    1121: ("沙盘据点", "/sand/records"),
    1122: ("沙盘据点", "/sand/records"),
    2001: ("大区状态", "/server/status/check"),
    2002: ("新闻资讯", "/news/records"),
    2003: ("维护公告", "/news/announce"),
    2004: ("百度贴吧", "/tieba/random"),
    2005: ("关隘首领", "/castle/status"),
    2006: ("地图活动", "/active/celebs"),
}

SERVER_FIELDS = (
    ("大区", "zone", "text"),
    ("服务器", "server", "text"),
)
EVENT_FIELDS = {
    1001: SERVER_FIELDS
    + (
        ("角色", "name", "text"),
        ("奇遇", "event", "text"),
        ("等级", "level", "text"),
        ("时间", "time", "time"),
    ),
    1002: SERVER_FIELDS
    + (
        ("地图", "map_name", "text"),
        ("刷新时间", "time", "time"),
    ),
    1003: SERVER_FIELDS
    + (
        ("名称", "name", "text"),
        ("地图", "map_name", "text"),
        ("马驹", "horse", "text"),
        ("等级", "level", "text"),
        ("捕获时间", "time", "time"),
    ),
    1004: SERVER_FIELDS + (("预告时间", "time", "time"),),
    1005: SERVER_FIELDS + (("开启时间", "time", "time"),),
    1006: SERVER_FIELDS
    + (
        ("点名角色", "name", "list"),
        ("时间", "time", "time"),
    ),
    1007: SERVER_FIELDS
    + (
        ("燃放者", "sender", "text"),
        ("接收者", "receiver", "text"),
        ("烟花", "firework", "text"),
        ("地图", "map_name", "text"),
        ("时间", "time", "time"),
    ),
    1008: SERVER_FIELDS
    + (
        ("马驹", "name", "text"),
        ("地图", "map_name", "text"),
        ("预告时间", "time", "time"),
    ),
    1009: SERVER_FIELDS
    + (
        ("马驹", "name", "text"),
        ("地图", "map_name", "text"),
        ("刷新时间", "refresh_time", "time"),
    ),
    1010: SERVER_FIELDS
    + (
        ("马驹", "name", "text"),
        ("地图", "map_name", "text"),
        ("捕获角色", "capture_role_name", "text"),
        ("角色阵营", "capture_camp_name", "text"),
        ("捕获时间", "capture_time", "time"),
    ),
    1011: SERVER_FIELDS
    + (
        ("马驹", "name", "text"),
        ("竞拍角色", "auction_role_name", "text"),
        ("角色阵营", "auction_camp_name", "text"),
        ("成交金额", "auction_amount", "text"),
        ("拍卖时间", "auction_time", "time"),
    ),
    1012: SERVER_FIELDS
    + (
        ("角色", "role_name", "text"),
        ("副本", "map_name", "text"),
        ("物品", "item_name", "text"),
        ("时间", "time", "time"),
    ),
    1013: SERVER_FIELDS
    + (
        ("竞拍角色", "role_name", "text"),
        ("阵营", "camp_name", "text"),
        ("物品", "item_name", "text"),
        ("成交金额", "item_amount", "text"),
        ("时间", "time", "time"),
    ),
    1014: SERVER_FIELDS
    + (
        ("地图", "map_name", "text"),
        ("时间", "time", "time"),
    ),
    1015: SERVER_FIELDS
    + (
        ("角色所在服", "role_server", "text"),
        ("点名角色", "role_name", "text"),
        ("时间", "time", "time"),
    ),
    1016: SERVER_FIELDS + (("预告时间", "time", "time"),),
    1017: SERVER_FIELDS
    + (
        ("阵营", "camp_name", "text"),
        ("帮会", "tong_name", "text"),
        ("角色", "role_name", "text"),
        ("据点", "castle_name", "text"),
        ("时间", "time", "time"),
    ),
    1101: SERVER_FIELDS
    + (
        ("战场类型", "battlefield_type", "text"),
        ("宣战帮会", "declaring_tong_name", "text"),
        ("应战帮会", "accepting_tong_name", "text"),
        ("领地帮会", "battlefield_tong_name", "text"),
        ("开始时间", "start_time", "time"),
    ),
    1102: SERVER_FIELDS
    + (
        ("战场类型", "battlefield_type", "text"),
        ("宣战帮会", "declaring_tong_name", "text"),
        ("应战帮会", "accepting_tong_name", "text"),
        ("领地帮会", "battlefield_tong_name", "text"),
        ("获胜帮会", "victory_tong_name", "text"),
        ("获胜积分", "victory_score", "text"),
        ("结束时间", "end_time", "time"),
    ),
    1108: SERVER_FIELDS
    + (
        ("战场类型", "battlefield_type", "text"),
        ("宣战帮会", "declaring_tong_name", "text"),
        ("应战帮会", "accepting_tong_name", "text"),
        ("持续时长（小时）", "duration_hours", "text"),
        ("开始时间", "start_time", "time"),
    ),
    1109: SERVER_FIELDS
    + (
        ("战场类型", "battlefield_type", "text"),
        ("宣战帮会", "declaring_tong_name", "text"),
        ("应战帮会", "accepting_tong_name", "text"),
        ("结束时间", "end_time", "time"),
    ),
    1111: SERVER_FIELDS
    + (
        ("据点", "castle_name", "text"),
        ("阵营", "camp_name", "text"),
        ("时间", "time", "time"),
    ),
    1112: SERVER_FIELDS
    + (
        ("据点", "castle_name", "text"),
        ("时间", "time", "time"),
    ),
    1113: SERVER_FIELDS
    + (
        ("阵营", "camp_name", "text"),
        ("地图", "map_name", "text"),
        ("据点", "castle_name", "text"),
        ("时间", "time", "time"),
    ),
    1114: SERVER_FIELDS
    + (
        ("阵营", "camp_name", "text"),
        ("帮会", "tong_name", "text"),
        ("据点", "castle_name", "text"),
        ("时间", "time", "time"),
    ),
    1115: SERVER_FIELDS
    + (
        ("阵营", "camp_name", "text"),
        ("据点", "castle_name", "text"),
        ("时间", "time", "time"),
    ),
    1116: SERVER_FIELDS
    + (
        ("阵营", "camp_name", "text"),
        ("贡献帮会", "tong_name", "list"),
        ("时间", "time", "time"),
    ),
    1117: SERVER_FIELDS
    + (
        ("阵营", "camp_name", "text"),
        ("贡献帮会", "tong_name", "list"),
        ("时间", "time", "time"),
    ),
    1118: SERVER_FIELDS
    + (
        ("阵营", "camp_name", "text"),
        ("贡献帮会", "tong_name", "list"),
        ("时间", "time", "time"),
    ),
    1119: SERVER_FIELDS
    + (
        ("阵营", "camp_name", "text"),
        ("竞拍角色", "role_name", "text"),
        ("物品", "item_name", "text"),
        ("成交金额", "item_amount", "text"),
        ("时间", "time", "time"),
    ),
    1120: SERVER_FIELDS
    + (
        ("阵营", "camp_name", "text"),
        ("分红帮会", "tong_name", "list"),
        ("分红金额", "split_amount", "text"),
        ("时间", "time", "time"),
    ),
    1121: SERVER_FIELDS
    + (
        ("阵营", "camp_name", "text"),
        ("分红帮会", "tong_name", "list"),
        ("分红金额", "split_amount", "text"),
        ("时间", "time", "time"),
    ),
    1122: SERVER_FIELDS
    + (
        ("阵营", "camp_name", "text"),
        ("指挥帮会", "chief_tong_name", "text"),
        ("分红帮会", "tong_name", "list"),
        ("分红金额", "split_amount", "text"),
        ("时间", "time", "time"),
    ),
    2001: SERVER_FIELDS
    + (
        ("状态", "status", "status"),
        ("时间", "time", "time"),
    ),
    2002: (
        ("类型", "type", "text"),
        ("标题", "title", "text"),
        ("日期", "date", "text"),
        ("链接", "url", "text"),
    ),
    2003: (
        ("当前版本", "now_version", "text"),
        ("最新版本", "new_version", "text"),
        ("更新包数量", "package_num", "text"),
        ("更新大小", "package_size", "text"),
    ),
    2004: (
        ("分类", "tags", "text"),
        ("服务器", "server", "text"),
        ("发布者", "name", "text"),
        ("标题", "title", "text"),
        ("日期", "date", "text"),
        ("链接", "url", "text"),
    ),
    2005: (
        ("服务器", "server", "text"),
        ("关卡", "stage", "text"),
        ("开始时间", "start", "time"),
    ),
    2006: (
        ("事件", "name", "text"),
        ("地点", "site", "text"),
        ("说明", "desc", "text"),
        ("时间", "time", "time"),
    ),
}
