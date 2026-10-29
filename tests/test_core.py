import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from jinja2 import Environment
from jx3portal.cache import TTLCache
from jx3portal.http import HttpClient, NetworkError, HTTPStatusError, HttpError
from jx3portal.jx3api import JX3APIClient
from jx3portal.jx3box import JX3BOXClient
from jx3portal.telemetry import Telemetry
from jx3portal.settings import Settings
from jx3portal.commands import CommandService, ImageReply
from jx3portal.render import ImageRenderer, price_context, daily_context, qiyu_context, RenderError
from jx3portal.format import calendar, help_text, split_message
from jx3portal.articles import clean_article, paginate, official_url, article_data
from jx3portal.online import parse_online


def test_http_pool_retry_limits_and_post():
    async def run():
        transports, counts = set(), {}
        async def handle(request):
            key = request.path
            counts[key] = counts.get(key, 0) + 1
            transports.add(id(request.transport))
            if key == '/slow':
                await asyncio.sleep(.5)
            if key == '/bad' or (key == '/retry' and counts[key] == 1):
                return web.Response(status=503, text='unavailable')
            if key == '/large':
                return web.Response(body=b'x'*1024)
            return web.json_response({'ok': True})
        app = web.Application(); app.router.add_route('*','/{name}',handle)
        runner = web.AppRunner(app); await runner.setup()
        site = web.TCPSite(runner,'127.0.0.1',0); await site.start()
        base = 'http://127.0.0.1:' + str(site._server.sockets[0].getsockname()[1])
        http = HttpClient()
        try:
            await http.request_json('GET',base+'/ok'); await http.request_json('GET',base+'/ok')
            assert len(transports) == 1
            await http.request_json('GET',base+'/retry',retries=1)
            assert counts['/retry'] == 2
            with pytest.raises(HTTPStatusError):
                await http.request_json('POST',base+'/bad',retries=5)
            assert counts['/bad'] == 1
            start=time.monotonic()
            with pytest.raises(NetworkError):
                await http.request_json('GET',base+'/slow',timeout=.12,retries=5)
            assert time.monotonic()-start < .35
            with pytest.raises(HttpError):
                await http.request_json('GET',base+'/large',max_bytes=100)
        finally:
            await http.close(); await runner.cleanup()
        assert http._session is None
    asyncio.run(run())


def test_cache_coalesces_and_isolates_data():
    async def run():
        cache=TTLCache(); calls=0
        async def load():
            nonlocal calls
            calls+=1; await asyncio.sleep(.03); return {'items':[1]}
        rows=await asyncio.gather(*(cache.get_or_load('api','same',60,load) for _ in range(12)))
        assert calls==1
        rows[0]['items'].append(99)
        assert rows[1]['items']==[1] and cache.get('api','same')=={'items':[1]}
        await cache.get_or_load('api','same',0,load)
        assert calls==2
        await cache.close()
    asyncio.run(run())


def test_cancelled_waiter_does_not_cancel_other_waiter():
    async def run():
        cache=TTLCache(); started=asyncio.Event()
        async def load():
            started.set(); await asyncio.sleep(.03); return {'ok':True}
        first=asyncio.create_task(cache.get_or_load('api','same',60,load))
        await started.wait(); second=asyncio.create_task(cache.get_or_load('api','same',60,load))
        first.cancel()
        with pytest.raises(asyncio.CancelledError): await first
        assert await second=={'ok':True}
        await cache.close()
    asyncio.run(run())


def test_failures_not_cached_and_clear_during_request():
    async def run():
        cache=TTLCache(); calls=0
        async def broken():
            nonlocal calls
            calls+=1; raise ValueError('failed')
        for _ in range(2):
            with pytest.raises(ValueError): await cache.get_or_load('api','x',20,broken)
        assert calls==2
        start=asyncio.Event(); finish=asyncio.Event()
        async def slow(): start.set(); await finish.wait(); return 10
        pending=asyncio.create_task(cache.get_or_load('api','x',20,slow))
        await start.wait(); cache.clear(); finish.set(); await pending
        assert cache.get('api','x') is None
    asyncio.run(run())


def test_api_burst_one_request_and_auth_isolation(tmp_path):
    async def run():
        settings=Settings({'jx3api_token':'first'},tmp_path)
        http=SimpleNamespace(request_json=AsyncMock(return_value=SimpleNamespace(data={'code':200,'data':{'value':1}})))
        api=JX3APIClient(settings,http,TTLCache(),Telemetry())
        await asyncio.gather(*(api.request('/role/detail',{'server':'唯我独尊','name':'刀剑笑我'}) for _ in range(10)))
        assert http.request_json.await_count==1
        settings._config['jx3api_token']='second'
        await api.request('/role/detail',{'server':'唯我独尊','name':'刀剑笑我'})
        assert http.request_json.await_count==2
        assert http.request_json.call_args.kwargs['params']['token']=='second'
    asyncio.run(run())


def test_help_template_and_no_debug_info():
    renderer=ImageRenderer()
    text=Environment(autoescape=True).from_string(renderer.build_html('help_dynamic')).render(categories=[{'name':'角色','items':[{'name':'奇遇','usage':'奇遇 服务器 角色名','arguments':'服务器 角色名'}]}],default_server='')
    assert '奇遇' in text and '服务器 角色名' in text
    assert all(word not in text for word in ['Token 已配置','Ticket 已配置','后台：','绑定区服后'])
    with pytest.raises(RenderError): renderer.build_html('../main')


