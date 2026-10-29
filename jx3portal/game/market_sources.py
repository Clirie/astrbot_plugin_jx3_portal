"""Read-only public market history; credentials from JX3API never leave that client."""
import asyncio
import math
import json
import hashlib
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from .market_fusion import LEGACY_KINDS


SHANGHAI = ZoneInfo("Asia/Shanghai")


def source_day(value):
    """Provider timestamps are UTC; display their actual China calendar day."""
    try:
        if isinstance(value, (int, float)):
            stamp = value / 1000 if value > 10_000_000_000 else value
            return datetime.fromtimestamp(stamp, SHANGHAI).date().isoformat()
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo:
            stamp = stamp.astimezone(SHANGHAI)
        return stamp.date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def positive_price(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and result > 0 else None
    except (TypeError, ValueError):
        return None


def history_series(reference, statistics, name):
    """Preserve price basis and sample counts for the reference-price merger."""
    definitions = [
        ("爱剑三报价均价", reference, "tradeTime", "price", "reference_quote", None),
        ("万宝楼在售均价", statistics, "countDate", "saleAvgPrice", "listing_mean", "saleAvgNum"),
        ("万宝楼上架均价", statistics, "countDate", "publicAvgPrice", "public_listing", "publicNum"),
        ("万宝楼成交均价", statistics, "countDate", "tradeAvgPrice", "transaction", "tradeAvgNum"),
    ]
    series = []
    for label, rows, date_key, price_key, kind, count_key in definitions:
        daily = {}
        for row in rows or []:
            if not isinstance(row, dict) or row.get("goodsName", name) != name:
                continue
            day, price = source_day(row.get(date_key)), positive_price(row.get(price_key))
            count = row.get(count_key) if count_key else None
            if count is not None and positive_price(count) is None:
                continue
            if day and price is not None:
                daily[day] = dict(date=day, value=price, count=count)
        if daily:
            series.append(dict(label=label, color="var(--cinnabar)", dash="",
                               kind=kind, provider="爱剑三", origin="万宝楼" if count_key else "爱剑三",
                               points=[point for _, point in sorted(daily.items())]))
    return series


def enrich_product(data, detail):
    """Add verified release facts while keeping the original full product image."""
    result = dict(data)
    for field, source in [("unbound_duration", "publishLimitTime"),
                          ("bound_duration", "limitTime"), ("unbound_limit", "publishNum")]:
        value = detail.get(source)
        if value not in (None, "") and not result.get(field):
            result[field] = str(value)
    if not result.get("retail") and positive_price(detail.get("priceNum")):
        result["retail"] = detail["priceNum"]
    if len(str(result.get("date") or "")) < 10:
        result["date"] = source_day(detail.get("publishTime")) or result.get("date", "")
    return result


class AiJX3MarketSource:
    def __init__(self, http, cache):
        self.cache = cache
        self.client = http
        self.slots = asyncio.Semaphore(4)

    async def close(self):
        pass

    async def _request(self, service, path, params):
        async def fetch():
            async with self.slots:
                result = await self.client.request_json('POST', f'https://www.aijx3.cn/api2/{service}{path}', json_body=params, timeout=7, retries=0, source='market-history')
                payload = result.data
                if not isinstance(payload, dict) or str(payload.get('code')) != '0': return None
                return payload.get('data')
        key = service + path + str(sorted(params.items()))
        return await self.cache.get_or_load('market-history', key, 600, fetch)

    async def get(self, name):
        """An optional source has a total time budget and never blocks the primary result."""
        try:
            async with asyncio.timeout(8.5):
                return await self.cache.get_or_load('market-history-result', name, 30, lambda: self._get(name))
        except Exception:
            # No provider errors or internal diagnostics enter the finished image.
            return {}

    async def detail(self, name):
        detail = await self._request("aijx3-wj", "/goods/getGoodsDetail", {"goodsName": name})
        if not isinstance(detail, dict) or detail.get("goodsName") != name:
            return {}
        return detail

    async def _get(self, name):
        async def statistics():
            detail = await self.detail(name)
            goods_id = detail.get("goodsId")
            if not str(goods_id or "").isdigit(): return detail, []
            rows = await self._request("aijx3-wblwg", "/goodsStatistics", {"goodsId": int(goods_id), "countType": 1})
            return detail, rows

        reference_task = asyncio.create_task(self._request("aijx3-wj", "/goods/getAvgGoodsPriceRecord", {"goodsName": name, "belongQf3": ""}))
        stats_task = asyncio.create_task(statistics())
        tasks = [reference_task, stats_task]
        try:
            done, pending = await asyncio.wait(tasks, timeout=8)
            reference = reference_task.result() if reference_task in done and not reference_task.exception() else []
            detail, stats = stats_task.result() if stats_task in done and not stats_task.exception() else ({}, [])
            return {"product": detail, "series": history_series(reference, stats, name)}
        finally:
            for task in tasks:
                if not task.done(): task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


class MarketArchive:
    """Retain dated observations so a provider outage cannot erase the timeline."""
    def __init__(self, folder):
        self.folder = Path(folder)
        self.lock = asyncio.Lock()
        seed = Path(__file__).resolve().parents[2] / 'data' / 'market_history_seed.json'
        self.seed = json.loads(seed.read_text()) if seed.is_file() else {}
        facts = seed.with_name('market_product_facts.json')
        self.products = json.loads(facts.read_text()) if facts.is_file() else {}

    async def merge(self, name, server, series):
        async with self.lock:
            return await asyncio.to_thread(self._merge, name, server, series)

    def _merge(self, name, server, series):
        path = self.folder / (hashlib.sha256((name + '\0' + server).encode()).hexdigest() + '.json')
        previous = json.loads(path.read_text())['series'] if path.is_file() else []
        merged = {}
        for item in [*self.seed.get(name, []), *previous, *series]:
            key = (item.get('provider', 'JX3API'), item.get('origin', ''), item.get('kind') or LEGACY_KINDS.get(item['label'], item['label']))
            if key not in merged: merged[key] = {**item, 'points': {}}
            for point in item.get('points', []):
                if source_day(point.get('date')) and positive_price(point.get('value')):
                    merged[key]['points'][point['date']] = point
        result = [{**item, 'points': [p for _, p in sorted(item['points'].items())]} for item in merged.values() if item['points']]
        if result:
            self.folder.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps({'name':name, 'server':server, 'series':result}, ensure_ascii=False, separators=(',', ':')))
            temp.replace(path)
        return result
