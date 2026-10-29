import asyncio
import io
import json
import time
from email.utils import formatdate
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from PIL import Image
from jx3portal.weibo import ACCOUNTS, AUTHORIZED_UID, WeiboError, WeiboService, author_posts, article_blocks, rich_text
from jx3portal.event_push import EventPushService
from jx3portal.replies import ImageReply, MessageParts
from jx3portal.settings import Settings
from test_game_features import service, event


def post(id, uid='7056235331', created=1000):
    return {'id':id,'mblogid':'abc'+str(id),'created_at':formatdate(created,usegmt=True),'user':{'id':int(uid),'screen_name':ACCOUNTS[uid]},'text_raw':'完整正文'}


def make_service(tmp_path):
    settings=Settings({'event_push_enabled':True,'event_push_actions':[2001]},tmp_path)
    events=EventPushService(settings,None,data_dir=tmp_path)
    svc=WeiboService(tmp_path,SimpleNamespace(_image=AsyncMock(return_value={'src':'data:image/png;base64,x'})),SimpleNamespace(render=AsyncMock(return_value='/tmp/weibo.jpg')),AsyncMock(),events)
    events.on_change=svc.sync_targets
    return svc


def test_only_target_author_and_no_ads_or_pinned():
    rows=[post(1),dict(post(2),isTop=True),dict(post(3),isAd=True),post(4,'2046281757')]
    assert [p['id'] for p in author_posts({'ok':1,'data':{'list':rows}},'7056235331')]==[1]
    with pytest.raises(WeiboError):author_posts({'ok':-100},'7056235331')


def test_authorized_login_is_checked_before_reading_posts(tmp_path):
    async def run():
        svc=make_service(tmp_path);svc._request=AsyncMock()
        svc.auth_path.write_text(json.dumps({'account_uid':'different','cookies':[]}))
        with pytest.raises(WeiboError):await svc.posts('7056235331')
        svc._request.assert_not_awaited()
        svc.auth_path.write_text(json.dumps({'account_uid':AUTHORIZED_UID,'cookies':[{'domain':'.weibo.com','name':'SUB','value':'test'},{'domain':'.weibo.cn','name':'SUB','value':'do-not-use'}]}))
        svc._request.return_value='<script>uid = "different";</script>'
        with pytest.raises(WeiboError):await svc.verify()
        assert svc.headers=={}
        svc._request.return_value='<script>uid = "7989517242";</script>'
        await svc.verify();assert svc.headers['Cookie']=='SUB=test'
        await svc.close()
    asyncio.run(run())


def test_full_text_retweet_and_picture_limit(tmp_path):
    async def run():
        svc=make_service(tmp_path);p=post(1);p['isLongText']=True;p['retweeted_status']=dict(post(2),isLongText=True)
        p['pic_infos']={str(i):{'large':{'url':f'https://wx1.sinaimg.cn/large/{i}.jpg'}} for i in range(24)}
        full='完整正文'*200+'\n下一段'
        svc._request=AsyncMock(return_value={'ok':1,'data':{'longTextContent':full.replace('\n','<br>')}})
        view=await svc.view(p)
        assert view['text']==full and view['quoted']['text']==full
        assert len(view['pictures'])==24 and view['remaining_images']==0
        detail=await svc.view(p,True)
        assert detail['text']==full and detail['quoted']['text']==full and detail['detail'] is True
        reply=await svc.reply(p)
        assert isinstance(reply,ImageReply) and 'https://weibo.com/7056235331/abc1' in reply.caption
        await svc.close()
    asyncio.run(run())


def test_article_semantics_and_detail_flag(tmp_path):
    async def run():
        content='<h2>新赛季</h2><p>调整<strong>完整文字</strong></p><script>malicious()</script><img src="http://internal/">'
        assert article_blocks('<p><strong>调整事项</strong></p>')==[{'text':'调整事项','heading':True}]
        assert article_blocks(content)==[{'text':'新赛季','heading':True},{'text':'调整 完整文字','heading':False}]
        svc=make_service(tmp_path);p=post(1);p['page_info']={'object_type':'article','object_id':'1022:12345','content1':'标题'}
        svc._request=AsyncMock(return_value={'data':{'title':'标题','content':content}})
        view=await svc.view(p);assert view['article']['blocks']==[];svc._request.assert_not_awaited()
        detail=await svc.view(p,True);assert detail['detail'] is True and len(detail['article']['blocks'])==2
        assert svc._request.await_args.kwargs['article'] is True
        await svc.close()
    asyncio.run(run())


