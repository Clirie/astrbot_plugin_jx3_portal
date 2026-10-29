import asyncio
from aiohttp import web
from jx3portal.cache import TTLCache
from jx3portal.http import HttpClient
from jx3portal.telemetry import Telemetry


def test_refresh_does_not_join_old_inflight_or_invalidate_other_namespace():
    async def run():
        cache=TTLCache();release=asyncio.Event();started=asyncio.Event()
        async def old(): started.set();await release.wait();return 'old'
        task=asyncio.create_task(cache.get_or_load('one','x',60,old));await started.wait()
        other=asyncio.create_task(cache.get_or_load('two','x',60,old));await asyncio.sleep(0)
        cache.clear('one')
        async def new(): return 'new'
        assert await cache.get_or_load('one','x',60,new)=='new'
        release.set();await asyncio.gather(task,other)
        assert cache.get('one','x')=='new' and cache.get('two','x')=='old'
        await cache.close()
    asyncio.run(run())


def test_image_downloads_cannot_starve_json_queries():
    async def run():
        release=asyncio.Event();started=asyncio.Event();active=0
        async def media(request):
            nonlocal active
            active+=1
            if active>=3:started.set()
            await release.wait();return web.Response(body=b'photo')
        async def query(request):return web.json_response({'ready':True})
        app=web.Application();app.router.add_get('/image',media);app.router.add_get('/query',query)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        base='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1]);http=HttpClient()
        tasks=[asyncio.create_task(http.request_bytes('GET',base+'/image')) for _ in range(6)]
        try:
            await started.wait();await asyncio.sleep(.03)
            result=await asyncio.wait_for(http.request_json('GET',base+'/query'),.4)
            assert result.data=={'ready':True} and not release.is_set()
        finally:
            release.set();await asyncio.gather(*tasks);await http.close();await runner.cleanup()
        assert http._session is None and http._media_session is None
    asyncio.run(run())


def test_command_timing_is_bounded_and_contains_no_chat_content():
    telemetry=Telemetry()
    for i in range(250):telemetry.record_command_duration('help',i)
    timings=telemetry.snapshot()['command_timings']['help:handler']
    assert timings=={'samples':200,'median_ms':150,'p95_ms':240,'max_ms':249}
    assert telemetry.logs()==[]
    telemetry.reset_stats();assert telemetry.snapshot()['command_timings']=={}


def test_render_burst_has_bound_but_duplicate_queries_share_one_job(tmp_path):
    import pytest
    from jx3portal.render import ImageRenderer, RenderError
    async def run():
        release=asyncio.Event();started=asyncio.Event();calls=0
        async def render(*args):
            nonlocal calls
            calls+=1;started.set();await release.wait();return '/tmp/test.jpg'
        renderer=ImageRenderer(render)
        renderer.build_html=lambda page_id: '<p>{{ title }}</p>'
        tasks=[asyncio.create_task(renderer.render('game_records',{'title':str(i)})) for i in range(16)]
        await started.wait()
        async with asyncio.timeout(2):
            while renderer._pending<16:await asyncio.sleep(0)
        with pytest.raises(RenderError,match='出图的人较多'):
            await renderer.render('game_records',{'title':'overflow'})
        duplicates=[asyncio.create_task(renderer.render('game_records',{'title':'0'})) for _ in range(100)]
        await asyncio.sleep(0);release.set();await asyncio.gather(*tasks,*duplicates)
        assert calls==16 and renderer._pending==0
        await renderer.close()
    asyncio.run(run())


def test_market_prefetch_is_owned_coalesced_and_cancelled():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from jx3portal.game.market import MarketService
    async def run():
        service=object.__new__(MarketService);service._history_tasks={};service.choices=SimpleNamespace(close=lambda:None)
        started=asyncio.Event();cancelled=asyncio.Event()
        async def fetch(name):
            started.set()
            try:await asyncio.Event().wait()
            finally:cancelled.set()
        service.history=SimpleNamespace(get=AsyncMock(side_effect=fetch))
        service.prefetch_history('挂宠·小霜');service.prefetch_history('挂宠·小霜');await started.wait()
        assert service.history.get.await_count==1
        await service.close();assert cancelled.is_set() and not service._history_tasks
    asyncio.run(run())


def test_fresh_card_burst_coalesces_without_returning_old_data(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from jx3portal.jx3api import JX3APIClient
    from jx3portal.settings import Settings
    async def run():
        cache=TTLCache();started=asyncio.Event();release=asyncio.Event();calls=0
        async def fetch(*args,**kwargs):
            nonlocal calls
            calls+=1;started.set();await release.wait();return SimpleNamespace(data={'code':200,'data':{'likes':calls}})
        http=SimpleNamespace(request_json=AsyncMock(side_effect=fetch));api=JX3APIClient(Settings({},tmp_path),http,cache,Telemetry())
        tasks=[asyncio.create_task(api.request('/card/record',{'name':'甲','server':'梦江南'},auth='none',use_cache=False)) for _ in range(100)]
        await started.wait();await asyncio.sleep(.01);release.set();result=await asyncio.gather(*tasks)
        assert calls==1 and all(row['likes']==1 for row in result)
        assert (await api.request('/card/record',{'name':'甲','server':'梦江南'},auth='none',use_cache=False))['likes']==2
        await asyncio.gather(*(api.request('/card/random',auth='none',use_cache=False) for _ in range(2)))
        assert calls==4
        await cache.close()
    asyncio.run(run())
