import asyncio
from test_game_features import service, event
from jx3portal.buttons import MenuReply, keyboard
from jx3portal.game.team_manager import TeamManager

async def click(game, menu, label, user):
    button=next(b for b in menu.buttons if b.label==label);cmd,args=button.command.split(' ',1)
    return await game.run({'报名':'team_signup','选择报名':'team_signup_menu','取消报名':'team_cancel'}[cmd],args,user)


def test_team_selection_identity_updates_boss_and_scope(tmp_path):
    async def run():
        commands=service(tmp_path);game=commands.game;await game.initialize();alice=event();admin=event(admin=True)
        await game.run('team_create','发财 25 今晚八点',admin);tid=(await game.local.team.list_teams(alice.unified_msg_origin))[0]['id']
        name='清唳@天鹅坪';await game.bindings.bind(alice,'唯我独尊',name)
        menu=await game.run('team_signup','',alice)
        assert '发财' in menu.text and '今晚八点' in menu.text
        assert (await game.local.team.get_team(alice.unified_msg_origin,tid))['member_count']==0
        role_menu=await click(game,menu,'发财',alice);healers=await click(game,role_menu,'治疗',alice)
        assert name in healers.text and '@唯我独尊' not in str(healers)
        result=await click(game,healers,'离经易道',alice);assert '报名成功' in result.text
        result=await game.run('team_signup',f'{tid} 花间 {name}',alice);assert '已更新报名' in result.text
        team=await game.local.team.get_team(alice.unified_msg_origin,tid);member=team['members'][0]
        assert team['member_count']==1 and member['server']=='唯我独尊' and member['role_name']==name and member['kungfu']=='花间游'
        same_id,slot=member['id'],member['slot_number'];role_menu=await game.run('team_signup',str(tid),alice)
        boss=await click(game,role_menu,'报名老板',alice);assert '老板' in boss.text
        team=await game.local.team.get_team(alice.unified_msg_origin,tid)
        assert team['boss_count']==1 and team['member_count']==1 and team['members'][0]['id']==same_id
        await game.bindings.bind(alice,'梦江南',name)
        ambiguous=await game.run('team_signup',f'{tid} 奶花 {name}',alice)
        assert isinstance(ambiguous,MenuReply) and len(ambiguous.buttons)==2
        result=await click(game,ambiguous,name+' · 梦江南',alice)
        team=await game.local.team.get_team(alice.unified_msg_origin,tid)
        assert team['member_count']==2 and {m['server'] for m in team['members']}=={'唯我独尊','梦江南'}
        prepared=TeamManager._prepare_team_image(team);assert all(m['display_name']==name for m in prepared['roster'])
        ref=(await game.bindings.list(alice))[0]['ref'];denied=await game.run('team_signup',f'{tid} 花间 角色#{ref}',event(user='other'));assert '解绑' in denied
        denied=await game.run('team_signup',f'{tid} 花间 {name}',event(user='other'));assert '其他人' in denied
        cancel=await game.run('team_cancel',str(tid),alice);assert len(cancel.buttons)==2
        await click(game,cancel,name+' · 梦江南',alice)
        team=await game.local.team.get_team(alice.unified_msg_origin,tid);assert team['member_count']==1 and team['members'][0]['id']==same_id and team['members'][0]['slot_number']==slot
        await game.close()
    asyncio.run(run())


def test_kungfu_pages_all_readable_and_boss_without_history(tmp_path):
    async def run():
        commands=service(tmp_path);game=commands.game;await game.initialize();u=event();await game.run('team_create','测试 10',event(admin=True));await game.bindings.bind(u,'唯我独尊','剑客')
        menu=await game.run('team_signup','1',u);page=await click(game,menu,'输出',u);seen=[]
        while True:
            rows=keyboard(page)['content']['rows'];assert len(rows)<=5 and all(len(r['buttons'])<=2 for r in rows)
            assert not page.text.startswith('\n')
            seen.extend(b.label for b in page.buttons if b.label not in {'上一页','下一页','返回'})
            if not any(b.label=='下一页' for b in page.buttons): break
            page=await click(game,page,'下一页',u)
        expected=[r['name'] for r in await game.local.kungfu.list_kungfu() if r['role_type']=='DPS'];assert seen==expected
        boss=await click(game,menu,'报名老板',u);kf=next(b for b in boss.buttons if b.label not in {'上一页','下一页','返回'})
        result=await click(game,boss,kf.label,u);assert '老板' in result.text
        await game.close()
    asyncio.run(run())


def test_concurrent_self_updates_and_swap_keep_identity(tmp_path):
    async def run():
        commands=service(tmp_path);g=commands.game;await g.initialize();u=event();await g.run('team_create','测试 10',event(admin=True));await g.bindings.bind(u,'唯我独尊','剑客')
        await asyncio.gather(g.run('team_signup','1 花间',u),g.run('team_signup','1 奶花',u))
        team=await g.local.team.get_team(u.unified_msg_origin,1);assert team['member_count']==1
        await g.bindings.bind(u,'梦江南','剑客');await g.run('team_signup','1 花间',u)
        await g.local.team.swap_slots(u.unified_msg_origin,1,1,2)
        team=await g.local.team.get_team(u.unified_msg_origin,1);assert {m['server'] for m in team['members']}=={'唯我独尊','梦江南'}
        await g.close()
    asyncio.run(run())


