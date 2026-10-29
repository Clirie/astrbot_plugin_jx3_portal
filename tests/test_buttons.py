import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from jx3portal.buttons import Button, MenuReply, keyboard, send_menu
from test_game_features import service, event


def test_qq_native_keyboard_private_and_public_and_fill_input():
    menu=MenuReply('选择', (Button('25 人团','开团 25人 ',False),Button('报名','报名 3')), 'alice')
    rows=keyboard(menu)['content']['rows'];a,b=rows[0]['buttons']
    assert a['action']['enter'] is False and a['action']['data']=='/开团 25人 '
    assert b['action']['enter'] is True and b['action']['permission']=={'type':0,'specify_user_ids':['alice']}
    assert keyboard(MenuReply('团队',menu.buttons))['content']['rows'][0]['buttons'][0]['action']['permission']=={'type':2}
    assert '开团 25人' in menu.fallback()


def test_qq_group_send_uses_current_message_and_falls_back_on_denial():
    async def run():
        api=SimpleNamespace(post_group_message=AsyncMock(return_value={'id':'sent'}))
        e=SimpleNamespace(get_platform_name=lambda:'qq_official',bot=SimpleNamespace(api=api),message_obj=SimpleNamespace(raw_message=SimpleNamespace(group_openid='test-group'),message_id='incoming'))
        menu=MenuReply('\n请选择\n', (Button('报名','报名 1'),))
        assert await send_menu(e,menu)
        args=api.post_group_message.call_args.kwargs
        assert args['group_openid']=='test-group' and args['msg_id']=='incoming' and args['msg_type']==2 and args['markdown']['content']=='请选择'
        assert args['keyboard']['content']['rows'][0]['buttons'][0]['action']['data']=='/报名 1'
        api.post_group_message.side_effect=PermissionError('denied')
        assert not await send_menu(e,menu)
    asyncio.run(run())


def test_team_menu_buttons_reach_signup_and_change_own_kungfu(tmp_path):
    async def run():
        commands=service(tmp_path);game=commands.game;await game.initialize();alice=event();admin=event(admin=True)
        menu=await game.run('team_create','',admin)
        assert menu.buttons[0].command=='开团 25人 ' and not menu.buttons[0].enter
        image=await game.run('team_create','25人 发财 今晚八点',admin)
        assert image.menu.buttons[0].command.startswith('报名 ')
        tid=(await game.local.team.list_teams(admin.unified_msg_origin))[0]['id']
        await game.bindings.bind(alice,'唯我独尊','刀剑笑我')
        menu=await game.run('team_signup',str(tid),alice)
        button=next(b for b in menu.buttons if b.label=='治疗');args=button.command.split(' ',1)[1]
        healers=await game.run('team_signup_menu',args,alice)
        button=next(b for b in healers.buttons if b.label=='离经易道')
        reply=await game.run('team_signup',button.command.split(' ',1)[1],alice)
        assert '1/25' in reply.text
        reply=await game.run('team_signup',f'{tid} 花间',alice)
        assert '已更新报名' in reply.text and '1/25' in reply.text
        team=await game.local.team.get_team(alice.unified_msg_origin,tid)
        assert team['members'][0]['kungfu']=='花间游'
        stranger=await game.run('team_signup_menu',args,event(user='other'))
        assert all('刀剑笑我' not in b.command for b in stranger.buttons)
        await game.close()
    asyncio.run(run())
