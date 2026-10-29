import asyncio,inspect,json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from jx3portal.commands import CommandService,COMMANDS,ImageReply,PendingReply
from jx3portal.settings import Settings
from jx3portal.aliases import ServerAliasService
from jx3portal.cache import TTLCache
from jx3portal.telemetry import Telemetry
from jx3portal.game.catalog import GAME_COMMANDS
from jx3portal.game.data import GameData
from jx3portal.game.service import GameUsageError
from jx3portal.game.market_fusion import fuse_history


def service(tmp_path):
    settings=Settings({'jx3api_token':'test','jx3api_ticket':'test','default_server':'唯我独尊'},tmp_path)
    api=SimpleNamespace(settings=settings,http=None,role_detail=AsyncMock(return_value={'roleName':'剑客','serverName':'唯我独尊'}),request=AsyncMock())
    renderer=SimpleNamespace(available=True,render=AsyncMock(return_value='/tmp/game.jpg'))
    return CommandService(settings,api,None,None,TTLCache(),Telemetry(),aliases=ServerAliasService(tmp_path),renderer=renderer)


def event(user='alice',group='a',admin=False):
    return SimpleNamespace(unified_msg_origin='qq:GroupMessage:'+group,get_sender_id=lambda:user,get_sender_name=lambda:user,get_group_id=lambda:group,is_admin=lambda:admin,get_group=AsyncMock(return_value=SimpleNamespace(group_admins=[],group_owner='owner')))


def test_catalog_arguments_and_no_duplicate_aliases():
    aliases=[alias for row in COMMANDS for alias in (row.name,*row.aliases)]
    assert len(aliases)==len(set(aliases))
    for row in GAME_COMMANDS:
        if row.get('local') or row.get('play'):continue
        signature=inspect.signature(getattr(GameData,row['method']))
        supplied=set(row['params'])|set(row['fixed'])
        required={key for key,value in signature.parameters.items() if key!='self' and value.default is inspect.Parameter.empty}
        assert required <= supplied <= set(signature.parameters)-{'self'}
        assert not set(row['params']) & set(row['fixed'])


def test_mode_server_and_recruit_parsing(tmp_path):
    game=service(tmp_path).game
    rows={row['name']:row for row in GAME_COMMANDS}
    assert game.parse(rows['战绩'],'唯我独尊 剑客 2v2')['mode']=='22'
    assert game.parse(rows['战绩'],'剑客','唯我独尊')['server']=='唯我独尊'
    assert game.parse(rows['跨服名剑'],'唯我独尊 55')['mode']==2
    assert game.parse(rows['拜师'],'唯我独尊')['label']==2
    assert game.parse(rows['收徒'],'唯我独尊')['label']==1
    assert game.parse(rows['招募'],'唯我独尊')['label']==1
    assert game.parse(rows['团长'],'唯我独尊')['label']==2
    assert game.parse(rows['团牌'],'唯我独尊')['label']==3
    for name,args in [('名剑排行','44'),('名剑排行','33 0'),('急速计算','nan'),('帮会排行','唯我独尊 错误榜单')]:
        with pytest.raises(GameUsageError):game.parse(rows[name],args)


def test_api_cache_not_mutated_and_empty_result_is_plain(tmp_path):
    async def run():
        commands=service(tmp_path);rows=[{'time':1,'name':'烟花'}];before=deepcopy(rows)
        commands.api.request.return_value=rows
        await commands.game.data.yanhuachaxun('唯我独尊','剑客',20)
        assert rows==before
        commands.api.request.return_value=[]
        result=await commands.game.data.tuanduizhaomu('唯我独尊',1,'',20)
        assert result['code']==404 and '功能函数' not in result['msg']
        assert await commands.game.reply(result)=='暂无相关记录。'
        await commands.game.close()
    asyncio.run(run())


def test_role_binding_cross_group_and_user_isolation(tmp_path):
    async def run():
        commands=service(tmp_path);await commands.game.initialize()
        await commands.game.run('role_bind','唯我独尊 剑客',event())
        assert (await commands.game.bindings.role(event(group='b')))['name']=='剑客'
        assert await commands.game.bindings.role(event(user='bob')) is None
        await commands.game.run('bind_server','乾坤一掷',event(admin=True))
        assert await commands.game.bindings.server(event())=='乾坤一掷'
        assert await commands.game.bindings.server(event(group='b'))==''
        await commands.game.close()
    asyncio.run(run())


