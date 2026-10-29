import asyncio
from types import SimpleNamespace
from aiohttp import web
from jx3portal.cache import TTLCache
from jx3portal.http import HttpClient
from jx3portal.game.market_sources import AiJX3MarketSource


def test_market_json_transport_and_cache():
    async def run():
        requests=[]
        async def handler(request):
            assert request.content_type=='application/json'
            body=await request.json();requests.append((request.path,body))
            if request.path.endswith('getGoodsDetail'):data={'goodsName':'测试','goodsId':'123'}
            elif request.path.endswith('goodsStatistics'):data=[{'countDate':'2026-10-27','saleAvgPrice':200,'saleAvgNum':3}]
            else:data=[{'goodsName':'测试','tradeTime':'2026-10-26','price':190}]
            return web.json_response({'code':'0','data':data})
        app=web.Application();app.router.add_post('/{path:.*}',handler)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        http=HttpClient();request=http.request_json
        async def local(method,url,**kwargs):
            return await request(method,url.replace('https://www.aijx3.cn',f'http://127.0.0.1:{port}'),**kwargs)
        http.request_json=local;source=AiJX3MarketSource(http,TTLCache())
        try:
            result=await source.get('测试')
            assert len(result['series'])==2
            assert {s['provider'] for s in result['series']}=={'爱剑三'}
            assert result['series'][1]['points'][0]['value']==200
            assert await source.get('测试')==result
            assert len(requests)==3
            assert requests[-1][1]=={'goodsId':123,'countType':1}
        finally:
            await http.close();await runner.cleanup()
    asyncio.run(run())
