import json
from .. import assets
from ..buttons import Button, MenuReply
from ..replies import ImageReply
from .bindings import Bindings
from .sqlite import AsyncSQLiteDB
from .kungfu_alias import KungfuAliasService
from .team_rules import TeamRuleService
from .team import TeamService
from .team_manager import TeamManager
from .bilei_data import BiLeidata

TEAM_METHODS = {
    'team_create': ('create', ('team_name', 'capacity'), {}),
    'team_open': ('open_registration', ('team_id',), {}),
    'team_close': ('close_registration', ('team_id',), {}),
    'team_end': ('end', ('team_id',), {}),
    'team_end_all': ('end_all', (), {}),
    'team_clear': ('clear_members', ('team_id',), {}),
    'team_signup': ('signup', ('team_id', 'kungfu', 'role_name', 'boss_mark'), {'boss_mark': ''}),
    'team_cancel': ('cancel_signup', ('team_id', 'role_name'), {}),
    'team_view': ('view', ('team_id',), {'team_id': 0}),
    'team_update': ('update_member', ('team_id', 'role_name', 'new_role_name', 'kungfu', 'boss_mark'), {'boss_mark': ''}),
    'team_swap': ('swap_slots', ('team_id', 'first_slot', 'second_slot'), {}),
    'team_rules': ('view_rules', ('scope',), {}),
    'team_rule_add': ('save_rule', ('scope', 'rule_type', 'target', 'min_count', 'max_count'), {}),
    'team_rule_edit': ('save_rule', ('scope', 'rule_id', 'rule_type', 'target', 'min_count', 'max_count'), {}),
    'team_rule_delete': ('delete_rule', ('scope', 'rule_id'), {}),
    'team_rule_reset': ('reset_rules', ('scope',), {}),
}

