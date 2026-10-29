from jx3portal.buttons import MenuReply, send_menu
import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from jx3portal.settings import Settings
from jx3portal.commands import CommandService, ImageReply, COMMANDS
from jx3portal.cache import TTLCache
from jx3portal.telemetry import Telemetry
from jx3portal.event_push import EventPushService
from jx3portal.jx3box import JX3BOXClient


def service(tmp_path):
    settings=Settings({'jx3api_token':'test','default_server':'唯我独尊'},tmp_path)
    api=SimpleNamespace(sand=AsyncMock(return_value={'server':'唯我独尊','data':[]}), role_detail=AsyncMock(return_value={}))
    renderer=SimpleNamespace(available=True,sand=AsyncMock(return_value='/tmp/sand.jpg'))
    return CommandService(settings,api,SimpleNamespace(),None,TTLCache(),Telemetry(),renderer=renderer)


def event(text='沙盘'):
    return SimpleNamespace(message_str=text,message_obj=SimpleNamespace(message_str=text,sender=SimpleNamespace(role='member')),unified_msg_origin='test:GroupMessage:1',get_sender_id=lambda:'tester',is_admin=lambda:False)


def test_defaults_help_and_retry_usage(tmp_path):
    async def run():
        commands=service(tmp_path)
        output=await commands.run('sand',event(),'唯我独尊')
        assert isinstance(output,ImageReply) and output.path=='/tmp/sand.jpg'
        commands.reset_runtime()
        assert isinstance(await commands.run('sand',event(),'唯我独尊 文字'),str)
        assert commands.renderer.sand.await_count==1
        first=await commands.run('role',event(),'')
        assert first.startswith('用法：')
        assert '秒后' not in await commands.run('role',event(),'唯我独尊 刀剑笑我')
        names=[item['name'] for group in commands._help_categories(event()) for item in group['items']]
        assert all(name not in names for name in ['诊断','推栏票据','生图','激活','在线'])
    asyncio.run(run())


def test_listener_routes_disabled_and_no_llm(tmp_path):
    # Execute the real listener methods without importing the AstrBot runtime.
    module=ast.parse((Path(__file__).parents[1]/'main.py').read_text())
    cls=next(node for node in module.body if isinstance(node,ast.ClassDef) and any(isinstance(fn,ast.FunctionDef) and fn.name=='resolve_command' for fn in node.body))
    names={'parse_message','resolve_command','ini_command_map','on_all_message'}
    methods=[node for node in cls.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in names]
    for node in methods: node.decorator_list=[]
    wrapper=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),ast.ClassDef(name='Listener',bases=[],keywords=[],body=methods,decorator_list=[])],type_ignores=[])
    from jx3portal.replies import MessageParts, PendingReply
    from jx3portal.game.catalog import GAME_MAP
    namespace={'logger':Mock(),'ImageReply':ImageReply,'MessageParts':MessageParts,'PendingReply':PendingReply,'MenuReply':MenuReply,'send_menu':send_menu,'asyncio':asyncio,'GAME_MAP':GAME_MAP,'split_message':lambda text:[text]}
    exec(compile(ast.fix_missing_locations(wrapper),'<listener>','exec'),namespace)
    listener=namespace['Listener']();listener.commands=service(tmp_path);listener.telemetry=listener.commands.telemetry;listener.ini_command_map()
    assert listener.resolve_command(event('jx3奇怪文本')) is None
    assert listener.resolve_command(event('功能'))[2]=='help'
    for name in ['更新','维护','公告','维护公告','更新公告','游戏更新']:
        assert listener.resolve_command(event(name))[2]=='announce'
    listener.commands.effective_enabled=lambda key:key!='sand'
    assert listener.resolve_command(event('沙盘 唯我独尊')) is None
    assert listener.resolve_command(event('剑三 沙盘 唯我独尊')) is None
    listener.commands.effective_enabled=lambda key:True
    assert listener.resolve_command(event('剑三 沙盘 唯我独尊'))[2]=='sand'
    async def run():
        e=event('沙盘 唯我独尊');e.stop_event=Mock();e.should_call_llm=Mock();e.image_result=lambda path:('image',path)
        assert [result async for result in listener.on_all_message(e)]==[('image','/tmp/sand.jpg')]
        e.should_call_llm.assert_called_once_with(False)
    asyncio.run(run())
    assert all(spec.key in GAME_MAP or hasattr(CommandService,'_cmd_'+spec.key) for spec in COMMANDS)


def test_official_push_images_dedup_and_nonblocking(tmp_path):
    async def run():
        settings=Settings({'event_push_sessions':['test:1','test:2'],'event_push_actions':[2001,2002,2003]},tmp_path)
        release=asyncio.Event();send=AsyncMock();calls=[]
        async def preview(action,detail):
            calls.append(action);await release.wait();return ['/tmp/page1.jpg','/tmp/page2.jpg']
        service=EventPushService(settings,SimpleNamespace(),send,tmp_path,preview_callback=preview)
        news={'action':2002,'detail':{'url':'https://jx3.xoyo.com/article','title':'新闻'}}
        await service.handle_payload(json.dumps(news));await service.handle_payload(json.dumps(news))
        await service.handle_payload(json.dumps({'action':2001,'detail':{'server':'唯我独尊','status':1}}))
        assert send.await_count==2
        release.set();await asyncio.gather(*service._news_tasks)
        assert calls==[2002] and send.await_count==4
        image_calls=[c for c in send.await_args_list if len(c.args)==3]
        assert len(image_calls)==2 and all(len(c.args[2])==2 for c in image_calls)
        service.preview_callback=AsyncMock(side_effect=RuntimeError('failed'))
        await service.handle_payload(json.dumps({'action':2003,'detail':{'url':'https://jx3.xoyo.com/update','title':'公告'}}))
        await asyncio.gather(*service._news_tasks)
        assert send.await_count==6 and len(send.await_args.args)==2
        await service.stop()
    asyncio.run(run())