def test_raid_permissions_and_registration_not_cross_session(tmp_path):
    async def run():
        commands=service(tmp_path);game=commands.game;await game.initialize()
        admin=event(admin=True);alice=event();bob=event(user='bob')
        denied=await game.run('team_create','测试 10',alice)
        assert '管理员' in denied and await game.local.team.list_teams(alice.unified_msg_origin)==[]
        await game.run('team_create','测试 10',admin)
        team=(await game.local.team.list_teams(alice.unified_msg_origin))[0];tid=str(team['id'])
        await game.run('team_open',tid,admin)
        assert '报名成功' in (await game.run('team_signup',tid+' 花间 剑客',alice)).text
        assert '只能取消自己' in await game.run('team_cancel',tid+' 剑客',bob)
        assert await game.local.team.get_team(event(group='b').unified_msg_origin,int(tid)) is None
        assert len((await game.local.team.get_team(alice.unified_msg_origin,int(tid)))['members'])==1
        assert '已取消' in await game.run('team_cancel',tid+' 剑客',alice)
        await game.close()
    asyncio.run(run())


def test_bilei_scoped_and_admin_only(tmp_path):
    async def run():
        commands=service(tmp_path);game=commands.game;await game.initialize()
        assert '管理员' in await game.run('bilei_add','测试 备注',event())
        assert '添加成功' in await game.run('bilei_add','测试 备注',event(admin=True))
        other=await game.run('bilei_search','测试',event(group='b'))
        assert isinstance(other,str) and '备注' not in other
        await game.close()
    asyncio.run(run())


def test_market_menu_and_selection_isolation_and_full_history(tmp_path):
    async def run():
        commands=service(tmp_path);market=commands.market
        commands.api.trade_records=AsyncMock(side_effect=lambda name,server:{'name':name,'alias':'蓝观灯','retail':280,'date':'2024-02-22'})
        market.history.detail=AsyncMock(return_value={})
        commands.api.request.return_value=[{'name':'十五夜观灯·南涧·标准'},{'name':'十五夜观灯·封霜·标准'}]
        market.image=AsyncMock(return_value=ImageReply('/tmp/price.jpg'))
        first=await market.query('关灯','',event())
        assert isinstance(first,PendingReply) and '封霜' in first.text
        assert first.menu.buttons[0].command=='换款 十五夜观灯·封霜·标准'
        assert first.menu.owner=='alice' and '默认查询：十五夜观灯·南涧·标准' in first.menu.text
        first.on_sent()
        assert '过期' in await market.select('1',event(user='bob'))
        assert '过期' in await market.select('1',event(group='b'))
        await market.select('1',event())
        assert await first.load() is None
        assert market.image.call_args.args[0]=='十五夜观灯·封霜·标准'
        assert market.image.await_count==1
        market.image.reset_mock()
        assert '没有找到匹配' in await market.query('观灯 黄色','',event())
        market.image.assert_not_called()
        await market.close();await commands.game.close()
    asyncio.run(run())
    series=[{'label':'在售','points':[{'date':'2024-01-01','value':20},{'date':'2026-10-26','value':30}]},{'label':'收购报价','points':[{'date':'2024-01-01','value':999}]},{'kind':'listing_mean','provider':'爱剑三','points':[{'date':'2026-10-26','value':25}]}]
    fused=fuse_history(series)
    assert [(p['date'],p['value']) for p in fused['points']]==[('2024-01-01',20),('2026-10-26',25)]


def test_old_market_query_cannot_replace_newer_menu(tmp_path):
    async def run():
        commands=service(tmp_path);market=commands.market;wait=asyncio.Event();entered=asyncio.Event()
        commands.api.trade_records=AsyncMock(side_effect=lambda name,server:{'name':name})
        market.history.detail=AsyncMock(return_value={})
        async def request(path,params):
            if params['name']=='旧':entered.set();await wait.wait()
            return [{'name':params['name']+'·甲·标准'},{'name':params['name']+'·乙·标准'}]
        commands.api.request=request
        old=asyncio.create_task(market.query('旧','',event()));await entered.wait()
        latest=await market.query('新','',event());wait.set()
        assert await old is None and '新' in latest.text
        assert market.choices.active(event()).options['1'].startswith('新')
        await market.close();await commands.game.close()
    asyncio.run(run())


def test_previous_json_bindings_import_once_and_user_scope(tmp_path):
    (tmp_path/'role_binding.json').write_text(json.dumps({'alice':[{'server':'唯我独尊','name':'甲'},{'server':'乾坤一掷','name':'乙'}]}))
    (tmp_path/'server_binding.json').write_text(json.dumps({'qq:GroupMessage:a':{'server':'乾坤一掷'}}))
    async def run():
        commands=service(tmp_path);await commands.game.initialize();bindings=commands.game.bindings
        assert len(await bindings.list(event()))==2
        assert (await bindings.role(event(group='b')))['name']=='甲'
        assert await bindings.server(event())=='乾坤一掷'
        assert await bindings.list(event(user='bob'))==[]
        await bindings.unbind(event(),'唯我独尊','甲')
        await bindings.import_previous(tmp_path)
        assert len(await bindings.list(event()))==1
        await commands.game.close()
    asyncio.run(run())


