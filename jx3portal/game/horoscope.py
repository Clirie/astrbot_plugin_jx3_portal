"""Dated source pages, shared 30-minute cache, and a twelve-sign overview."""
import asyncio
import hashlib
import json
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import aiohttp
from bs4 import BeautifulSoup
from opencc import OpenCC
from .data import load_template

CONVERTER=OpenCC("t2s")

SIGNS = dict(zip(('白羊座','金牛座','双子座','巨蟹座','狮子座','处女座','天秤座','天蝎座','射手座','摩羯座','水瓶座','双鱼座'), ('aries','taurus','gemini','cancer','leo','virgo','libra','scorpio','sagittarius','capricorn','aquarius','pisces')))
USAGE = '用法：今日运势 星座名\n例如：今日运势 水瓶座'


def parse_sign(text):
    text = str(text).strip().lower()
    return next((key for name,key in SIGNS.items() if text in (name,name[:-1],key)),None)


def normalize_page(source, sign, day):
    page=BeautifulSoup(source,'html.parser');index=list(SIGNS.values()).index(sign)
    selected=page.select_one('select[name="iAcDay"] option[selected]');identity=page.select_one('input[name="iAstro"]')
    if selected is None or selected.get('value')!=day.isoformat():raise ValueError('wrong page date')
    if identity is None or identity.get('value')!=str(index):raise ValueError('wrong page sign')
    body=page.select_one('.TODAY_CONTENT');name=list(SIGNS)[index]
    source_name=('牡羊座','金牛座','雙子座','巨蟹座','獅子座','處女座','天秤座','天蠍座','射手座','摩羯座','水瓶座','雙魚座')[index]
    if body is None or body.h3 is None or body.h3.get_text(strip=True)!='今日'+source_name+'解析':raise ValueError('wrong reading sign')
    sections=[]
    for key,label,css in [('all','综合','.txt_green'),('love','感情','.txt_pink'),('work','事业','.txt_blue'),('money','财富','.txt_orange')]:
        heading=body.select_one(css)
        if heading is None:raise ValueError('missing score')
        rating=heading.get_text(strip=True);stars=re.search(r'([★☆]{5})',rating)
        paragraph=heading.parent.find_next_sibling('p')
        text=paragraph.get_text(' ',strip=True) if paragraph else ''
        if not stars or not text or len(text)>800 or '�' in text:raise ValueError('invalid reading')
        sections.append({'key':key,'label':label,'text':CONVERTER.convert(text),'score':stars[1].count('★')})
    comment=page.select_one('.TODAY_WORD p');lucky=[]
    for css,label in [('title02','幸运色'),('title01','幸运数字'),('title05','速配星座')]:
        image=page.select_one('.TODAY_LUCKY img[src*="'+css+'"]')
        value=image.parent.find('h4') if image else None
        if value:lucky.append({'label':label,'value':CONVERTER.convert(value.get_text(strip=True))})
    result={'name':name,'sign':sign,'date':day.strftime('%Y.%m.%d'),'comment':CONVERTER.convert(comment.get_text(strip=True)) if comment else '', 'overview':sections[0],'sections':sections[1:],'lucky':lucky,'scale':5,'source':'科技紫微网','source_url':f'https://astro.click108.com.tw/daily_{index}.php?iAcDay={day.isoformat()}&iAstro={index}'}
    result['content_hash']=hashlib.sha256(json.dumps({'sections':sections,'lucky':lucky},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return result


class HoroscopeService:
    def __init__(self, session_factory, clock=time.monotonic, today=None):
        self.session_factory=session_factory;self.clock=clock
        self.today=today or (lambda:datetime.now(ZoneInfo('Asia/Shanghai')).date())
        self.cache={};self.failures={};self.locks={sign:asyncio.Lock() for sign in SIGNS.values()};self.requests=asyncio.Semaphore(4)

    async def _fetch(self, sign, day):
        session=await self.session_factory()
        index=list(SIGNS.values()).index(sign)
        url=f'https://astro.click108.com.tw/daily_{index}.php?iAcDay={day.isoformat()}&iAstro={index}'
        async with self.requests, asyncio.timeout(8):
            async with session.get(url,headers={'User-Agent':'Mozilla/5.0'},allow_redirects=False) as response:
                if response.status!=200:raise ValueError('dated page unavailable')
                blob=bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    blob.extend(chunk)
                    if len(blob)>262144:raise ValueError('oversized page')
                return bytes(blob).decode('utf-8-sig',errors='replace')

    async def data(self, sign):
        async with self.locks[sign]:
            day=self.today();cached=self.cache.get(sign);now=self.clock()
            if cached and cached[0]==day and now-cached[1]<1800:return cached[2]
            if self.failures.get(sign,('',0))[0]==day and self.failures[sign][1]>now:return None
            try:
                data=normalize_page(await self._fetch(sign,day),sign,day)
                if self.today()!=day:return None
            except (ValueError,TimeoutError,aiohttp.ClientError):
                self.failures[sign]=(day,self.clock()+30);return None
            self.cache[sign]=(day,self.clock(),data);self.failures.pop(sign,None)
            return data

    async def reading(self, text=''):
        text=str(text).strip();sign=parse_sign(text)
        if text and not sign:return {'code':0,'msg':USAGE,'data':{},'temp':''}
        day=self.today()
        if sign:
            data=await self.data(sign)
            if data is None or self.today()!=day:return self.unavailable()
            return {'code':200,'msg':'ok','data':data,'temp':await load_template('horoscope.html')}
        rows=await asyncio.gather(*(self.data(key) for key in SIGNS.values()))
        if self.today()!=day:return self.unavailable()
        if not any(rows):return self.unavailable()
        rows=[row or {'name':name,'sign':key,'unavailable':True} for (name,key),row in zip(SIGNS.items(),rows)]
        return {'code':200,'msg':'ok','data':{'date':day.strftime('%Y.%m.%d'),'signs':rows,'missing':sum(bool(row.get('unavailable')) for row in rows),'scale':5,'source':'科技紫微网'},'temp':await load_template('horoscope_overview.html')}

    @staticmethod
    def unavailable():
        return {'code':0,'msg':'当天运势暂未更新，请稍后再试。','data':{},'temp':''}