def test_renderer_cache_singleflight_restart_and_data_changes(tmp_path):
    async def run():
        source=tmp_path/'source.jpg'; source.write_bytes(b'jpeg-test')
        callback=AsyncMock(return_value=str(source))
        data={'categories':[{'name':'日常','items':[{'name':'日常','usage':'日常'}]}]}
        renderer=ImageRenderer(callback,tmp_path/'cache')
        paths=await asyncio.gather(*(renderer.render('help_dynamic',data) for _ in range(5)))
        assert callback.await_count==1 and len(set(paths))==1
        assert callback.call_args.args[1]['categories']==data['categories']
        original_template=callback.call_args.args[0]
        restarted=ImageRenderer(callback,tmp_path/'cache')
        assert await restarted.render('help_dynamic',data)==paths[0]
        assert callback.await_count==1
        changed={**data,'default_server':'唯我独尊'}
        await restarted.render('help_dynamic',changed)
        assert callback.await_count==2
        assert callback.call_args.args[0]==original_template
        await renderer.close(); await restarted.close()
    asyncio.run(run())


def test_all_calendar_dates_survive():
    rows=[{'date':f'2026-10-{day}','war':'天龙寺','battle':'西风古道'} for day in range(23,30)]
    data={'today':{'date':'2026-10-26'},'total':rows}
    context=daily_context(data)
    assert len(context['items'])==7 and context['today']['war']=='天龙寺'
    assert all(row['date'] in calendar(data) for row in rows)


def test_price_districts_statuses_and_full_history():
    data={'name':'外观','list':[{'name':'电信区','list':[
        {'date':'2023-01-01','sale':3,'value':200,'server':'唯我独尊'},
        {'date':'2026-10-26','sale':3,'value':300,'server':'唯我独尊'},
        {'date':'2026-10-26','sale':4,'value':999,'server':'唯我独尊'},
        {'date':'2026-10-25','sale':5,'value':280,'server':'唯我独尊'}]}]}
    context=price_context(data)
    assert len(context['players'])==4
    assert {row['kind'] for row in context['players']}=={'sell','buy','done'}
    assert '2023.01.01' in context['trend']['period']
    assert '>200<' in context['trend']['svg'] and '>300<' in context['trend']['svg'] and '>999<' not in context['trend']['svg']
    assert 'fill="#607f87"' in context['trend']['svg']
    assert price_context(data,server='梦江南')['players']==[]


def test_qiyu_pet_and_unknown_date():
    data=[{'event':'流年如虹','level':2,'time':1790000000},{'event':'猫','level':0,'time':1790000000},{'event':'平生心愿','level':1,'time':0},{'event':'旧宴承欢','level':1,'time':'未知'}]
    context=qiyu_context(data,server='唯我独尊',name='刀剑笑我')
    assert len(context['jsqy'])==1 and len(context['ptqy'])==2
    assert all(row['time']=='' for row in context['ptqy'])


def test_article_sanitization_pagination_and_identity():
    content='<script>alert(1)</script><p onclick="x()">正文</p><img src="https://jx3.xoyo.com/a.jpg" onerror="x()"><img src="http://127.0.0.1/private">'
    blocks=clean_article(content,'https://jx3.xoyo.com/show-1.html'); text=''.join(blocks)
    assert '正文' in text and 'a.jpg' in text
    assert all(word not in text for word in ['script','onclick','onerror','127.0.0.1'])
    pages=paginate(['<p>'+str(i)+'文'*500+'</p>' for i in range(6)],limit=1000)
    assert len(pages)==6 and ''.join(pages).count('文')==3000
    assert official_url('https://jx3.xoyo.com/show-1.html')
    assert not official_url('https://jx3.xoyo.com.evil.test/a')
    assert article_data({'desc':{'title':'公告','content':'内容','url':'https://jx3.xoyo.com/a'}})['title']=='公告'


@pytest.mark.parametrize('raw,expected',[(True,True),(False,False),(1,True),(0,False),('true',True),('false',False),('未知',None),(None,None)])
def test_online_never_infers_from_card(raw,expected):
    assert parse_online({'code':0,'data':[{'gameLogin':raw,'showActive':True}]}) is expected


def test_reply_splitting_keeps_last_complete_part():
    text='a'*30
    parts=split_message(text,limit=10,max_parts=3)
    assert ''.join(parts)==text


def test_image_stream_stops_after_decodable_frame():
    async def run():
        import io
        from PIL import Image
        encoded=io.BytesIO();Image.new('RGB',(100,100),'red').save(encoded,format='GIF')
        first=encoded.getvalue()+b'\0'*(140*1024);released=asyncio.Event()
        async def stream(request):
            response=web.StreamResponse(headers={'Content-Type':'image/gif'});await response.prepare(request)
            await response.write(first);await released.wait()
            try:await response.write(b'\0'*(1024*1024));await response.write_eof()
            except ConnectionResetError:pass
            return response
        app=web.Application();app.router.add_get('/animation.gif',stream)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        http=HttpClient()
        try:
            port=site._server.sockets[0].getsockname()[1]
            result=await http.request_image(f'http://127.0.0.1:{port}/animation.gif',timeout=5)
            assert result.bytes < 200*1024
            with Image.open(io.BytesIO(result.data)) as decoded:assert decoded.size==(100,100)
        finally:released.set();await http.close();await runner.cleanup()
    asyncio.run(run())
