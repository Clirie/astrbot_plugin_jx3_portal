import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from bs4 import BeautifulSoup
from jx3portal.articles import clean_article
from jx3portal.game.equipment import equipment_view
from jx3portal.game.market_choices import MarketChoices, build_menu
from jx3portal.game.market_sources import AiJX3MarketSource, MarketArchive
from jx3portal.game.market_fusion import fuse_history


def test_choice_window_starts_on_menu_and_expiry_keeps_render_identity():
    now=[0];choices=MarketChoices(clock=lambda:now[0]);event=SimpleNamespace(unified_msg_origin='qq:group:a',get_sender_id=lambda:'alice')
    state=choices.start(event,{},'');state.options={'1':'蓝·标准'}
    now[0]=90;choices.arm(event,state)
    now[0]=99.9;assert choices.numeric_reply(event,'1')
    now[0]=100;assert not choices.numeric_reply(event,'1')
    assert choices.current(event,state,0)
    choices.start(event,{},'');assert not choices.current(event,state,0)
    choices.close()


def test_market_box_editions_precede_component_hair_and_clothes():
    rows=[{'name':'观灯·南涧·标准'},{'name':'观灯·南涧·衣'},{'name':'观灯·封霜·豪华'},{'name':'观灯·封霜·标准'},{'name':'观灯·南涧·豪华'}]
    assert list(build_menu(rows,'观灯').values())==['观灯·南涧·标准','观灯·南涧·豪华','观灯·封霜·标准','观灯·封霜·豪华','观灯·南涧·衣']


def test_article_keeps_body_and_promotes_actual_section_markers():
    body='<p>◎ 武学调整</p><p>1、霸刀</p><p>调整伤害为 1234 点。</p><p><span style="font-weight:700;color:red">重点内容</span>保留说明。</p><p>280 元的外观。</p><script>bad()</script>'
    clean=BeautifulSoup(''.join(clean_article(body,'https://jx3.xoyo.com/')),'html.parser')
    assert clean.h2.get_text()=='◎ 武学调整' and clean.h3.get_text()=='1、霸刀'
    assert clean.strong.get_text()=='重点内容' and '调整伤害为 1234 点。' in clean.get_text()
    assert clean.find('p',string='280 元的外观。') and not clean.find('script') and not clean.find(style=True)


def test_equipment_symbols_retain_refinement_and_gem_grade():
    rows=equipment_view({'equipList':[{'itemName':'测试','strengthLevel':4,'maxStrengthLevel':6,'mountDiamond':[{'itemName':'五行石（七级）'},{'itemName':'五行石（六级）'}]}]},'区服','名字')['equipment']
    assert rows[0]['refinement']==[True]*4+[False]*2
    assert [g['grade'] for g in rows[0]['gems']]==['七','六']
    assert equipment_view({'equipList':[{'itemName':'测试'}]},'区服','名字')['equipment'][0]['refinement']==[]


def test_history_reference_survives_detail_failure():
    async def run():
        from jx3portal.cache import TTLCache
        source=AiJX3MarketSource(None,TTLCache())
        async def request(service,path,params):
            if path.endswith('getGoodsDetail'):return None
            return [{'goodsName':'测试','tradeTime':'2024-01-01','price':100}]
        source._request=request
        result=await source.get('测试')
        assert result['series'][0]['points'][0]['value']==100
    asyncio.run(run())


def test_archive_restart_outage_correction_and_product_isolation(tmp_path):
    async def run():
        archive=MarketArchive(tmp_path)
        base={'label':'在售','points':[{'date':'2024-01-01','value':100}]}
        await archive.merge('外观甲','',[base])
        reopened=MarketArchive(tmp_path)
        result=await reopened.merge('外观甲','',[{'label':'在售','points':[{'date':'2024-01-01','value':110},{'date':'2026-10-27','value':160}]}])
        assert [p['value'] for p in result[0]['points']]==[110,160]
        assert await reopened.merge('外观甲','',[])==result
        assert await reopened.merge('外观乙','',[])==[]
        assert await reopened.merge('外观甲','唯我独尊',[])==[]
        fused=fuse_history(result+[{'label':'收购报价','points':[{'date':'2026-10-27','value':50}]}])
        assert fused['points'][-1]['value']==160
    asyncio.run(run())


def test_recent_quotes_merge_servers_before_selecting_rows():
    from jx3portal.game.market_design import prepare
    rows=[{'date':'2026-10-26','value':100,'kind':'buy','source':'交易','server':str(i)} for i in range(8)]
    rows += [{'date':'2026-10-25','value':95,'kind':'buy','source':'交易','server':'甲'},{'date':'2024-10-25','value':30,'kind':'done','source':'交易','server':'乙'}]
    result=prepare({'product':{'name':'测试'},'players':rows,'trend':{'series':[]}})
    assert [(r['date'],r['value']) for r in result['players']]==[('2026-10-25',95),('2026-10-26',100)]
    assert '8 服' in result['players'][-1]['server'] and not result['has_source']


def test_filled_history_marks_long_gap_without_filling_it():
    from jx3portal.game.market_design import make_fused_chart
    result=make_fused_chart([{'label':'在售','points':[{'date':'2024-01-01','value':100},{'date':'2024-01-02','value':110},{'date':'2026-10-01','value':200},{'date':'2026-10-02','value':210}]}])
    assert result['has_gaps'] and result['svg'].count('class="history-area"')==2
    assert len(result['points'])==4 and 'stroke-dasharray="2 4"' in result['svg']


def test_archive_new_contract_overwrites_legacy_daily_average(tmp_path):
    async def run():
        archive=MarketArchive(tmp_path)
        await archive.merge('外观','',[{'provider':'爱剑三','origin':'万宝楼','label':'万宝楼上架均价','points':[{'date':'2024-01-01','value':120}]}])
        result=await archive.merge('外观','',[{'provider':'爱剑三','origin':'万宝楼','label':'万宝楼上架均价','kind':'public_listing','points':[{'date':'2024-01-01','value':100}]}])
        assert len(result)==1 and result[0]['points'][0]['value']==100
    asyncio.run(run())
