import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from jx3portal.settings import Settings, SettingsError
from jx3portal.aliases import ServerAliasService
from jx3portal.paid import PaidService, PaidError
from jx3portal.event_push import EventPushService
from jx3portal.commands import CommandService
from jx3portal.cache import TTLCache
from jx3portal.telemetry import Telemetry
from jx3portal.jx3box import JX3BOXClient
from jx3portal.storage import write_json


def test_settings_save_failure_rolls_back_memory_and_secret(tmp_path):
    config={'default_server':'梦江南','jx3api_token':'old'}
    settings=Settings(config,tmp_path,lambda:False)
    with pytest.raises(SettingsError):settings.save({'default_server':'唯我独尊','jx3api_token':'new','jx3api_timeout':12})
    assert config=={'default_server':'梦江南','jx3api_token':'old'}
    with pytest.raises(SettingsError):settings.clear_secret('jx3api_token')
    assert settings.token=='old'


def test_command_overrides_failure_keeps_previous_settings(tmp_path):
    settings=Settings({},tmp_path)
    settings.save_command_overrides({'disabled':['sand']})
    with patch.object(settings,'_atomic_write_json',side_effect=OSError('disk full')):
        with pytest.raises(OSError):settings.save_command_overrides({'disabled':['gold']})
        with pytest.raises(OSError):settings.reset_command_overrides()
    assert settings.command_overrides()['disabled']==['sand']
    assert Settings({},tmp_path).command_overrides()['disabled']==['sand']


def test_alias_save_failure_keeps_previous_aliases(tmp_path):
    aliases=ServerAliasService(tmp_path);before=aliases.summary()
    with patch('jx3portal.aliases._atomic_write',side_effect=OSError('disk full')):
        with pytest.raises(OSError):aliases.save([{'server':'梦江南','aliases':['测试双梦']}])
    assert aliases.summary()==before
    assert ServerAliasService(tmp_path).summary()==before


def test_atomic_json_failed_replace_preserves_file(tmp_path):
    path=tmp_path/'state.json';write_json(path,{'old':1})
    with patch('os.replace',side_effect=OSError('disk full')):
        with pytest.raises(OSError):write_json(path,{'new':2})
    assert json.loads(path.read_text())=={'old':1}
    assert list(tmp_path.iterdir())==[path]


def test_paid_code_and_entitlement_commit_together(tmp_path):
    settings=Settings({'paid_enabled':True},tmp_path);paid=PaidService(settings,tmp_path)
    code=paid.generate_codes(days=30,count=1)[0]['code']
    with patch('jx3portal.paid._atomic_write',side_effect=OSError('disk full')):
        with pytest.raises(PaidError):paid.activate('test:group:1',code)
    assert not paid.status('test:group:1')['active']
    assert PaidService(settings,tmp_path)._codes[0]['used_at'] is None
    paid.activate('test:group:1',code)
    loaded=PaidService(settings,tmp_path)
    assert loaded.status('test:group:1')['active']
    with pytest.raises(PaidError):loaded.activate('test:group:2',code)
    assert set(json.loads((tmp_path/'paid_state.json').read_text()))=={'groups','codes'}


def test_paid_reads_old_files_without_overwriting_them(tmp_path):
    expiry=time.time()+86400
    old={'groups':[{'session_id':'test:group:old','expires_at':expiry,'active':True}]}
    write_json(tmp_path/'paid_groups.json',old)
    write_json(tmp_path/'activation_codes.json',{'codes':[{'code':'JX3-OLD','days':3}]})
    settings=Settings({},tmp_path);paid=PaidService(settings,tmp_path)
    assert paid.status('test:group:old')['active']
    paid.activate('test:group:new','JX3-OLD')
    assert PaidService(settings,tmp_path).status('test:group:new')['active']
    assert json.loads((tmp_path/'paid_groups.json').read_text())==old


def test_paid_validation_happens_before_mutation(tmp_path):
    paid=PaidService(Settings({},tmp_path),tmp_path)
    paid.add_group(session_id='test:1',note='original')
    with pytest.raises(PaidError):paid.update_group(session_id='test:1',note='changed',expires_at='bad date')
    assert paid.status('test:1')['note']=='original'


def test_corrupt_paid_file_is_not_silently_overwritten(tmp_path):
    path=tmp_path/'activation_codes.json';path.write_text('broken')
    with pytest.raises(PaidError):PaidService(Settings({},tmp_path),tmp_path)
    assert path.read_text()=='broken'
    assert not (tmp_path/'paid_state.json').exists()


def test_subscription_edit_preserves_inherited_actions(tmp_path):
    settings=Settings({'event_push_sessions':['test:group'],'event_push_actions':[2001,2002,2003]},tmp_path)
    events=EventPushService(settings,SimpleNamespace(),data_dir=tmp_path)
    events.set_action('test:group',2002,False)
    assert events.is_subscribed('test:group',2001) and events.is_subscribed('test:group',2003)
    assert not events.is_subscribed('test:group',2002)
    events.set_action('new:group',2002,True)
    assert events.session_actions('new:group')=={2002}
    reloaded=EventPushService(settings,SimpleNamespace(),data_dir=tmp_path)
    assert reloaded.session_actions('test:group')=={2001,2003}


