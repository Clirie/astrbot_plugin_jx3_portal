"""Public JX3 accounts, using only the explicitly authorized web login."""
import asyncio
import contextlib
import json
import html
import logging
import re
import time
import traceback
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
from bs4 import BeautifulSoup
from .cache import TTLCache
from .http import HttpError
from .replies import ImageReply, MessageParts
from .storage import write_json

ACCOUNTS = {'1761587065':'剑网3官方微博', '2046281757':'剑网3余玉贤', '7056235331':'剑网3邓毅'}
AUTHORIZED_UID = '7989517242'
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
logger = logging.getLogger('astrbot.plugin.jx3_portal.weibo')


class WeiboError(HttpError):
    pass


def plain_text(text):
    soup = BeautifulSoup(str(text or ''), 'html.parser')
    for br in soup.find_all('br'): br.replace_with('\n')
    return soup.get_text().replace('\u200b','').strip()


def rich_text(text):
    """Keep Weibo's topic, mention and link hierarchy in a static preview."""
    pattern = r'https?://[^\s<>]+|#[^#\n]+#|@[\w\-·]+'
    parts, end = [], 0
    for match in re.finditer(pattern, text):
        parts.append(html.escape(text[end:match.start()]))
        value = match.group()
        kind = 'topic' if value.startswith('#') else 'mention' if value.startswith('@') else 'link'
        if kind == 'link': parts.append('<a class="link" href="'+html.escape(value,quote=True)+'">'+html.escape(value)+'</a>')
        else: parts.append('<span class="'+kind+'">'+html.escape(value)+'</span>')
        end = match.end()
    return ''.join(parts)+html.escape(text[end:])


def timestamp(post):
    return parsedate_to_datetime(post['created_at']).timestamp()


def author_posts(data, uid):
    if not isinstance(data, dict) or data.get('ok') != 1:
        raise WeiboError('微博暂时无法读取，请稍后再试。')
    rows = (data.get('data') or {}).get('list')
    if not isinstance(rows, list): raise WeiboError('微博暂时没有返回内容。')
    # Keep pinned posts: publication time and per-session seen ids control delivery.
    # The web endpoint also inserts recommendations and advertisements.
    rows = [p for p in rows if str((p.get('user') or {}).get('id')) == uid and not p.get('isAd')]
    return sorted(rows, key=timestamp, reverse=True)


def image_urls(post, original=False):
    urls = []
    infos = post.get('pic_infos') or {}
    for key in post.get('pic_ids') or infos:
        pic = infos.get(key,{})
        row = (pic.get('original') or pic.get('largest') or pic.get('large') or {}) if original else (pic.get('large') or pic.get('original') or {})
        if row.get('url'): urls.append(row['url'])
    page = post.get('page_info') or {}
    if not urls:
        picture = page.get('page_pic')
        if isinstance(picture, dict): picture = picture.get('url')
        if picture: urls.append(picture)
    return urls


def article_blocks(content):
    soup = BeautifulSoup(content, 'html.parser')
    for tag in soup.find_all(['script','style','iframe','video','object','embed']): tag.decompose()
    blocks = []
    for tag in soup.find_all(['h1','h2','h3','p','li','img']):
        if tag.name == 'img':
            url = tag.get('src') or tag.get('data-src') or ''
            if urlsplit(url).scheme == 'https' and (urlsplit(url).hostname or '').endswith('.sinaimg.cn'): blocks.append({'image':url})
            continue
        if tag.find(['p','li']): continue
        text = tag.get_text(' ',strip=True)
        bold = ' '.join(node.get_text(' ',strip=True) for node in tag.find_all(['strong','b']))
        if text: blocks.append({'text':text,'heading':tag.name.startswith('h') or (len(text)<=60 and text==bold)})
    return blocks


