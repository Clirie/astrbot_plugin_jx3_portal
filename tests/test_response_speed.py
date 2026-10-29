import ast
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from aiohttp import web
from jinja2 import Environment
from jx3portal.local_render import LocalRenderService
from jx3portal.render import ImageRenderer
from jx3portal.game.data import GameData
from jx3portal.settings import Settings
from jx3portal.commands import ImageReply, MessageParts
from test_flows import service, event


def test_static_template_keeps_data_escaped_and_cache_fresh(tmp_path):
    async def run():
        source=tmp_path/'source.jpg';source.write_bytes(b'image')
        callback=AsyncMock(return_value=str(source));renderer=ImageRenderer(callback,tmp_path/'images',asset_origin='http://127.0.0.1:8999/static/')
        data={'title':'<img src=x onerror=alert(1)>','rows':[['角色甲','100']], 'columns':['角色','分数'],'update_time':'2026-10-26 12:00'}
        first=await renderer.render('game_records',dict(data,data_time='12:01'))
        template,payload,options=callback.call_args.args
        rendered=Environment(autoescape=False).from_string(template).render(**payload)
        assert data['title'] not in rendered and '&lt;img src=x onerror=alert(1)&gt;' in rendered
        assert data['title'] not in template and payload['title']==data['title']
        assert await renderer.render('game_records',dict(data,data_time='12:02'))==first and callback.await_count==1
        await renderer.render('game_records',dict(data,update_time='2026-10-26 13:00'))
        assert callback.await_count==2 and callback.call_args.args[0]==template
        os.utime(first,(1,1));renderer.cache.clear()
        await renderer.render('game_records',data)
        assert callback.await_count==3
        assert "RecordBrush;src:url('http://127.0.0.1:8999/static/assets/ink/Yuwei.woff2?v=" in template
        assert len(template)<50000 and 'data:font' not in template
        await renderer.close()
    asyncio.run(run())


def test_generated_display_clock_does_not_change_same_data(tmp_path):
    async def run():
        api=SimpleNamespace(request=AsyncMock(return_value=[{'name':'门派','count':1}]))
        game=GameData(api,Settings({},tmp_path))
        with patch('jx3portal.game.data.datetime') as clock:
            clock.now.return_value.strftime.side_effect=['12:00:00','12:00:02']
            first=await game.mingjiantongji('33');second=await game.mingjiantongji('33')
        assert first['data']==second['data']
        api.request.return_value={'data':[],'time':1793000000}
        first=await game.kuafumingjian('唯我独尊')
        api.request.return_value={'data':[],'time':1793000060}
        second=await game.kuafumingjian('唯我独尊')
        assert first['data']['update_time'] and first['data']['update_time']!=second['data']['update_time']
        await game.close()
    asyncio.run(run())


def test_update_query_without_push_credentials_and_image_failure(tmp_path):
    async def run():
        commands=service(tmp_path)
        commands.api.announce=AsyncMock(return_value=[{'title':'版本更新公告','date':'2026-10-26','url':'https://jx3.xoyo.com/article'}])
        commands.articles=SimpleNamespace(from_announcement=AsyncMock(return_value=['/tmp/one.jpg']))
        reply=await commands.run('announce',event('更新'),'')
        assert isinstance(reply,ImageReply) and reply.path=='/tmp/one.jpg' and not reply.extra_paths
        assert 'https://jx3.xoyo.com/article' in reply.caption
        commands.api.announce.assert_awaited_once_with(3)
        commands.articles.from_announcement.assert_awaited_once()
        commands.reset_runtime();commands.articles.from_announcement.side_effect=RuntimeError('render failed')
        assert '版本更新公告' in await commands.run('announce',event('更新'),'')
        commands.reset_runtime();commands.articles.from_announcement.reset_mock()
        assert '版本更新公告' in await commands.run('announce',event('更新 3'),'3')
        commands.articles.from_announcement.assert_not_awaited()
    asyncio.run(run())


