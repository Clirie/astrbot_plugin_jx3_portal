import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from jx3portal.articles import ArticleService, canonical_url
from PIL import Image


def test_official_news_and_events_capture_original_page_and_cache(tmp_path):
    async def run():
        path=tmp_path/'snapshot.jpg';Image.new('RGB',(1200,800),'white').save(path)
        expected=[str(path)]
        callback=AsyncMock(return_value=expected);svc=ArticleService(None,None,SimpleNamespace(render_callback=callback))
        row={'title':'外观上新','url':'https://jx3.xoyo.com/show-2458-7549-1.html'}
        assert await svc.from_news(row,compact=True)==expected
        assert callback.await_args.args[2]['snapshot_url']==row['url']
        assert await svc.from_event(2002,row)==expected
        callback.assert_awaited_once()
        assert await svc.from_event(2002,{'url':'http://127.0.0.1/'})==[]
        await svc.close()
    asyncio.run(run())


def test_spa_article_identity_preserves_id():
    assert canonical_url('https://jx3.xoyo.com/index/#/article-details?kid=1')!=canonical_url('https://jx3.xoyo.com/index/#/article-details?kid=2')


def test_announcements_use_ink_for_query_and_push(tmp_path):
    async def run():
        row={'title':'更新公告','url':'https://jx3.xoyo.com/announce/gg.html?id=1','content':'<h2>更新内容</h2><p>正文</p>'}
        svc=ArticleService(SimpleNamespace(announce=AsyncMock(return_value=[row])),None,None)
        svc.render_content=AsyncMock(return_value=['/tmp/ink.jpg']);svc.from_news=AsyncMock()
        assert await svc.from_announcement(row)==['/tmp/ink.jpg']
        assert await svc.from_event(2003,{'url':row['url']})==['/tmp/ink.jpg']
        assert svc.render_content.await_count==2
        svc.from_news.assert_not_awaited()
        await svc.close()
    asyncio.run(run())


def test_dom_pages_do_not_split_paragraphs_images_or_detach_headings():
    from jx3portal.official_snapshot import page_ranges
    blocks=[{'top':0,'bottom':100,'heading':False},{'top':130,'bottom':750,'heading':False},{'top':780,'bottom':850,'heading':True},{'top':880,'bottom':1450,'heading':False},{'top':1480,'bottom':3300,'heading':False}]
    pages=page_ranges(blocks,3330)
    assert pages[0][0]==0 and pages[-1][1]==3330
    assert all(a[1]==b[0] for a,b in zip(pages,pages[1:]))
    cuts=[end for _,end in pages[:-1]]
    assert all(not block['top']<cut<block['bottom'] for cut in cuts for block in blocks)
    assert all(not 780<cut<1450 for cut in cuts)
    assert any(top<=1480 and bottom>=3300 for top,bottom in pages)


def test_snapshot_pages_keep_resolution_and_order(tmp_path):
    import io
    from jx3portal.official_snapshot import package_pages
    from jx3portal.local_render import LocalRenderService
    raw=[]
    for color in ['red','blue']:
        buf=io.BytesIO();Image.new('RGB',(1080,1200),color).save(buf,'JPEG');raw.append(buf.getvalue())
    paths=LocalRenderService._save_pages(package_pages(raw,{'pages':2}),tmp_path)
    assert len(paths)==2
    with Image.open(paths[0]) as image:
        assert image.width==1080 and image.getpixel((500,500))[0]>240
    with Image.open(paths[1]) as image: assert image.getpixel((500,500))[2]>240


def test_news_pages_are_bound_to_reader_and_do_not_refetch(tmp_path):
    from test_game_features import service,event
    async def run():
        command=service(tmp_path);paths=[]
        for i in range(5):
            path=tmp_path/f'{i}.jpg';Image.new('RGB',(100,100),'white').save(path);paths.append(str(path))
        command.articles=SimpleNamespace(from_news=AsyncMock(return_value=paths))
        command.api.news=AsyncMock(return_value=[{'title':'新闻正文','url':'https://jx3.xoyo.com/show-1.html'}])
        user=event();first=await command._cmd_news('',user)
        assert first.path==paths[0] and first.extra_paths==(paths[1],)
        assert first.menu.buttons[0].command=='新闻 第3页'
        other=await command._cmd_news('第3页',event(user='other'));assert isinstance(other,str)
        next_page=await command._cmd_news('第3页',user)
        assert next_page.path==paths[2] and next_page.extra_paths==(paths[3],)
        command.api.news.assert_awaited_once();command.articles.from_news.assert_awaited_once()
        assert await command._cmd_news('第99页',user)=='没有这一页。'
        await command.game.close();await command.cache.close()
    asyncio.run(run())


def test_push_continuation_uses_the_pushed_article_not_latest_news(tmp_path):
    from test_game_features import service,event
    from jx3portal.commands import _session_id
    from jx3portal.cache import TTLCache
    async def run():
        command=service(tmp_path);user=event();paths=[]
        for i in range(4):
            path=tmp_path/f'{i}.jpg';path.write_bytes(b'image');paths.append(str(path))
        command.events=SimpleNamespace(news_readings=TTLCache());command.api.news=AsyncMock()
        command.events.news_readings.set('push',_session_id(user),{'paths':paths,'caption':'昨天的推送'},1200)
        reply=await command._cmd_news('续看',user)
        assert reply.path==paths[2] and reply.caption=='昨天的推送'
        command.api.news.assert_not_awaited()
        assert (await command._cmd_news('第1页',user)).path==paths[0]
        await command.game.close();await command.cache.close()
    asyncio.run(run())