def test_command_switch_migration_preserves_overrides(tmp_path):
    settings=service(tmp_path).settings
    settings.save_command_overrides({'disabled':['x_calcd_attribute'],'cooldowns':{'x_calcd_attribute':30},'permissions':{'x_calcd_attribute':'admin'}})
    settings.migrate_command_keys()
    data=settings.command_overrides()
    assert 'game_equipment' in data['disabled'] and data['cooldowns']['game_equipment']==30 and data['permissions']['game_equipment']=='admin'
    settings.migrate_command_keys()
    assert settings.command_overrides()==data


def test_online_failures_are_unknown_not_offline(tmp_path):
    from jx3portal.online import OnlineError
    async def run():
        commands=service(tmp_path);await commands.game.initialize();await commands.game.bindings.bind(event(),'唯我独尊','甲')
        commands.online=SimpleNamespace(query=AsyncMock(side_effect=OnlineError('unavailable')))
        await commands._cmd_online_stats('',event())
        assert commands.renderer.render.call_args.args[1]['rows'][0][-1]=='暂未查到'
        await commands.game.close()
    asyncio.run(run())


def test_equipment_adapter_and_skill_pagination(tmp_path):
    async def run():
        commands=service(tmp_path)
        commands.api.request.return_value={'kungfuName':'北傲诀','equipScore':12345,'panelList':[{'name':'会心','value':'20%'}],'equipList':[{'itemName':'剑','itemLevel':100}]}
        result=await commands.game.data.equipment('唯我独尊','甲')
        assert result['temp']=='equipment' and result['data']['equipment'][0]['itemName']=='剑'
        assert any(call.args==('/calcd/attribute',{'server':'唯我独尊','name':'甲','format':'calcd'}) for call in commands.api.request.call_args_list)
        commands.api.request.return_value={'skillCount':25,'skillList':[{'szSkillName':str(i),'nCost':30} for i in range(25)]}
        result=await commands.game.data.role_monster('唯我独尊','甲',page=2)
        assert len(result['data']['rows'])==1 and result['data']['rows'][0][0]=='24'
        assert (await commands.game.data.role_monster('唯我独尊','甲',page=3))['code']==400
        await commands.game.close()
    asyncio.run(run())


def test_card_ai_uses_existing_client_without_extra_api_fields(tmp_path):
    async def run():
        commands=service(tmp_path);await commands.game.initialize()
        commands.doubao=SimpleNamespace(enabled=True,generate=AsyncMock(return_value='/tmp/card.jpg'))
        commands.game.data.card_remote=AsyncMock(return_value={'code':200,'data':[{'type':'image','path':'https://example.com/card.png'}]})
        result=await commands._cmd_card_ai('唯我独尊 剑客 水墨',event())
        assert isinstance(result,ImageReply)
        assert commands.doubao.generate.call_args.kwargs=={'image':'https://example.com/card.png'}
        await commands.game.close()
    asyncio.run(run())


def test_migration_does_not_reassign_new_bazi_permission(tmp_path):
    settings=service(tmp_path).settings
    settings.save_command_overrides({'disabled':['fortune'],'cooldowns':{},'permissions':{}})
    settings.migrate_command_keys()
    assert settings.command_overrides()['disabled']==['horoscope']
    settings.save_command_overrides({'disabled':['fortune'],'cooldowns':{},'permissions':{}})
    settings.migrate_command_keys()
    assert settings.command_overrides()['disabled']==['fortune']


def test_team_leader_update_is_scoped_and_admin_only(tmp_path):
    async def run():
        game=service(tmp_path).game;await game.initialize();admin=event(admin=True)
        await game.run('team_create','测试 10',admin)
        tid=(await game.local.team.list_teams(admin.unified_msg_origin))[0]['id']
        assert '管理员' in await game.run('team_leader',f'{tid} 剑客',event())
        assert '已更新' in await game.run('team_leader',f'{tid} 剑客',admin)
        assert (await game.local.team.get_team(admin.unified_msg_origin,tid))['leader_name']=='剑客'
        assert '没有找到' in await game.run('team_note',f'{tid} 备注',event(group='b',admin=True))
        await game.close()
    asyncio.run(run())