def test_initial_subscription_no_backfill_persistent_dedup_and_retry(tmp_path):
    async def run():
        svc=make_service(tmp_path);rows={uid:[post(1,uid)] for uid in ACCOUNTS}
        svc.posts=AsyncMock(side_effect=lambda uid,**kw:rows[uid]);svc.reply=AsyncMock(return_value=ImageReply('/tmp/test.jpg',caption='原文链接'))
        svc.events.set_action('qq:group:1',9001,True)
        await svc.poll_once();svc.send.assert_not_awaited()
        rows['7056235331'].insert(0,post(2,created=time.time()+1))
        svc.send.side_effect=RuntimeError('temporary failure')
        with pytest.raises(RuntimeError):await svc.poll_once()
        assert '2' not in svc.subscriptions['qq:group:1']['seen']['7056235331']
        svc.send.side_effect=None
        await svc.poll_once();assert svc.send.await_count==2
        assert svc.subscriptions['qq:group:1']['last']['bid']=='abc2'
        await svc.close()
        reopened=make_service(tmp_path);reopened.posts=AsyncMock(side_effect=lambda uid,**kw:rows[uid])
        await reopened.poll_once();reopened.send.assert_not_awaited()
        reopened.events.set_action('qq:group:1',9001,False);assert not reopened.subscriptions
        await reopened.close()
    asyncio.run(run())


def test_disable_while_rendering_stops_delivery_and_ignores_remote_event(tmp_path):
    async def run():
        svc=make_service(tmp_path);svc.events.set_action('qq:group:1',9001,True)
        svc.posts=AsyncMock(side_effect=lambda uid,**kw:[post(2,uid,time.time()+1)])
        async def render(p):
            svc.events.set_action('qq:group:1',9001,False)
            return ImageReply('/tmp/test.jpg',caption='原文链接')
        svc.reply=render
        await svc.poll_once();svc.send.assert_not_awaited();assert not svc.subscriptions
        await svc.events.handle_payload(json.dumps({'action':9001,'status':'success','detail':{'title':'injected'}}))
        assert svc.events.status()['received']==0
        await svc.close()
    asyncio.run(run())


def test_subscription_uses_existing_admin_switch(tmp_path):
    async def run():
        commands=service(tmp_path);svc=make_service(tmp_path);commands.events=svc.events
        assert '管理员' in await commands._cmd_event_push('微博动态 开启',event(admin=False))
        assert not svc.subscriptions
        assert await commands._cmd_event_push('微博动态 开启',event(admin=True))=='已开启微博动态推送。'
        assert 'qq:GroupMessage:a' in svc.subscriptions
        assert '已开 · 微博动态' in await commands._cmd_event_list('',event())
        assert await commands._cmd_event_push('微博动态 关闭',event(admin=True))=='已关闭微博动态推送。'
        assert not svc.subscriptions
        assert not commands.settings.weibo_configured
        (tmp_path/'weibo-auth.json').write_text('{}');assert commands.settings.weibo_configured
        await commands.game.close();await svc.close()
    asyncio.run(run())


def test_detail_last_post_links_and_original_image(tmp_path):
    async def run():
        svc=make_service(tmp_path);svc.verify=AsyncMock();svc._request=AsyncMock(return_value=dict(post(1),ok=1))
        svc.subscriptions['qq:group:1']={'last':{'uid':'7056235331','bid':'abc1'}}
        svc.reply=AsyncMock(return_value=ImageReply('/tmp/full.jpg'));svc.original_image=AsyncMock(return_value=ImageReply('/tmp/original.jpg'))
        assert (await svc.detail('','qq:group:1')).path=='/tmp/full.jpg'
        assert svc.reply.await_args.kwargs=={'detail':True}
        assert (await svc.detail('2','qq:group:1')).path=='/tmp/original.jpg'
        assert svc.original_image.await_args.args[1]==2
        assert (await svc.detail('https://weibo.com/7056235331/abc1 3','other')).path=='/tmp/original.jpg'
        assert '原微博链接' in await svc.detail('https://weibo.com/123/abc1','other')
        assert '没有微博' in await svc.detail('','other')
        await svc.close()
    asyncio.run(run())


def test_original_image_keeps_dimensions_and_picture_order(tmp_path):
    async def run():
        svc=make_service(tmp_path);p=post(1);p['pic_ids']=['b','a']
        p['pic_infos']={key:{'large':{'url':f'https://wx1.sinaimg.cn/large/{key}.jpg'},'original':{'url':f'https://wx1.sinaimg.cn/original/{key}.jpg'}} for key in ['a','b']}
        buf=io.BytesIO();Image.new('RGB',(1200,2200)).save(buf,format='PNG')
        svc.articles.http=SimpleNamespace(_request=AsyncMock(return_value=SimpleNamespace(data=buf.getvalue())))
        result=await svc.original_image(p,1)
        assert svc.articles.http._request.await_args.args[1].endswith('/original/b.jpg')
        with Image.open(result.path) as im:assert im.size==(1200,2200)
        assert __import__('pathlib').Path(result.path).read_bytes()==buf.getvalue()
        assert '2 张' in await svc.original_image(p,3)
        await svc.close()
    asyncio.run(run())


