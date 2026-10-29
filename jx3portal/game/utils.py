from datetime import datetime,date
from zoneinfo import ZoneInfo

def gold_to_parts(gold_amount):
    """将铜钱数拆成模板可渲染的货币片段"""
    try:
        amount = int(gold_amount or 0)
    except (TypeError, ValueError):
        amount = 0

    if amount <= 0:
        return []

    bricks = amount // 100000000
    gold = (amount % 100000000) // 10000
    silver = (amount % 10000) // 100
    copper = amount % 100

    parts = []
    started = False
    for key, name, value in [
        ("zhuang", "砖", bricks),
        ("jin", "金", gold),
        ("yin", "银", silver),
        ("tong", "铜", copper),
    ]:
        if value != 0:
            started = True
        if started:
            parts.append({"key": key, "name": name, "value": value})

    return parts

def week_to_num(week :str):
    week_map = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,  
    }
    return week_map.get(week,None)

def compare_date_str(date_str: str) -> str:
    """
    date_str 格式：YYYY-MM-DD
    """
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    today = date.today()

    if d < today:
        return "过去"
    elif d == today:
        return "今天"
    else:
        return "将来"

def format_time(ts):
    try:
        return datetime.fromtimestamp(int(ts),
            tz=ZoneInfo("Asia/Shanghai")
            ).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return ""

def format_remaining(ts):
    try:
        seconds = max(0, int(ts) - int(datetime.now().timestamp()))
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        return f"{hours}时{minutes:02d}分{seconds:02d}秒"
    except (TypeError, ValueError):
        return ""