def test_subscription_write_failure_not_reported_as_success(tmp_path):
    settings=Settings({'event_push_actions':[2001]},tmp_path)
    events=EventPushService(settings,SimpleNamespace(),data_dir=tmp_path)
    events.set_action('test:1',2001,True)
    with patch('jx3portal.event_push.write_json',side_effect=OSError('disk full')):
        with pytest.raises(ValueError):events.configure('test:1','开服状态','关闭')
    assert events.is_subscribed('test:1',2001)
    assert EventPushService(settings,SimpleNamespace(),data_dir=tmp_path).is_subscribed('test:1',2001)


def test_news_unsubscribed_during_render_is_not_sent(tmp_path):
    async def run():
        settings=Settings({'event_push_actions':[2002],'event_push_sessions':['test:1']},tmp_path)
        release=asyncio.Event();send=AsyncMock()
        async def preview(*args):await release.wait();return ['/tmp/news.jpg']
        events=EventPushService(settings,SimpleNamespace(),send,tmp_path,preview_callback=preview)
        await events.handle_payload(json.dumps({'action':2002,'detail':{'title':'news','url':'https://jx3.com/news'}}))
        events.set_all('test:1',False);release.set()
        await asyncio.gather(*events._news_tasks)
        send.assert_not_awaited();await events.close()
    asyncio.run(run())


def test_reload_requests_coalesce_and_close_cancels_pending_work(tmp_path):
    async def run():
        events=EventPushService(Settings({},tmp_path),SimpleNamespace(),data_dir=tmp_path)
        entered=asyncio.Event()
        async def reload():entered.set();await asyncio.Event().wait()
        events.reload=reload
        events.request_reload();task=events._reload_task;events.request_reload()
        assert events._reload_task is task
        await entered.wait();await events.close()
        assert task.cancelled()
        events.request_reload();assert events._reload_task is task
    asyncio.run(run())


def test_menu_configuration_and_permissions_share_catalog(tmp_path):
    settings=Settings({},tmp_path);commands=CommandService(settings,None,None,None,TTLCache(),Telemetry())
    event=SimpleNamespace(is_admin=lambda:False)
    shown={item['name'] for group in commands._help_categories(event) for item in group['items']}
    assert '物价' not in shown and '日常' in shown
    settings.save({'jx3api_token':'test'})
    shown={item['name'] for group in commands._help_categories(event) for item in group['items']}
    assert '物价' in shown and '资历' not in shown
    assert next(c for c in commands.public_catalog() if c['key']=='trade')['available']
    settings.save_command_overrides({'permissions':{'trade':'admin'}})
    assert '物价' not in {item['name'] for group in commands._help_categories(event) for item in group['items']}
    async def run():
        assert '管理员' in await commands.run('trade',event,'小霜')
        assert '管理员' in await commands._cmd_help('物价',event)
    asyncio.run(run())


def test_total_query_deadline_spans_multiple_steps(tmp_path):
    async def run():
        commands=CommandService(Settings({},tmp_path),None,None,None,TTLCache(),Telemetry())
        commands.query_timeout=.04
        async def slow(*args):await asyncio.sleep(.025);await asyncio.sleep(.025);return 'late'
        commands._cmd_exam=slow
        event=SimpleNamespace(is_admin=lambda:False)
        started=time.monotonic();response=await commands.run('exam',event,'question')
        assert response=='查询超时，请稍后再试。' and time.monotonic()-started<.1
    asyncio.run(run())


def test_box_zero_ttl_and_explicit_clear_are_effective(tmp_path):
    async def run():
        settings=Settings({'jx3box_cache_ttl':0},tmp_path)
        http=SimpleNamespace(request_json=AsyncMock(return_value=SimpleNamespace(data={'code':0,'data':[]})))
        cache=TTLCache();box=JX3BOXClient(settings,http,cache,Telemetry())
        await box._item_groups();await box._item_groups()
        assert http.request_json.await_count==2
        settings.save({'jx3box_cache_ttl':300})
        await box._item_groups();await box._item_groups();assert http.request_json.await_count==3
        box.clear_local_cache();await box._item_groups();assert http.request_json.await_count==4
        await cache.close()
    asyncio.run(run())


def test_macro_uses_current_ranking_and_article_endpoints(tmp_path):
    async def run():
        box=JX3BOXClient(Settings({},tmp_path),None,TTLCache(),Telemetry())
        box._request=AsyncMock(side_effect=[[{'pid':42}],{'ID':42,'post_title':'宏示例','author':'作者','post_meta':{'data':[{'name':'一键宏','macro':'/cast 示例技能'}]}}])
        result=await box.macros('花间游')
        calls=box._request.await_args_list
        assert calls[0].args[:2]==('auction','/api/macro/tops')
        assert calls[1].args[:2]==('cms','/api/cms/post/42')
        assert result['macros'][0]['macro']=='/cast 示例技能'
        assert result['url'].endswith('/42')
    asyncio.run(run())
