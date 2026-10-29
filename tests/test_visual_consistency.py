import asyncio,random
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from test_game_features import service,event
from jx3portal.game.equipment import equipment_view
from jx3portal.game.tarot import TarotDeck,draw_cards,load_deck,select_reading,tarot_reading
from jx3portal.game.horoscope import HoroscopeService,normalize_page
from jx3portal.game.market_card import market_card
from jx3portal.http import NetworkError

FIXTURE=(Path(__file__).parent/'fixtures/horoscope-20261026-aries.html').read_text()


def test_equipment_data_and_parallel_optional_portrait(tmp_path):
    async def run():
        commands=service(tmp_path);started=set();ready=asyncio.Event()
        async def request(path,params,**kwargs):
            started.add(path)
            if len(started)==2:ready.set()
            await ready.wait()
            if path=='/card/cached':return {'serverName':'唯我独尊','roleName':'剑客','showAvatar':'https://example.com/portrait.png','cacheTime':1793000000}
            return {'serverName':'唯我独尊','roleName':'剑客','equipScore':900000,'panelList':[{'name':'会心等级','value':30000,'percent':42.93},{'name':'加速等级','value':9073,'percent':4.32}], 'equipList':[{'itemIndex':10,'itemName':'测试裤子','itemPlus':'精简','iconId':12,'mountDiamond':[{'itemName':'五行石（七级）'},{'itemName':'五行石（七级）'}],'minEnchant':{'itemName':'风语·裤·铸（无双）'}}]}
        commands.api.request=request
        result=await asyncio.wait_for(commands.game.data.equipment('唯我独尊','剑客'),.5);data=result['data']
        assert data['portrait'].endswith('portrait.png') and len(started)==2
        assert [row['value'] for row in data['sections'][0]['items']]==['42.93%','9,073']
        assert data['equipment'][0]['itemPlus']=='精简' and data['equipment'][0]['stones']=='七级 ×2'
        assert data['equipment'][0]['enchants'][0]['name']=='风语·裤·铸（无双）'
        async def failed_card(path,params,**kwargs):
            if path=='/card/cached':raise NetworkError('unavailable')
            return {'serverName':'唯我独尊','roleName':'剑客','equipScore':1}
        commands.api.request=failed_card
        assert 'portrait' not in (await commands.game.data.equipment('唯我独尊','剑客'))['data']
        async def wrong_card(path,params,**kwargs):
            if path=='/card/cached':return {'serverName':'唯我独尊','roleName':'另一人','showAvatar':'https://example.com/wrong.png'}
            return {'serverName':'唯我独尊','roleName':'剑客'}
        commands.api.request=wrong_card
        assert 'portrait' not in (await commands.game.data.equipment('唯我独尊','剑客'))['data']
        await commands.game.close()
    asyncio.run(run())


def test_tarot_orientation_topics_and_recent_draws():
    for card in load_deck():
        for reverse in [False,True]:
            for topic in ['综合','感情','求物','事业','学业']:
                selected=select_reading(dict(card,reversed_card=reverse),topic)
                assert len(selected['reading'])>5 and not selected['keywords']
                parts=selected['reading'].rstrip('。').split('，')
                assert 1<=len(parts)<=3 and all(part in card['reversed' if reverse else 'upright'] for part in parts)
                if topic=='求物':assert all(word not in selected['reading'] for word in ['恋爱','爱情','婚姻','学业','事业','职场'])
    card=next(row for row in load_deck() if row['id']=='major_15')
    assert '挣脱' in select_reading(dict(card,reversed_card=True),'综合')['reading']
    now=[0];deck=TarotDeck(random.Random(19),lambda:now[0]);previous=[]
    for _ in range(200):
        draw=deck.draw(1,'qq:alice')[0]
        assert draw['id'] not in previous[-6:]
        previous.append(draw['id'])
    assert len(set(previous))>65
    deck.draw(1,'qq:bob');assert set(deck.recent)=={'qq:alice','qq:bob'}
    now[0]=1801;deck.draw(1,'qq:alice');assert len(deck.recent['qq:alice'][1])==1 and 'qq:bob' not in deck.recent
    assert len({c['id'] for c in deck.draw(3,'qq:alice')})==3


def test_tarot_unknown_question_keeps_reading():
    result=asyncio.run(tarot_reading('事情会怎样发展',1))
    assert result['code']==200 and result['data']['topic_key']=='综合'