class WeiboService:
    def __init__(self, data_dir, articles, renderer, send, events=None):
        self.data_dir, self.articles, self.renderer, self.send = Path(data_dir), articles, renderer, send
        self.auth_path = self.data_dir/'weibo-auth.json'
        self.state_path = self.data_dir/'weibo-subscriptions.json'
        self.subscriptions = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.cache = TTLCache(max_entries=100)
        self.headers, self.verified_until, self.auth_revision = {}, 0, None
        self.session, self.task = None, None
        self.lock = asyncio.Lock()
        self.events = events

    async def start(self):
        self.sync_targets()
        if self.subscriptions and not self.auth_path.is_file():
            logger.warning('微博订阅已开启，但登录文件缺失，自动推送未启动。')
        if self.auth_path.is_file() and (self.task is None or self.task.done()):
            self.task = asyncio.create_task(self._poll(), name='jx3-weibo')

    async def close(self):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError): await self.task
        if self.session: await self.session.close()
        await self.cache.close()

    async def _request(self, path, params=None, *, article=False, text=False):
        if self.session is None:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12), cookie_jar=aiohttp.DummyCookieJar())
        origin = 'https://card.weibo.com' if article else 'https://weibo.com'
        headers = {'User-Agent':UA,'Referer':origin+'/'} if article else self.headers
        async with self.session.get(origin+path, params=params, headers=headers, allow_redirects=False) as response:
            if response.status != 200: raise WeiboError('微博暂时无法读取，请稍后再试。')
            body = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                body.extend(chunk)
                if len(body) > 4*1024*1024: raise WeiboError('这条微博内容过长，暂时无法读取。')
        if text: return body.decode('utf-8')
        try: return json.loads(body)
        except ValueError: raise WeiboError('微博登录已失效，请管理员重新登录。') from None

    async def verify(self):
        if not self.auth_path.is_file(): raise WeiboError('微博尚未登录，请联系管理员。')
        revision = self.auth_path.stat().st_mtime_ns
        if revision == self.auth_revision and time.monotonic() < self.verified_until: return
        auth = json.loads(self.auth_path.read_text())
        if auth.get('account_uid') != AUTHORIZED_UID: raise WeiboError('微博登录账号不符合配置。')
        values = {c['name']:c['value'] for c in auth['cookies'] if c['domain'] in ('weibo.com','.weibo.com')}
        self.headers = {'User-Agent':UA,'Referer':'https://weibo.com/','Cookie':'; '.join(k+'='+v for k,v in values.items()),'X-XSRF-TOKEN':values.get('XSRF-TOKEN','')}
        body = await self._request('/', text=True)
        uids = re.findall(r"""uid["']?\s*[:=]\s*["']?(\d+)""", body)
        if AUTHORIZED_UID not in uids:
            self.headers = {}
            raise WeiboError('微博登录已失效，请管理员重新登录。')
        self.auth_revision, self.verified_until = revision, time.monotonic()+3600

    async def posts(self, uid, *, fresh=False):
        if uid not in ACCOUNTS: raise WeiboError('暂不支持这位博主。')
        async def load():
            await self.verify()
            return author_posts(await self._request('/ajax/statuses/mymblog', {'uid':uid,'page':1,'feature':0}), uid)
        if fresh: return await load()
        return await self.cache.get_or_load('posts', uid, 120, load)

    async def _body(self, post):
        text = post.get('text_raw') or plain_text(post.get('text'))
        if post.get('isLongText'):
            data = await self._request('/ajax/statuses/longtext', {'id':post['mblogid']})
            full = (data.get('data') or {}).get('longTextContent')
            if not full: raise WeiboError('这条微博全文暂时无法读取。')
            text = plain_text(full)
        return text

    async def view(self, post, detail=False):
        text = await self._body(post)
        retweet = post.get('retweeted_status') or {}
        quoted = {'name':(retweet.get('user') or {}).get('screen_name',''),'text':await self._body(retweet)} if retweet else None
        page = post.get('page_info') or {}; article = None
        article_id = str(page.get('object_id') or '').removeprefix('1022:')
        if page.get('object_type') == 'article' and article_id.isdigit():
            article = {'title':page.get('content1') or '','blocks':[]}
        if article and detail:
            response = await self._request('/article/m/aj/detail', {'id':article_id}, article=True)
            data = response.get('data') or {}
            if not data.get('content'): raise WeiboError('这篇文章全文暂时无法读取。')
            article = {'title':data.get('title',''),'blocks':article_blocks(data['content'])}
            for block in article['blocks']:
                if 'image' in block: block['image'] = (await self.articles._image(block['image']))['src']
        urls = list(dict.fromkeys(image_urls(post)+image_urls(retweet)))
        urls = [u for u in urls if urlsplit(u).scheme == 'https' and (urlsplit(u).hostname or '').endswith('.sinaimg.cn')]
        total_images = len(urls)
        pictures = await asyncio.gather(*(self.articles._image(url) for url in urls), return_exceptions=True)
        date = datetime.fromtimestamp(timestamp(post), timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
        uid = str(post['user']['id']); url = 'https://weibo.com/'+uid+'/'+post['mblogid']
        if quoted: quoted['html'] = rich_text(quoted['text'])
        avatar = post['user'].get('avatar_hd') or post['user'].get('profile_image_url') or ''
        avatar_image = None
        if urlsplit(avatar).scheme == 'https' and (urlsplit(avatar).hostname or '').endswith('.sinaimg.cn'):
            try: avatar_image = await self.articles._image(avatar)
            except HttpError: pass
        return {'detail':detail,'remaining_images':0,'html':rich_text(text),'avatar':avatar_image,'name':ACCOUNTS[uid],'date':date,'text':text,'quoted':quoted,'article':article,'pictures':[p for p in pictures if isinstance(p,dict)],'url':url}

    async def reply(self, post, detail=False):
        async def load():
            view = await self.view(post,detail)
            path = await self.renderer.render('weibo', view, options={'width':1000,'device_scale_factor':1})
            return ImageReply(str(path), caption='【'+view['name']+'】'+(view['text'][:240].rstrip()+'…' if len(view['text'])>240 else view['text'])+'\n'+view['url'])
        return await self.cache.get_or_load('render', (str(post['id']),detail), 300, load)

    def sync_targets(self):
        if self.events is None: return
        targets = {row['session_id'] for row in self.events.subscriptions_summary() if self.events.settings.event_push_enabled and self.events.is_subscribed(row['session_id'],9001)}
        changed = set(self.subscriptions) != targets
        self.subscriptions = {session:self.subscriptions.get(session,{'since':time.time(),'seen':{uid:[] for uid in ACCOUNTS}}) for session in targets}
        for state in self.subscriptions.values():
            for uid in ACCOUNTS:
                if uid not in state['seen']:
                    state['seen'][uid] = []
                    state.setdefault('author_since',{})[uid] = time.time()
                    changed = True
        if changed: write_json(self.state_path,self.subscriptions)

    async def latest(self, args, session):
        names = {'':'1761587065', '官方':'1761587065', '剑网3':'1761587065', '余玉贤':'2046281757', '邓毅':'7056235331', **{name:uid for uid,name in ACCOUNTS.items()}}
        uid = names.get(args.replace(' ', '').strip())
        if uid is None: return '微博 官方／余玉贤／邓毅'
        posts = await self.posts(uid, fresh=True)
        if not posts: return '暂时没有查到这位博主的微博。'
        post = posts[0]
        reply = await self.reply(post)
        self.cache.set('last-post', session, {'uid':uid,'bid':post['mblogid']}, 3600)
        self.cache.set('post', post['mblogid'], post, 300)
        return reply

    async def detail(self, args, session):
        words = args.split(); number = None
        if words and words[-1].isdigit() and len(words[-1])<=2: number = int(words.pop())
        if len(words)>1: return '发送 detail 查看全部大图，或发送 detail 2 查看第 2 张。'
        link = words[0] if words else ''
        if link:
            match = re.fullmatch(r'https://(?:www\.)?weibo\.com/(\d+)/([A-Za-z0-9]+)(?:\?[^ ]*)?',link)
            if not match or match[1] not in ACCOUNTS: return '请附上剑网3官方微博、余玉贤或邓毅的原微博链接。'
            uid,bid = match[1],match[2]
        else:
            last = self.cache.get('last-post', session) or self.subscriptions.get(session,{}).get('last')
            if not last: return '还没有微博推送记录，可以发送 detail 原微博链接。'
            uid,bid = last['uid'],last['bid']
        await self.verify()
        async def load():
            post = await self._request('/ajax/statuses/show',{'id':bid,'isGetLongText':'true'})
            if post.get('ok')!=1 or str((post.get('user') or {}).get('id')) != uid: raise WeiboError('这条微博暂时无法读取。')
            return post
        post = await self.cache.get_or_load('post',bid,300,load)
        if number is not None: return await self.original_image(post,number)
        urls = list(dict.fromkeys(image_urls(post,True)+image_urls(post.get('retweeted_status') or {},True)))
        if not urls: return await self.reply(post,detail=True)
        slots = asyncio.Semaphore(3)
        async def download(index):
            async with slots: return await self.original_image(post,index)
        images = await asyncio.gather(*(download(i) for i in range(1,len(urls)+1)))
        return MessageParts([{'type':'image','path':image.path} for image in images])

    async def original_image(self,post,number):
        urls = list(dict.fromkeys(image_urls(post,True)+image_urls(post.get('retweeted_status') or {},True)))
        if number<1 or number>len(urls): return '这条微博有 '+str(len(urls))+' 张配图。'
        url = urls[number-1];host=urlsplit(url).hostname or ''
        if urlsplit(url).scheme!='https' or not host.endswith('.sinaimg.cn'): raise WeiboError('这张图片暂时无法读取。')
        directory = self.data_dir/'weibo-images';directory.mkdir(exist_ok=True)
        path = directory/(str(post['id'])+'-'+str(number)+'-original.jpg')
        saved = list(directory.glob(str(post['id'])+'-'+str(number)+'-original.*'))
        if saved: path = saved[0]
        if not path.is_file():
            import io
            from PIL import Image
            result = await self.articles.http._request('GET',url,binary=True,max_bytes=20*1024*1024,timeout=15,retries=0)
            with Image.open(io.BytesIO(result.data)) as image:
                extension = {'JPEG':'.jpg','PNG':'.png','GIF':'.gif','WEBP':'.webp'}.get(image.format,'.jpg')
                image.verify()
            path = path.with_suffix(extension)
            path.write_bytes(result.data)
        return ImageReply(str(path))

    async def poll_once(self):
        self.sync_targets()
        if not self.subscriptions: return
        rows, replies, failures = {}, {}, []
        for uid in ACCOUNTS:
            try: rows[uid] = await self.posts(uid, fresh=True)
            except Exception as exc:
                logger.warning('微博抓取失败：%s，%s：%s', ACCOUNTS[uid], type(exc).__name__, str(exc)[:160])
                failures.append(exc)
        for session, state in list(self.subscriptions.items()):
            for uid, posts in rows.items():
                if self.subscriptions.get(session) is not state: continue
                seen = state['seen'].setdefault(uid, [])
                since = state.get('author_since', {}).get(uid, state['since'])
                pending = [p for p in reversed(posts) if str(p['id']) not in seen and timestamp(p) >= since]
                for post in pending[:3]:
                    stage = '出图'
                    try:
                        identity = (uid, str(post['id']))
                        if identity not in replies: replies[identity] = await self.reply(post)
                        reply = replies[identity]
                        stage = '发送'
                        # Rendering does not hold the subscription lock. Recheck before delivery.
                        async with self.lock:
                            if self.subscriptions.get(session) is not state: break
                            async with asyncio.timeout(15): await self.send(session, reply.caption, [reply.path])
                            state['last'] = {'uid':uid, 'bid':post['mblogid']}
                            self.cache.set('last-post', session, state['last'], 3600)
                            seen.append(str(post['id']))
                            state['seen'][uid] = seen[-500:]
                            write_json(self.state_path, self.subscriptions)
                            logger.info('微博推送成功：%s，微博 %s', ACCOUNTS[uid], post['mblogid'])
                    except Exception as exc:
                        logger.warning('微博%s失败：%s，微博 %s，%s：%s', stage, ACCOUNTS[uid], post.get('mblogid', ''), type(exc).__name__, str(exc)[:160])
                        failures.append(exc)
                        break
        if failures: raise failures[0]

    async def _poll(self):
        delay = 5
        while True:
            await asyncio.sleep(delay)
            try:
                logger.info('微博定时检查开始')
                async with asyncio.timeout(90): await self.poll_once()
                write_json(self.data_dir/'weibo-health.json', {'status':'ok','checked_at':time.time()})
                logger.info('微博定时检查完成')
                delay = 300
            except Exception as exc:
                delay = min(1800,max(300,delay*2))
                write_json(self.data_dir/'weibo-health.json', {'error':type(exc).__name__,'message':str(exc)[:200],'frames':[{'file':Path(f.filename).name,'line':f.lineno,'function':f.name} for f in traceback.extract_tb(exc.__traceback__)]})
                logger.warning('微博读取或推送失败（%s：%s），%s 秒后重试。', type(exc).__name__, str(exc)[:160], delay)
