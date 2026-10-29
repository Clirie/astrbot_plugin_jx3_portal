import asyncio
from copy import deepcopy
from .tarot import tarot_reading,TarotDeck
from .daily_tarot import load_secret, daily_card
from .fortune import LoveBook, love_reading, fortune_reading
from .birth_chart import ziwei_reading
from .horoscope import HoroscopeService
from ..replies import ImageReply

class ExistingPlay:
    def __init__(self, game):
        self.game = game
        self.book = LoveBook(library_name='love_answers')
        self.deck = TarotDeck()
        self.horoscope = HoroscopeService(self.session)
        self.secret = None

    async def session(self): return self.game.api.http._get_session()

    async def daily(self, event):
        if self.secret is None: self.secret = await asyncio.to_thread(load_secret, self.game.settings.data_dir)
        platform = event.get_platform_name() if hasattr(event,'get_platform_name') else str(event.unified_msg_origin).split(':',1)[0]
        owner = str(platform) + '\0' + str(event.get_sender_id())
        return await asyncio.to_thread(daily_card, owner, self.secret)

    async def run(self, key, args, event):
        if key == 'tarot': result = await tarot_reading(args,1,self.deck,self.game.local.bindings.owner(event))
        elif key == 'tarot_three': result = await tarot_reading(args,3,self.deck,self.game.local.bindings.owner(event))
        elif key == 'fortune': result = await fortune_reading(args)
        elif key == 'ziwei': result = await ziwei_reading(args)
        elif key == 'love': result = await love_reading(self.book,args,self.game.local.bindings.owner(event))
        elif key == 'tarot_daily':
            draw = await self.daily(event)
            result = {'code':200,'temp':'tarot','data':{'cards':[draw['card']],'date':draw['date'],'question':'','daily':True}}
        elif key == 'horoscope':
            result = deepcopy(await self.horoscope.reading(args))
            if result['code'] == 200:
                draw = await self.daily(event)
                result['data']['daily_card'] = draw['card']
        else: raise KeyError(key)
        if result['code'] != 200: return result.get('msg') or '暂时没有结果。'
        width = 1200 if key in {'horoscope','ziwei'} else 960
        return ImageReply(await self.game.renderer.render(result['temp'],result['data'],options={'width':width},use_cache=key in {'horoscope','tarot_daily'}))