def test_horoscope_source_date_sign_and_original_scale():
    data=normalize_page(FIXTURE,'aries',date(2026,10,26))
    assert data['scale']==5 and [data['overview']['score']]+[row['score'] for row in data['sections']]==[3,3,2,4]
    assert data['source']=='科技紫微网' and '工作需要' in data['overview']['text']
    assert any(row['value']=='0' for row in data['lucky'])
    with pytest.raises(ValueError):normalize_page(FIXTURE,'aries',date(2026,10,27))
    with pytest.raises(ValueError):normalize_page(FIXTURE,'taurus',date(2026,10,26))
    with pytest.raises(ValueError):normalize_page(FIXTURE.replace('★★★☆☆','★★★'),'aries',date(2026,10,26))


def test_horoscope_coalesces_requests_and_refreshes_next_day():
    async def run():
        today=[date(2026,10,26)];clock=[10];service=HoroscopeService(None,lambda:clock[0],lambda:today[0]);calls=[]
        async def fetch(sign,day):
            calls.append((sign,day));await asyncio.sleep(0)
            return FIXTURE.replace('2026-10-26',day.isoformat())
        service._fetch=fetch
        rows=await asyncio.gather(*(service.data('aries') for _ in range(6)))
        assert len(calls)==1 and all(row['date']=='2026.10.26' for row in rows)
        today[0]=date(2026,10,27);row=await service.data('aries')
        assert len(calls)==2 and row['date']=='2026.10.27'
        clock[0]+=1801;service._fetch=AsyncMock(return_value=FIXTURE)
        assert await service.data('aries') is None
        assert await service.data('aries') is None and service._fetch.await_count==1
        today[0]=date(2026,10,28);service._fetch=fetch
        assert (await service.data('aries'))['date']=='2026.10.28'
    asyncio.run(run())


def test_new_game_functions_do_not_count_unobtained_and_keep_units(tmp_path):
    async def run():
        commands=service(tmp_path)
        commands.api.event_records=AsyncMock(return_value=[{'event':'甲','level':2,'status':1},{'event':'甲','level':2,'status':1},{'event':'乙','level':2,'status':0},{'event':'丙','level':1,'status':0}])
        result=await commands.game.data.event_count('唯我独尊','剑客')
        assert result['data']['rows']==[['绝世',1,1],['普通',0,1],['宠物',0,0]]
        commands.api.request=AsyncMock(return_value={'name':'某药','items':[{'name':'材料','type':'trade','quantity':2,'price':{'lowestPrice':12000,'updatedAt':1793000000}}],'costVigor':10,'createItemMin':2,'createItemMax':3,'total':{'lowestTotal':24000}})
        result=await commands.game.data.recipe('唯我独尊','某药')
        assert result['data']['rows'][0][-2:]==['1.20','2.40']
        assert ('产出','2–3') in result['data']['facts']
        await commands.game.close()
    asyncio.run(run())


def test_new_team_actions_and_unbind_are_scoped(tmp_path):
    async def run():
        commands=service(tmp_path);game=commands.game;await game.initialize();admin=event(admin=True)
        await game.run('team_create','测试 10',admin);tid=str((await game.local.team.list_teams(admin.unified_msg_origin))[0]['id'])
        assert '管理员' in await game.run('team_rename',tid+' 新名',event())
        assert '没有找到' in await game.run('team_rename',tid+' 新名',event(group='b',admin=True))
        assert '新名' in await game.run('team_rename',tid+' 新名',admin)
        assert '空位 10' in await game.run('team_count',tid,event())
        await game.bindings.bind(event(),'唯我独尊','甲')
        await game.bindings.bind(event(user='bob'),'唯我独尊','乙')
        assert '已解绑 1' in await game.run('role_clear','',event())
        assert not await game.bindings.list(event()) and len(await game.bindings.list(event(user='bob')))==1
        await game.close()
    asyncio.run(run())


def test_market_text_card_keeps_variant_alias_and_fields():
    text=market_card({'name':'十五夜观灯·南涧·标准','alias':'蓝观灯','date':'2024-02-22','retail':280,'unbound_duration':'7天','bound_duration':'21天'}, {'1':'十五夜观灯·封霜·豪华｜白观灯'})
    for value in ['回复序号','封霜·豪华（白观灯）','官方售价：280元','不绑定限时：7天','绑定限时：21天']:assert value in text
    assert '物价选' not in text