class LocalGame:
    def __init__(self, service):
        self.service = service
        self.sql = AsyncSQLiteDB(str(service.settings.data_dir / 'game.sqlite3'))
        self.bindings = Bindings(self.sql)
        self.kungfu = KungfuAliasService(self.sql, assets.DATA_DIR / 'kungfu.json')
        self.rules = TeamRuleService(self.sql, self.kungfu)
        self.team = TeamService(self.sql, self.kungfu, self.rules)
        self.manager = TeamManager(self.team, self.rules)
        self.bilei = BiLeidata(self.sql)

    async def initialize(self):
        await self.sql.connect()
        await self.bindings.initialize()
        await self.sql.execute('CREATE TABLE IF NOT EXISTS portal_signup_kungfu (owner TEXT NOT NULL, role_name TEXT NOT NULL, kungfu TEXT NOT NULL, PRIMARY KEY(owner,role_name))')
        await self.bindings.import_previous(self.service.settings.data_dir)
        self.service.settings.data_dir.joinpath("game.sqlite3").chmod(0o600)
        await self.kungfu.initialize()
        await self.team.initialize()
        await self.rules.initialize()
        await self.bilei.initialize()

    async def run(self, key, args, event):
        from .service import GameUsageError
        words = args.split()
        if key in {'team_count','team_kungfu','team_rename'}:
            if not words or not words[0].isdigit():raise GameUsageError()
            if key!='team_rename' and len(words)!=1:raise GameUsageError()
            if key=='team_rename':
                error=await self.manager._permission_error(event)
                if error:return error
                if len(words)<2:raise GameUsageError()
            sid,tid=str(event.unified_msg_origin),int(words[0]);team=await self.team.get_team(sid,tid)
            if not team:return '没有找到这个团队。'
            if key=='team_rename':
                name=' '.join(words[1:])
                if len(name)>80:return '团名最多 80 个字。'
                await self.sql.execute('UPDATE raid_teams SET name=?,updated_at=CURRENT_TIMESTAMP WHERE session_id=? AND id=?',(name,sid,tid))
                return '团名已改为：'+name
            members=team['members'];counts={}
            for member in members:
                label=member['kungfu'] if key=='team_kungfu' else '老板' if member['is_boss'] else {'T':'坦克','HEALER':'治疗','DPS':'输出'}.get(member['role_type'],'输出')
                counts[label]=counts.get(label,0)+1
            if key=='team_count':
                return team['name']+f" · {len(members)}/{team['capacity']} 人\n"+' · '.join(f'{label} {count}' for label,count in counts.items())+f"\n空位 {team['capacity']-len(members)}"
            return await self.service.reply({'code':200,'temp':'game_records','data':{'title':'团队心法','subtitle':team['name'],'facts':[('已报名',len(members)),('空位',team['capacity']-len(members))],'columns':['心法','人数'],'rows':[[name,count] for name,count in sorted(counts.items(),key=lambda item:-item[1])]}})
        if key=='role_clear':
            if words:raise GameUsageError()
            changed=await self.sql.execute_affected('DELETE FROM portal_roles WHERE owner=?',(self.bindings.owner(event),))
            return f'已解绑 {changed} 个角色。' if changed else '还没有绑定角色。'
        if key in {'team_leader','team_note'}:
            error = await self.manager._permission_error(event)
            if error: return error
            parts = args.split(maxsplit=1)
            if len(parts) != 2 or not parts[0].isdigit(): raise GameUsageError()
            sid, tid = str(event.unified_msg_origin), int(parts[0])
            if not await self.team.get_team(sid, tid): return '没有找到这个团队。'
            field = 'leader_name' if key == 'team_leader' else 'announcement'
            await self.sql.execute(f'UPDATE raid_teams SET {field}=?, updated_at=CURRENT_TIMESTAMP WHERE session_id=? AND id=?', (parts[1], sid, tid))
            return '已更新团长。' if key == 'team_leader' else '已更新团队备注。'
        if key == 'team_create':
            if not words:
                error = await self.manager._permission_error(event)
                if error: return error
                return MenuReply('新建团队\n点选人数，在输入框填入团名和时间后发送。', (Button('25 人团', '开团 25人 ', False), Button('10 人团', '开团 10人 ', False)), str(event.get_sender_id()))
            capacity = '25'
            if words[0].removesuffix('人').isdigit():
                capacity = words.pop(0).removesuffix('人')
                if not words: return MenuReply(f'{capacity} 人团\n填入团名和时间后发送。', (Button('填写团名和时间', f'开团 {capacity}人 ', False),), str(event.get_sender_id()))
                name = words.pop(0)
            else:
                name = words.pop(0)
                if words and words[0].removesuffix('人').isdigit(): capacity = words.pop(0).removesuffix('人')
            return await self.service.reply(await self.manager.create(event, name, capacity, *words))
        if key == 'team_signup_menu':
            if not words or not words[0].isdigit() or len(words)>4: raise GameUsageError()
            tid=int(words[0]);kind=words[1] if len(words)>1 else '角色';page=int(words[3]) if len(words)>3 and words[3].isdigit() else 1
            team=await self.team.get_team(str(event.unified_msg_origin),tid)
            if not team: return '没有找到这个团队。'
            if not team['registration_open']: return '这个团队已暂停报名。'
            roles=await self.bindings.list(event);owner=str(event.get_sender_id())
            if not roles: return MenuReply(team['name']+' · 选择报名角色', (Button('绑定角色','绑定角色 ',False),Button('手动报名',f'报名 {tid} ',False)),owner)
            if kind=='角色':
                if len(roles)==1: return await self.run('team_signup_menu',f"{tid} 推荐 {roles[0]['choice']}",event)
                choices=roles[(page-1)*8:page*8]
                buttons=[Button(r['name']+' · '+r['server'],f"选择报名 {tid} 推荐 {r['choice']}") for r in choices]
                if page>1: buttons.append(Button('上一页',f'选择报名 {tid} 角色 - {page-1}'))
                if page*8<len(roles): buttons.append(Button('下一页',f'选择报名 {tid} 角色 - {page+1}'))
                return MenuReply(team['name']+' · 选择角色',tuple(buttons),owner)
            token=words[2] if len(words)>2 else roles[0]['choice']
            matches=[r for r in roles if token==r['name']]
            if not matches: matches=[r for r in roles if token==r['name']+'（'+r['server']+'）' or token=='角色#'+r['ref'] or token==r['name']+'@'+r['server']]
            if len(matches)>1: return MenuReply(team['name']+' · 选择角色所在区服',tuple(Button(r['name']+' · '+r['server'],f"选择报名 {tid} {kind} {r['choice']} {page}") for r in matches),owner)
            role=matches[0] if matches else None
            if not role: return '这个角色已解绑，请重新选择报名角色。'
            ref=role['choice'];name,server=role['name'],role['server'];identity=json.dumps([server,name],ensure_ascii=False)
            saved=await self.sql.fetch_one('SELECT kungfu FROM portal_signup_kungfu WHERE owner=? AND role_name=?',(self.bindings.owner(event),identity))
            same_names=[r for r in roles if r['name']==name]
            title=team['name']+' · '+name+('（'+server+'）' if len(same_names)>1 else '')
            if kind=='推荐':
                buttons=[Button(saved['kungfu']+'报名',f"报名 {tid} {saved['kungfu']} {ref}")] if saved else []
                buttons += [Button(label,f'选择报名 {tid} {label} {ref}') for label in ['坦克','治疗','输出']]
                buttons.append(Button('报名老板',f"报名 {tid} {saved['kungfu']} {ref} 老板" if saved else f'选择报名 {tid} 老板 {ref}'))
                buttons.append(Button('换角色',f'选择报名 {tid} 角色'))
                return MenuReply(title+'\n选择报名职责',tuple(buttons),owner)
            role_type={'坦克':'T','治疗':'HEALER','输出':'DPS','老板':'ALL'}.get(kind)
            if not role_type or page<1: raise GameUsageError()
            choices=[r for r in await self.kungfu.list_kungfu() if role_type=='ALL' or r['role_type']==role_type]
            if (page-1)*8>=len(choices): return '这一页没有心法，请重新选择。'
            buttons=[Button(r['name'],f"报名 {tid} {r['name']} {ref}"+(' 老板' if kind=='老板' else '')) for r in choices[(page-1)*8:page*8]]
            buttons.append(Button('上一页',f'选择报名 {tid} {kind} {ref} {page-1}') if page>1 else Button('返回',f'选择报名 {tid} 推荐 {ref}'))
            if len(choices)>8: buttons.append(Button('下一页',f'选择报名 {tid} {kind} {ref} {page+1}') if page*8<len(choices) else Button('返回',f'选择报名 {tid} 推荐 {ref}'))
            return MenuReply(title+'\n'+('老板报名 · ' if kind=='老板' else '')+'选择心法',tuple(buttons),owner)
        if key in {'team_signup','team_cancel','team_view','team_formation','team_roster','team_open','team_close'}:
            sid=str(event.unified_msg_origin);owner=str(event.get_sender_id())
            tid=int(words.pop(0).removeprefix('#')) if words and words[0].removeprefix('#').isdigit() else 0
            teams=await self.team.list_teams(sid)
            if not tid:
                candidates=[t for t in teams if t['registration_open']] if key=='team_signup' else teams
                if not candidates: return '当前没有开放报名的团队。' if key=='team_signup' else '当前没有团队。'
                if key=='team_signup' or len(candidates)>1:
                    command={'team_signup':'报名','team_cancel':'取消报名','team_formation':'阵容','team_open':'打开报名','team_close':'关闭报名','team_view':'团队','team_roster':'团队名单'}[key]
                    text='请选择团队\n'+'\n'.join(f"{t['name']} · {t['member_count']}/{t['capacity']} 人"+(' · '+t['announcement'] if t['announcement'] else '') for t in candidates)
                    return MenuReply(text,tuple(Button(t['name'],command+' '+str(t['id'])+(' '+' '.join(words) if words else '')) for t in candidates),owner)
                tid=candidates[0]['id']
            team=await self.team.get_team(sid,tid)
            if not team: return '没有找到这个团队。'
            if key in {'team_view','team_formation','team_roster','team_open','team_close'}:
                if words: raise GameUsageError()
                result=await self.manager.view(event,tid,formation=key!='team_roster') if key in {'team_view','team_formation','team_roster'} else await getattr(self.manager,TEAM_METHODS[key][0])(event,tid)
                return await self.service.reply(result)
            if key=='team_cancel':
                if len(words)>1: raise GameUsageError()
                token=words[0] if words else ''
                matches=[m for m in team['members'] if str(m['user_id'])==owner] if not token else [m for m in team['members'] if token=='成员#'+str(m['id']) or token==m['role_name'] or token==m['role_name']+'（'+m['server']+'）' or token==m['role_name']+'@'+m['server']]
                if not matches: return '你还没有报名这个团队。'
                if len(matches)>1: return MenuReply('选择要取消的报名',tuple(Button(m['role_name']+(' · '+m['server'] if m['server'] else ''),f"取消报名 {tid} {m['role_name']}（{m['server']}）") for m in matches),owner)
                m=matches[0];return await self.service.reply(await self.manager.cancel_signup(event,tid,m['role_name'],member_id=m['id']))
            if len(words)>3: raise GameUsageError()
            boss=words.pop() if words and words[-1]=='老板' else ''
            if not words: return await self.run('team_signup_menu',f"{tid} {'老板' if boss else '角色'}",event)
            kungfu=words[0];token=words[1] if len(words)>1 else '';roles=await self.bindings.list(event)
            if token.startswith('角色#'):
                matches=[r for r in roles if token=='角色#'+str(r['ref'])]
                if not matches: return '这个角色已解绑，请重新选择报名角色。'
            elif token:
                matches=[r for r in roles if r['name']==token]
                if not matches: matches=[r for r in roles if token in {r['name']+'（'+r['server']+'）',r['name']+'@'+r['server']}]
            else: matches=roles[:1]
            if len(matches)>1:
                return MenuReply(team['name']+' · 选择角色所在区服',tuple(Button(r['name']+' · '+r['server'],f"报名 {tid} {kungfu} {r['choice']}"+(' 老板' if boss else '')) for r in matches),owner)
            if matches: role=matches[0];name,server=role['name'],role['server']
            elif token: name,server=token,await self.bindings.server(event) or self.service.settings.default_server or ''
            else: return await self.run('team_signup_menu',f'{tid} 角色',event)
            result=await self.manager.signup(event,tid,kungfu,name,boss,server)
            if result['code']==200:
                identity=json.dumps([server,name],ensure_ascii=False)
                await self.sql.execute('INSERT INTO portal_signup_kungfu (owner,role_name,kungfu) VALUES (?,?,?) ON CONFLICT(owner,role_name) DO UPDATE SET kungfu=excluded.kungfu',(self.bindings.owner(event),identity,self.kungfu.resolve_kungfu(kungfu)))
                current=await self.team.get_team(sid,tid);member=next(m for m in current['members'] if m['role_name'].casefold()==name.casefold() and m['server']==server)
                reply=await self.service.reply(result)
                cancel_name=name+('（'+server+'）' if sum(m['role_name']==name for m in current['members'])>1 else '')
                return MenuReply(reply,(Button('查看团队',f'团队 {tid}'),Button('换心法 / 职责',f'选择报名 {tid} 推荐 {matches[0]["choice"]}') if matches else Button('修改报名',f'报名 {tid} ',False),Button('取消报名',f"取消报名 {tid} {cancel_name}")),owner)
            return await self.service.reply(result)
        if key in TEAM_METHODS:
            method, params, defaults = TEAM_METHODS[key]
            values = dict(defaults)
            if key == 'team_create':
                if len(words) < 2: raise GameUsageError()
                result = await self.manager.create(event, words[0], words[1], *words[2:])
            else:
                if len(words) > len(params): raise GameUsageError()
                values.update(zip(params, words))
                if any(param not in values for param in params): raise GameUsageError()
                for param in ('team_id', 'rule_id', 'first_slot', 'second_slot', 'min_count', 'max_count'):
                    if param in values:
                        try: values[param] = int(values[param])
                        except ValueError: raise GameUsageError() from None
                result = await getattr(self.manager, method)(event, **values)
            return await self.service.reply(result)
        if key == 'show_server':
            if words: raise GameUsageError()
            server = await self.bindings.server(event) or self.service.settings.default_server
            return '当前区服：' + server if server else '还没有绑定区服。用法：绑定区服 服务器'
        if key in {'bind_server', 'unbind_server'}:
            if event.get_group_id():
                error = await self.manager._permission_error(event)
                if error: return error
            if key == 'unbind_server':
                if words: raise GameUsageError()
                await self.sql.execute('DELETE FROM portal_servers WHERE session=?', (str(event.unified_msg_origin),))
                return '已解除当前会话的区服绑定。'
            if len(words) != 1: raise GameUsageError()
            server = self.service.aliases.lookup(words[0]) if self.service.aliases else words[0]
            if not server or not assets.is_server(server): return '没有找到这个服务器。'
            await self.sql.execute('INSERT INTO portal_servers (session,server) VALUES (?,?) ON CONFLICT(session) DO UPDATE SET server=excluded.server', (str(event.unified_msg_origin), server))
            return '已绑定区服：' + server
        if key == 'role_list':
            roles = await self.bindings.list(event)
            return '\n'.join(row['server'] + ' · ' + row['name'] + ('（默认）' if row['active'] else '') for row in roles) or '还没有绑定角色。用法：绑定角色 服务器 角色名'
        if key in {'role_bind', 'role_unbind'}:
            if len(words) == 1:
                server = await self.bindings.server(event) or self.service.settings.default_server
                name = words[0]
                if key == 'role_unbind':
                    hits = [row for row in await self.bindings.list(event) if row['name'] == name]
                    if len(hits) == 1: server = hits[0]['server']
                    elif len(hits) > 1: return '有同名角色，请补充服务器。'
            elif len(words) == 2: server, name = words
            else: raise GameUsageError()
            server = self.service.aliases.resolve(server) if self.service.aliases else server
            if not server: raise GameUsageError()
            if key == 'role_unbind':
                changed = await self.bindings.unbind(event, server, name)
                return '已解绑：' + server + ' · ' + name if changed else '没有绑定这个角色。'
            detail = await self.service.api.role_detail(server, name)
            if not isinstance(detail, dict) or detail.get('roleName') != name or detail.get('serverName', server) != server:
                return '没有找到这个角色，请检查服务器和角色名。'
            roles = await self.bindings.list(event)
            if len(roles) >= 20 and not any(row['server']==server and row['name']==name for row in roles): return '最多绑定 20 个角色，请先解绑不用的角色。'
            await self.bindings.bind(event, server, name)
            return '默认角色：' + server + ' · ' + name
        if key.startswith('bilei_'):
            sid, user = str(event.unified_msg_origin), str(event.get_sender_name())
            if key not in {'bilei_view', 'bilei_search'}:
                error = await self.manager._permission_error(event)
                if error: return error
            if key == 'bilei_view': result = await self.bilei.all(sid)
            elif key == 'bilei_search':
                if not args: raise GameUsageError()
                result = await self.bilei.select(sid, args)
            elif key == 'bilei_add':
                parts = args.split(maxsplit=1)
                if len(parts) != 2: raise GameUsageError()
                result = await self.bilei.add(sid, *parts, user)
            elif key == 'bilei_edit':
                parts = args.split(maxsplit=1)
                if len(parts) != 2 or not parts[0].isdigit(): raise GameUsageError()
                row = await self.sql.fetch_one('SELECT name FROM bilei WHERE session_id=? AND id=?', (sid, int(parts[0])))
                if not row: return '没有找到这条避雷记录。'
                result = await self.bilei.update(sid, int(parts[0]), row['name'], parts[1], user)
            elif key == 'bilei_delete':
                if not args.isdigit(): raise GameUsageError()
                result = await self.bilei.delete(sid, int(args))
            return await self.service.reply(result)
        raise KeyError(key)
