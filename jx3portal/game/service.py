"""游戏查询的参数解析与结果转换，使用百宝箱的连接池和渲染器。"""
from copy import deepcopy
from .. import assets
from ..replies import ImageReply, MessageParts
from ..buttons import Button, MenuReply
from .catalog import GAME_MAP
from .local import LocalGame
from .play import ExistingPlay
from .data import GameData, GUILD_RANK_OPTIONS, CAMP_RANK_OPTIONS, OTHER_RANK_OPTIONS, RANK_NAMES

class GameUsageError(ValueError):
    pass

class GameService:
    def __init__(self, settings, api, renderer, aliases):
        self.api, self.renderer, self.aliases = api, renderer, aliases
        self.settings = settings
        self.data = GameData(api, settings)
        self.bindings = None
        self.local = LocalGame(self)
        self.play = ExistingPlay(self)

    async def initialize(self):
        await self.local.initialize()
        self.bindings = self.local.bindings

    async def close(self):
        await self.local.sql.close()
        await self.data.close()

    def parse(self, spec, args, default_server=''):
        words = args.split()
        values = deepcopy(spec['defaults'])
        params = spec['params']
        if params and params[0] == 'server':
            supplied = self.aliases.lookup(words[0]) if words and self.aliases else None
            if not supplied and words and assets.is_server(words[0]): supplied = words[0]
            if supplied:
                values['server'] = supplied
                words.pop(0)
            elif default_server:
                values['server'] = default_server
            elif values.get('server') is None:
                raise GameUsageError()
            params = params[1:]
        if len(words) > len(params): raise GameUsageError()
        values.update(zip(params, words))
        if any(values.get(param) is None for param in spec['params']): raise GameUsageError()
        if values.get('server') and self.aliases: values['server'] = self.aliases.resolve(values['server'])
        for param in ('limit', 'num', 'page', 'floor', 'source'):
            if param not in values: continue
            try: values[param] = int(values[param])
            except (ValueError, TypeError): raise GameUsageError() from None
            low, high = (0, 15) if spec['method']=='activity' and param=='num' else (0, 2) if param == 'source' else (1, 120 if param == 'floor' else 100)
            if not low <= values[param] <= high: raise GameUsageError()
        if spec['method']=='activity' and not 0 <= values['num'] <= 15: raise GameUsageError()
        if 'cooldown' in values:
            try: values['cooldown'] = float(values['cooldown'])
            except (ValueError, TypeError): raise GameUsageError() from None
            if not 0.1 <= values['cooldown'] <= 60: raise GameUsageError()
        method = spec['method']
        if method in {'zhanji', 'mingjianpaihang', 'mingjiantongji', 'kuafumingjian'}:
            mode = str(values['mode']).lower().replace('v', '')
            if mode not in {'22', '33', '55'}: raise GameUsageError('模式可选 22、33、55。')
            values['mode'] = {'22': 0, '33': 1, '55': 2}[mode] if method == 'kuafumingjian' else mode
        if method == 'wulinzhengba':
            camp = {'浩气盟': 1, '浩气': 1, '1': 1, '恶人谷': 2, '恶人': 2, '2': 2}.get(str(values['camp']))
            if camp is None: raise GameUsageError()
            values['camp'] = camp
        if method == 'juedoutiaozhan':
            mode = {'公开': 1, '本服': 1, '1': 1, '私人': 2, '私密': 2, '2': 2}.get(str(values['mode']))
            if mode is None: raise GameUsageError()
            values['mode'] = mode
        if spec.get('kungfu_query') and values.get('name'):
            kungfu = assets.find_kungfu(values['name'])
            if kungfu: values['name'] = kungfu['name']
        if method == 'rank_statistical':
            options = {'帮会排行': GUILD_RANK_OPTIONS, '阵营排行': CAMP_RANK_OPTIONS, '其他排行': OTHER_RANK_OPTIONS}.get(spec['name'], {name:name for name in RANK_NAMES})
            name = values['name']
            values['name'] = options.get(name, name)
            if values['name'] not in options.values(): raise GameUsageError()
        if method == 'equipment' and values.get('kind', '秘境挑战') not in {'秘境挑战','竞技对抗','休闲','通用'}: raise GameUsageError('装备类型可选秘境挑战、竞技对抗、休闲、通用。')
        if method == 'shitu' and 'label' in values:
            values['label'] = {'1':1,'2':2,'收徒':1,'拜师':2}.get(str(values['label']))
            if values['label'] is None: raise GameUsageError()
        values.update(spec.get('fixed', {}))
        return values

    async def run(self, key, args, event):
        spec = GAME_MAP[key]
        if spec.get("local"): return await self.local.run(key, args, event)
        if spec.get("play"): return await self.play.run(key, args, event)
        default_server = self.settings.default_server
        if self.bindings:
            default_server = await self.bindings.server(event) or default_server
            if spec.get('role_query') and not args:
                role = await self.bindings.role(event)
                if role: args = role['server'] + ' ' + role['name']
            elif spec.get('role_query') and len(args.split()) == 1:
                matches = [row for row in await self.bindings.list(event) if row['name'] == args]
                if len(matches) == 1: args = matches[0]['server'] + ' ' + args
        values = self.parse(spec, args, default_server)
        result = await getattr(self.data, spec['method'])(**values)
        return await self.reply(result)

    async def reply(self, result):
        if not isinstance(result, dict): raise TypeError('Invalid game result')
        if str(result.get('code')) != '200': return result.get('msg') or '暂无相关记录。'
        data, page = result.get('data'), result.get('temp')
        if page:
            if not isinstance(data, dict): raise TypeError('Invalid page data')
            menu = None
            if page == 'team' and data.get('team'):
                team = data['team'];tid = team['id']
                menu = MenuReply(team['name'], (Button('报名', f'报名 {tid}'), Button('换角色 / 心法', f'选择报名 {tid} 角色'), Button('取消报名', f'取消报名 {tid}'), Button('刷新团队', f'团队 {tid}'), Button('团队名单', f'团队名单 {tid}')))
            return ImageReply(await self.renderer.render(page, data), menu=menu)
        if isinstance(data, str): return data
        if isinstance(data, list) and all(isinstance(part, dict) and part.get('type') in {'text', 'image'} for part in data):
            return MessageParts(data[:12])
        if not data: return '暂无相关记录。'
        raise TypeError('Missing game result formatter')
