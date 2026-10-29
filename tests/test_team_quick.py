import asyncio
from test_game_features import service, event
from jx3portal.replies import ImageReply
from jx3portal.buttons import MenuReply
from jx3portal.game.team_manager import TeamManager


def test_quick_create_signup_memory_cancel_and_role_isolation(tmp_path):
    async def run():
        commands=service(tmp_path);game=commands.game;await game.initialize()
        admin=event(admin=True);alice=event();bob=event(user='bob')
        result=await game.run('team_create','发财 今晚八点',admin)
        assert isinstance(result,ImageReply)
        team=(await game.local.team.list_teams(admin.unified_msg_origin))[0]
        assert team['registration_open'] and team['capacity']==25 and team['announcement']=='今晚八点'
        assert team['leader_name']=='alice'
        assert isinstance(await game.run('team_signup','',alice),MenuReply)
        await game.bindings.bind(alice,'唯我独尊','刀剑笑我')
        assert '请选择团队' in (await game.run('team_signup','',alice)).text
        assert '1/25' in (await game.run('team_signup',f"{team['id']} 奶花",alice)).text
        current=await game.local.team.get_team(admin.unified_msg_origin,team['id'])
        assert current['members'][0]['kungfu']=='离经易道'
        assert current['members'][0]['role_name']=='刀剑笑我' and current['members'][0]['server']=='唯我独尊'
        assert '还没有报名' in await game.run('team_cancel','',bob)
        assert '已取消' in await game.run('team_cancel','',alice)
        assert '请选择团队' in (await game.run('team_signup','',alice)).text
        assert '1/25' in (await game.run('team_signup',f"{team['id']} 奶花",alice)).text
        await game.bindings.bind(alice,'唯我独尊','另一个角色')
        assert '请选择团队' in (await game.run('team_signup','',alice)).text
        await game.run('team_view','',alice)
        assert commands.renderer.render.call_args.args[1]['mode']=='formation'
        await game.run('team_formation','',alice)
        assert commands.renderer.render.call_args.args[1]['mode']=='formation'
        await game.run('team_close','',admin)
        assert '暂停报名'  in await game.run('team_signup',f"{team['id']} 奶花",alice)
        await game.close()
    asyncio.run(run())


def test_multiple_teams_and_multiple_roles_require_explicit_choice(tmp_path):
    async def run():
        game=service(tmp_path).game;await game.initialize();admin=event(admin=True);alice=event()
        await game.run('team_create','第一团 10人',admin)
        first=(await game.local.team.list_teams(admin.unified_msg_origin))[0]['id']
        assert '1/10' in (await game.run('team_signup',f'{first} 花间 甲',alice)).text
        assert '2/10' in (await game.run('team_signup',f'{first} 奶花 乙',alice)).text
        assert len((await game.run('team_cancel','',alice)).buttons)==2
        await game.run('team_create','第二团 25',admin)
        assert '请选择团队' in (await game.run('team_signup','花间 丙',alice)).text
        assert '请选择团队' in (await game.run('team_cancel','',alice)).text
        assert '已取消' in await game.run('team_cancel',f'{first} 甲',alice)
        assert '没有找到' in await game.run('team_signup',f'{first} 花间 甲',event(group='other'))
        await game.close()
    asyncio.run(run())


def test_roster_keeps_full_names_and_slot_locations():
    name='一个完整的较长角色名称'
    team={'capacity':25,'members':[{'slot_number':8,'role_name':name,'server':'唯我独尊','kungfu':'傲血战意','is_boss':False,'role_type':'DPS'}]}
    data=TeamManager._prepare_team_image(team)
    assert len(data['roster'])==1 and data['roster'][0]['display_name']=='一个完整的较长角色名称'
    assert data['roster'][0]['server']=='唯我独尊'
    assert data['squads'][1][2]['role_name']==name
    assert data['counts']=={'坦克':0,'治疗':0,'输出':1,'老板':0}
