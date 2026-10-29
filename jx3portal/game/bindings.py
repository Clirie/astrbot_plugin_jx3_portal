import json
import hashlib
from pathlib import Path

"""只保存主动绑定的角色与区服；角色归用户，区服归会话。"""
class Bindings:
    def __init__(self, sql): self.sql = sql

    async def initialize(self):
        await self.sql.execute('CREATE TABLE IF NOT EXISTS portal_roles (owner TEXT NOT NULL, server TEXT NOT NULL, name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (owner,server,name))')
        await self.sql.execute('CREATE TABLE IF NOT EXISTS portal_servers (session TEXT PRIMARY KEY, server TEXT NOT NULL)')

    def owner(self, event):
        platform = str(event.get_platform_name()) if hasattr(event, 'get_platform_name') else str(event.unified_msg_origin).split(':',1)[0]
        if platform in {'aiocqhttp','qq_official','qq','onebot','onebot_v11'}: platform='qq'
        return platform + ':' + str(event.get_sender_id())

    async def server(self, event):
        row = await self.sql.fetch_one('SELECT server FROM portal_servers WHERE session=?', (str(event.unified_msg_origin),))
        return row['server'] if row else ''

    async def role(self, event):
        return await self.sql.fetch_one('SELECT rowid AS id,server,name FROM portal_roles WHERE owner=? ORDER BY active DESC,server,name LIMIT 1', (self.owner(event),))

    async def list(self, event):
        roles = await self.sql.fetch_all('SELECT server,name,active FROM portal_roles WHERE owner=? ORDER BY active DESC,server,name', (self.owner(event),))
        for role in roles: role['ref'] = hashlib.sha256(json.dumps([role['server'],role['name']],ensure_ascii=False).encode()).hexdigest()[:16]
        for role in roles: role['choice'] = role['name'] + ('（'+role['server']+'）' if sum(r['name']==role['name'] for r in roles)>1 else '')
        return roles

    async def bind(self, event, server, name):
        owner = self.owner(event)
        async with self.sql.transaction():
            await self.sql.execute('UPDATE portal_roles SET active=0 WHERE owner=?', (owner,))
            await self.sql.execute('INSERT INTO portal_roles (owner,server,name,active) VALUES (?,?,?,1) ON CONFLICT(owner,server,name) DO UPDATE SET active=1', (owner, server, name))

    async def unbind(self, event, server, name):
        return await self.sql.execute_affected('DELETE FROM portal_roles WHERE owner=? AND server=? AND name=?', (self.owner(event), server, name))

    async def import_previous(self, directory):
        await self.sql.execute('CREATE TABLE IF NOT EXISTS portal_migrations (name TEXT PRIMARY KEY)')
        if await self.sql.fetch_one('SELECT name FROM portal_migrations WHERE name=?', ('json-bindings-v1',)): return
        role_path, server_path = Path(directory)/'role_binding.json', Path(directory)/'server_binding.json'
        roles = json.loads(role_path.read_text()) if role_path.is_file() else {}
        servers = json.loads(server_path.read_text()) if server_path.is_file() else {}
        async with self.sql.transaction():
            for uid, rows in roles.items():
                for index, row in enumerate(rows):
                    if row.get('server') and row.get('name'):
                        await self.sql.execute('INSERT OR IGNORE INTO portal_roles (owner,server,name,active) VALUES (?,?,?,?)', ('qq:'+str(uid), row['server'], row['name'], 1 if index==0 else 0))
            for session, row in servers.items():
                if row.get('server'):
                    await self.sql.execute('INSERT OR IGNORE INTO portal_servers (session,server) VALUES (?,?)', (session, row['server']))
            await self.sql.execute('INSERT INTO portal_migrations (name) VALUES (?)', ('json-bindings-v1',))
