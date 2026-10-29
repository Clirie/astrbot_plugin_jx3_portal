import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from test_game_features import service, event


def test_group_owner_admin_member_and_missing_identity(tmp_path):
    async def run():
        commands=service(tmp_path);manager=commands.game.local.manager
        assert await manager._permission_error(event(user='owner')) is None
        assert await manager._permission_error(event(admin=True)) is None
        assert '仅群主' in await manager._permission_error(event(user='member'))
        official=event(user='owner');official.get_platform_name=lambda:'qq_official';official.message_obj=SimpleNamespace(group=SimpleNamespace(group_owner=None,group_admins=[]))
        assert '未提供群管理身份' in await manager._permission_error(official)
        official.get_group.assert_not_called()
        official.message_obj.group.group_owner='owner'
        assert await manager._permission_error(official) is None
        official.message_obj.group.group_owner=None;official.is_admin=lambda:True
        assert await manager._permission_error(official) is None
        await commands.game.close()
    asyncio.run(run())