def test_old_qualified_and_literal_names_migrate_without_false_split(tmp_path):
    async def run():
        commands=service(tmp_path);g=commands.game;await g.initialize();u=event();await g.run('team_create','测试 10',event(admin=True))
        await g.bindings.bind(u,'唯我独尊','清唳@天鹅坪');await g.bindings.bind(u,'梦江南','清唳@天鹅坪')
        sql=g.local.sql
        await sql.execute('DROP TABLE raid_team_members')
        await sql.execute("CREATE TABLE raid_team_members (id INTEGER PRIMARY KEY,team_id INTEGER,slot_number INTEGER,squad_number INTEGER,kungfu TEXT,role_name TEXT,user_id TEXT,user_name TEXT,is_boss INTEGER,created_at TEXT,UNIQUE(team_id,role_name))")
        rows=[(1,1,1,1,'花间游','清唳@天鹅坪@唯我独尊','alice','alice',0,'2026-10-27'),(2,1,2,1,'离经易道','清唳@天鹅坪@梦江南','alice','alice',0,'2026-10-27'),(3,1,3,1,'花间游','未绑定@天鹅坪','bob','bob',0,'2026-10-27')]
        for row in rows: await sql.execute('INSERT INTO raid_team_members VALUES (?,?,?,?,?,?,?,?,?,?)',row)
        await g.local.team.initialize();team=await g.local.team.get_team(u.unified_msg_origin,1)
        assert [(m['role_name'],m['server']) for m in team['members']]==[('清唳@天鹅坪','唯我独尊'),('清唳@天鹅坪','梦江南'),('未绑定@天鹅坪','')]
        await g.local.team.initialize();assert (await g.local.team.get_team(u.unified_msg_origin,1))['member_count']==3
        await g.close()
    asyncio.run(run())


def test_migration_merges_same_owned_role_keeps_latest_kungfu_and_first_slot(tmp_path):
    async def run():
        commands=service(tmp_path);g=commands.game;await g.initialize();u=event();await g.run('team_create','测试 10',event(admin=True));await g.bindings.bind(u,'唯我独尊','清唳@天鹅坪');sql=g.local.sql
        await sql.execute('DROP TABLE raid_team_members')
        await sql.execute("CREATE TABLE raid_team_members (id INTEGER PRIMARY KEY,team_id INTEGER,slot_number INTEGER,squad_number INTEGER,kungfu TEXT,role_name TEXT,user_id TEXT,user_name TEXT,is_boss INTEGER,created_at TEXT,UNIQUE(team_id,role_name))")
        for row in [(1,1,1,1,'花间游','清唳@天鹅坪','alice','alice',0,'2026-10-27'),(2,1,2,1,'离经易道','清唳@天鹅坪@唯我独尊','alice','alice',0,'2026-10-27')]: await sql.execute('INSERT INTO raid_team_members VALUES (?,?,?,?,?,?,?,?,?,?)',row)
        await g.local.team.initialize();team=await g.local.team.get_team(u.unified_msg_origin,1)
        assert team['member_count']==1 and team['members'][0]['id']==1 and team['members'][0]['slot_number']==1 and team['members'][0]['kungfu']=='离经易道'
        assert await sql.fetch_all('PRAGMA foreign_key_check')==[]
        await g.close()
    asyncio.run(run())


def test_stale_role_button_cannot_sign_up_new_binding(tmp_path):
    async def run():
        commands=service(tmp_path);g=commands.game;await g.initialize();u=event();await g.run('team_create','测试 10',event(admin=True));await g.bindings.bind(u,'唯我独尊','旧角色')
        ref=(await g.bindings.list(u))[0]['ref'];await g.bindings.unbind(u,'唯我独尊','旧角色');await g.bindings.bind(u,'唯我独尊','新角色')
        assert '解绑' in await g.run('team_signup',f'1 奶花 角色#{ref}',u)
        assert (await g.local.team.get_team(u.unified_msg_origin,1))['member_count']==0
        await g.close()
    asyncio.run(run())


def test_readable_commands_keep_cross_server_selection(tmp_path):
    async def run():
        commands=service(tmp_path);g=commands.game;await g.initialize();u=event();await g.run('team_create','发财 25',event(admin=True))
        name='清唳@天鹅坪';await g.bindings.bind(u,'唯我独尊',name)
        menu=await g.run('team_signup','1',u)
        assert next(b.command for b in menu.buttons if b.label=='输出')=='选择报名 1 输出 '+name
        old_output=menu
        await g.bindings.bind(u,'梦江南',name)
        servers=await click(g,old_output,'输出',u)
        assert '区服' in servers.text and len(servers.buttons)==2
        page=await click(g,servers,name+' · 唯我独尊',u)
        assert all('角色#' not in b.command and '成员#' not in b.command for b in page.buttons)
        assert next(b for b in page.buttons if b.label=='花间游').command=='报名 1 花间游 '+name+'（唯我独尊）'
        result=await click(g,page,'花间游',u)
        assert all('角色#' not in b.command and '成员#' not in b.command for b in result.buttons)
        await g.run('team_signup','1 花间游 '+name+'（梦江南）',u)
        cancel=await g.run('team_cancel','1',u)
        assert all('成员#' not in b.command for b in cancel.buttons)
        await click(g,cancel,name+' · 梦江南',u)
        team=await g.local.team.get_team(u.unified_msg_origin,1)
        assert team['member_count']==1 and team['members'][0]['server']=='唯我独尊'
        await g.close()
    asyncio.run(run())