def test_loopback_static_handler_rejects_traversal_and_nonassets(tmp_path):
    # Load this pure HTTP handler without requiring a local Chromium installation.
    module=ast.parse((Path(__file__).parents[1]/'jx3portal/render_worker.py').read_text())
    handler=next(n for n in module.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='handle_static')
    namespace={'web':web,'TEMPLATE_ROOT':tmp_path/'templates'}
    exec(compile(ast.Module(body=[handler],type_ignores=[]),'<static handler>','exec'),namespace)
    namespace['TEMPLATE_ROOT'].mkdir();(tmp_path/'templates/font.woff2').write_bytes(b'font');(tmp_path/'private.jpg').write_bytes(b'private');(tmp_path/'templates/private.py').write_text('secret')
    (tmp_path/'templates/link.jpg').symlink_to(tmp_path/'private.jpg')
    async def run():
        response=await namespace['handle_static'](SimpleNamespace(remote='127.0.0.1',match_info={'path':'font.woff2'}))
        assert response.headers['Content-Type']=='font/woff2' and response.headers['Access-Control-Allow-Origin']=='*'
        for path in ['../private.jpg','private.py','link.jpg','missing.jpg']:
            with pytest.raises(web.HTTPNotFound):await namespace['handle_static'](SimpleNamespace(remote='127.0.0.1',match_info={'path':path}))
        with pytest.raises(web.HTTPForbidden):await namespace['handle_static'](SimpleNamespace(remote='192.0.2.1',match_info={'path':'font.woff2'}))
    asyncio.run(run())


def test_local_client_template_reference_recovers_after_worker_cache_eviction(tmp_path):
    async def run():
        requests=[];known=False
        async def generate(request):
            nonlocal known
            data=await request.json();requests.append(data)
            if 'tmpl_id' in data and not known:return web.json_response({'code':2},status=409)
            known=True
            return web.Response(body=b'image',content_type='image/jpeg',headers={'X-T2I-Template-Id':'abc'})
        app=web.Application();app.router.add_post('/generate',generate);runner=web.AppRunner(app);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start();url='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])+'/generate'
        local=LocalRenderService(tmp_path)
        async with aiohttp.ClientSession() as session:
            local.session=SimpleNamespace(post=lambda ignored,**kwargs:session.post(url,**kwargs))
            for role in ['甲','乙','丙']:
                if role=='丙':known=False
                path=await local.render('{{name}}',{'name':role},{})
                assert Path(path).read_bytes()==b'image'
        await runner.cleanup()
        assert len(requests)==4
        assert 'tmpl' in requests[0] and 'tmpl_id' in requests[1]
        assert requests[1]['tmpldata']=={'name':'乙'}
        assert 'tmpl_id' in requests[2] and requests[3]['tmpl']=='{{name}}'
        assert requests[3]['tmpldata']=={'name':'丙'}
    asyncio.run(run())


def test_main_routes_local_images_without_markdown_preprocessing():
    module=ast.parse((Path(__file__).parents[1]/'main.py').read_text())
    cls=next(n for n in module.body if isinstance(n,ast.ClassDef) and n.name=='JX3PortalPlugin')
    methods=[n for n in cls.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in {'_render_endpoint','_asset_origin','_render_html'}]
    from urllib.parse import urlsplit
    namespace={'urlsplit':urlsplit,'RenderError':RuntimeError,'Any':object}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name='Adapter',bases=[],keywords=[],body=methods,decorator_list=[])],type_ignores=[])),'<render adapter>','exec'),namespace)
    adapter=namespace['Adapter']();config={'t2i_endpoint':'http://localhost:8999/text2img'}
    adapter.context=SimpleNamespace(get_config=lambda:config,html_renderer=SimpleNamespace(network_strategy=SimpleNamespace(BASE_RENDER_URL='https://external.example')))
    adapter.local_render=SimpleNamespace(ensure=AsyncMock(),render=AsyncMock(return_value='/tmp/local.jpg'))
    adapter.html_render=AsyncMock(return_value='/tmp/external.jpg')
    async def run():
        assert adapter._asset_origin()=='http://127.0.0.1:8999/static/'
        assert await adapter._render_html('{{name}}',{'name':'甲'},{})=='/tmp/local.jpg'
        adapter.html_render.assert_not_awaited()
        config['t2i_endpoint']='https://external.example/text2img'
        assert adapter._asset_origin()==''
        assert await adapter._render_html('{{name}}',{'name':'乙'},{})=='/tmp/external.jpg'
        adapter.html_render.assert_awaited_once()
    asyncio.run(run())