def test_box_guide_sequence(tmp_path):
    async def run():
        box=JX3BOXClient(Settings({},tmp_path),None,TTLCache(),Telemetry())
        box._request=AsyncMock(side_effect=[{'list':[{'dwID':42,'szName':'三尺青锋'}]},{'achievement_id':123},{'post':{'title':'三尺青锋','content':'<p>攻略正文</p>'}}])
        data=await box.guide('三尺青锋')
        assert '攻略正文' in data['content']
        assert len(box._request.await_args_list)==3
    asyncio.run(run())


def test_news_compact_selects_sections_not_every_product():
    from jx3portal.articles import news_summary
    content='<p>这里是来自官方正文的导语，说明这次更新包含哪些内容以及上线时间。</p><h1>外观上新</h1>'
    content+=''.join(f'<img src="https://jx3.xoyo.com/{n}.jpg">' for n in range(24))
    content+='<h1>活动奖励</h1><p>活动内容。</p><img src="https://jx3.xoyo.com/reward.jpg">'
    data=news_summary({'title':'资讯','date':'2026-10-26','url':'https://jx3.xoyo.com/news','content':content})
    assert len(data['pictures'])==2
    assert [p['url'] for p in data['pictures']]==['https://jx3.xoyo.com/0.jpg','https://jx3.xoyo.com/reward.jpg']
    assert data['points']==['外观上新','活动奖励'] and '导语' in data['lead']


def test_news_defaults_compact_and_full_explicit(tmp_path):
    async def run():
        commands=service(tmp_path);commands.api.news=AsyncMock(return_value=[{'title':'news'}]);commands.articles=SimpleNamespace(from_news=AsyncMock(return_value=['/tmp/news.jpg']))
        await commands._news_reply('')
        assert commands.articles.from_news.call_args.kwargs['compact'] is True
        await commands._news_reply('全文')
        assert commands.articles.from_news.call_args.kwargs['compact'] is False
    asyncio.run(run())


def test_async_admin_routes_return_json_after_await():
    module=ast.parse((Path(__file__).parents[1]/'main.py').read_text())
    cls=next(node for node in module.body if isinstance(node,ast.ClassDef) and any(isinstance(fn,ast.FunctionDef) and fn.name=='register_web_apis' for fn in node.body))
    routes={'web_test':'test','web_token_stats':'token_stats','web_servers':'servers','web_debug':'debug_request','web_render_preview':'render_preview','web_events_reload':'events_reload','web_doubao_test':'doubao_test','web_online_test':'online_test'}
    methods=[node for node in cls.body if isinstance(node,ast.AsyncFunctionDef) and node.name in routes]
    wrapper=ast.Module(body=[ast.ClassDef(name='Routes',bases=[],keywords=[],body=methods,decorator_list=[])],type_ignores=[])
    namespace={'json_response':json.dumps,'_query_get':lambda name,default:default}
    exec(compile(ast.fix_missing_locations(wrapper),'<admin routes>','exec'),namespace)
    instance=namespace['Routes']();instance._json_payload=AsyncMock(return_value={'path':'/data/server/check'});instance._fail=lambda exc,action:(_ for _ in ()).throw(exc)
    instance.admin=SimpleNamespace(**{name:AsyncMock(return_value={'ok':True}) for name in routes.values()})
    async def run():
        for route,name in routes.items():
            assert json.loads(await getattr(instance,route)())=={'ok':True}
            getattr(instance.admin,name).assert_awaited_once()
    asyncio.run(run())


def test_help_overview_categories_and_pagination(tmp_path):
    async def run():
        commands=service(tmp_path);commands.renderer.help=AsyncMock(return_value='/tmp/help.jpg')
        result=await commands._cmd_help('',event())
        data=commands.renderer.help.call_args.args[0]
        assert data['overview'] and all(len(group['items']) <= 4 for group in data['categories'])
        assert {button.label for button in result.menu.buttons}=={group['name'] for group in commands._help_categories(event())}
        result=await commands._cmd_help('团队',event());data=commands.renderer.help.call_args.args[0]
        assert not data['overview'] and len(data['categories'][0]['items'])==18
        assert any(button.command=='功能 团队 2' for button in result.menu.buttons)
        result=await commands._cmd_help('团队 2',event());data2=commands.renderer.help.call_args.args[0]
        assert len(data2['categories'][0]['items'])==6
        assert not set(item['name'] for item in data['categories'][0]['items']) & set(item['name'] for item in data2['categories'][0]['items'])
        commands.renderer.available=False
        assert isinstance(await commands._cmd_help('团队 2',event()),MenuReply)
        assert '用法' in await commands._cmd_help('报名',event())
    asyncio.run(run())