def test_added_official_account_does_not_backfill_existing_session(tmp_path):
    async def run():
        svc=make_service(tmp_path);svc.events.set_action('qq:group:1',9001,True)
        state=svc.subscriptions['qq:group:1'];state['since']=0;state['seen'].pop('1761587065')
        svc.sync_targets()
        since=svc.subscriptions['qq:group:1']['author_since']['1761587065']
        assert since>=time.time()-2
        rows={'1761587065':[post(1,'1761587065',since-60)],'2046281757':[],'7056235331':[]}
        svc.posts=AsyncMock(side_effect=lambda uid,**kw:rows[uid]);svc.reply=AsyncMock(return_value=ImageReply('/tmp/test.jpg',caption='官方微博'))
        await svc.poll_once();svc.send.assert_not_awaited()
        rows['1761587065'].insert(0,post(2,'1761587065',since+1))
        await svc.poll_once();assert svc.send.await_count==1
        assert svc.subscriptions['qq:group:1']['last']['uid']=='1761587065'
        reopened=make_service(tmp_path);reopened.sync_targets()
        assert reopened.subscriptions['qq:group:1']['author_since']['1761587065']==since
        await svc.close();await reopened.close()
    asyncio.run(run())


def test_rich_text_and_detail_returns_individual_images(tmp_path):
    text=rich_text('#苍生铸世# @微博抽奖平台 https://t.cn/abc <script>bad</script>')
    assert 'class="topic"' in text and 'class="mention"' in text and 'href="https://t.cn/abc"' in text
    assert '<script>' not in text and '&lt;script&gt;' in text
    async def run():
        svc=make_service(tmp_path);p=dict(post(1),ok=1,pic_ids=['a','b','c'])
        p['pic_infos']={key:{'original':{'url':'https://wx1.sinaimg.cn/original/'+key+'.jpg'}} for key in p['pic_ids']}
        svc.verify=AsyncMock();svc._request=AsyncMock(return_value=p)
        svc.original_image=AsyncMock(side_effect=lambda post,index:ImageReply('/tmp/'+str(index)+'.jpg'))
        svc.reply=AsyncMock()
        result=await svc.detail('https://weibo.com/7056235331/abc1','test')
        assert isinstance(result,MessageParts) and [p['path'] for p in result.parts]==['/tmp/1.jpg','/tmp/2.jpg','/tmp/3.jpg']
        svc.reply.assert_not_awaited()
        await svc.close()
    asyncio.run(run())


def test_latest_query_default_author_and_detail_context_without_subscribing(tmp_path):
    async def run():
        svc=make_service(tmp_path);p=post(7,'1761587065')
        svc.posts=AsyncMock(return_value=[p]);svc.reply=AsyncMock(return_value=ImageReply('/tmp/latest.jpg'))
        assert (await svc.latest('','qq:group:test')).path=='/tmp/latest.jpg'
        svc.posts.assert_awaited_with('1761587065',fresh=True)
        assert svc.cache.get('last-post','qq:group:test')=={'uid':'1761587065','bid':'abc7'}
        assert not svc.subscriptions and not svc.state_path.exists()
        svc.verify=AsyncMock();svc._request=AsyncMock()
        await svc.detail('','qq:group:test');svc._request.assert_not_awaited()
        await svc.latest('邓毅','qq:group:test');svc.posts.assert_awaited_with('7056235331',fresh=True)
        assert '官方／余玉贤／邓毅' in await svc.latest('不存在','test')
        await svc.close()
    asyncio.run(run())


def test_one_broken_author_or_group_does_not_block_other_deliveries(tmp_path):
    async def run():
        svc=make_service(tmp_path)
        for session in ['qq:group:bad','qq:group:good']:svc.events.set_action(session,9001,True)
        async def posts(uid,**kw):
            if uid=='1761587065':raise RuntimeError('author failure')
            return [post(2,uid,created=time.time()+1)] if uid=='7056235331' else []
        async def send(session,*args):
            if session.endswith('bad'):raise RuntimeError('delivery failure')
        svc.posts=AsyncMock(side_effect=posts);svc.reply=AsyncMock(return_value=ImageReply('/tmp/test.jpg',caption='原文链接'));svc.send=AsyncMock(side_effect=send)
        with pytest.raises(RuntimeError):await svc.poll_once()
        assert svc.subscriptions['qq:group:bad']['seen']['7056235331']==[]
        assert svc.subscriptions['qq:group:good']['seen']['7056235331']==['2']
        assert svc.reply.await_count==1
        await svc.close()
    asyncio.run(run())
