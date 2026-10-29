import asyncio
from ..replies import ImageReply, PendingReply
from ..buttons import Button, MenuReply
from .market_choices import MarketChoices, build_menu, normalize_query, canonical_name
from .market_sources import AiJX3MarketSource, enrich_product
from .market_design import make_fused_chart
from .market_card import market_card
from ..jx3api import JX3APIError
from ..http import HttpError

class MarketService:
    def __init__(self, game, http, cache):
        self.game = game
        self.choices = MarketChoices()
        self._history_tasks = {}
        self.history = AiJX3MarketSource(http, cache)
        from .market_sources import MarketArchive
        self.archive = MarketArchive(game.settings.data_dir / "market-history")

    async def close(self):
        self.choices.close()
        tasks=list(self._history_tasks.values())
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._history_tasks.clear()

    def prefetch_history(self, name):
        if name in self._history_tasks or len(self._history_tasks) >= 4: return
        task=asyncio.create_task(self.history.get(name))
        self._history_tasks[name]=task
        def finished(done):
            if self._history_tasks.get(name) is done: self._history_tasks.pop(name,None)
            if not done.cancelled(): done.exception()
        task.add_done_callback(finished)

    async def query(self, query, server, event, text_only=False):
        name = normalize_query(query)
        words = name.split()
        state = self.choices.start(event, {}, server)
        try:
            async with asyncio.timeout(4): items = await self.game.api.request('/trade/item/search', {'name': words[0]})
        except (TimeoutError, JX3APIError, HttpError): items = []
        if state is not None and not self.choices.current(event, state, 0): return None
        options = build_menu(items, name, words[1:]) if isinstance(items, list) else {}
        if (items or len(words)>1) and not options: return '没有找到匹配的款式，请试试完整外观名。'
        selected = canonical_name(options['1']) if options else name
        if not text_only: self.prefetch_history(selected)
        related = {str(i):label for i,label in enumerate(list(options.values())[1:],1)}
        if state is not None:
            state.options = related
            state.text_only = text_only
        async def detail():
            try:
                async with asyncio.timeout(1.5): return await self.history.detail(selected)
            except (TimeoutError, HttpError): return {}
        data, extra = await asyncio.gather(self.game.api.trade_records(selected, server), detail())
        if state is not None and not self.choices.current(event, state, 0): return None
        if not isinstance(data,dict) or not data.get('name'): return '没有找到这个外观。'
        if options and data['name'] != selected: return '暂时没有查到这款外观的价格，请换一款或稍后重试。'
        product = enrich_product(data, {**self.archive.products.get(data['name'], {}), **(extra if isinstance(extra,dict) else {})})
        text = market_card(product, related)
        async def load():
            if text_only or (state and not self.choices.current(event, state, 0)): return None
            result = await self.image(data['name'], server, strict=True, data=product)
            return result if state is None or self.choices.current(event, state, 0) else None
        buttons = tuple(Button(canonical_name(label).split('·',1)[-1], '换款 ' + canonical_name(label) + (' ' + server if server else '')) for label in related.values())
        menu = MenuReply(market_card(product, {}).replace('当前查询：', '默认查询：') + '\n\n相关外观', buttons, str(event.get_sender_id())) if buttons else None
        return PendingReply(text, load, lambda: self.choices.arm(event, state), menu=menu)

    async def select(self, args, event):
        state = self.choices.active(event)
        if not state: return '款式选择已过期，请重新发送「物价 外观名」。'
        if args not in state.options: return '请选择列表中的序号。'
        state.revision += 1
        revision = state.revision
        result = await self.image(canonical_name(state.options[args]), state.server, strict=True, text_only=state.text_only)
        return result if self.choices.current(event, state, revision) else None

    async def image(self, name, server, text_only=False, strict=False, data=None):
        if data is None: data = await self.game.api.trade_records(name, server)
        if not isinstance(data, dict) or not data.get('name'): return '没有找到这个外观。'
        if strict and data['name'] != name: return '暂时没有查到这款外观的价格，请换一款或稍后重试。'
        if text_only: return market_card(enrich_product(data, self.archive.products.get(data['name'], {})), {})
        extra = await self.history.get(data['name'])
        product = enrich_product(data, {**self.archive.products.get(data['name'], {}), **(extra.get('product') or {})})
        context = self.game.data._market_render_data(product)
        series = context.pop('_history_series', [])
        series = await self.archive.merge(data['name'], server, [*(extra.get('series') or []), *series])
        context['trend'] = make_fused_chart(series)
        # 报价只取近期，长期曲线在截取前计算。
        for market in context['markets']: market['rows'] = market['rows'][-10:]
        return ImageReply(await self.game.renderer.render('hangqing', context))
