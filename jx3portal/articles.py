"""Official articles as a single readable image, using the API's full body."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import math
import re
import io
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
from bs4 import BeautifulSoup, NavigableString
from .cache import TTLCache


class ArticleError(Exception):
    pass


def official_url(url):
    try:
        parsed = urlsplit(html.unescape(str(url or '')))
        return parsed.scheme in {'https', 'http'} and parsed.hostname in {'jx3.xoyo.com', 'www.jx3.com', 'jx3.com'} and not parsed.username and parsed.port in {None, 80, 443}
    except ValueError:
        return False


def canonical_url(url):
    parsed = urlsplit(html.unescape(str(url or '')))
    return urlunsplit(('https', parsed.netloc.lower(), parsed.path.rstrip('/'), parsed.query, parsed.fragment))


def article_data(row):
    detail = row.get('desc') if isinstance(row.get('desc'), dict) else {}
    return {'title': str(row.get('title') or detail.get('title') or '官方消息'), 'date': str(row.get('date') or ''), 'url': str(row.get('url') or detail.get('url') or ''), 'content': str(detail.get('content') or row.get('content') or '')}


def clean_article(content, base_url):
    soup = BeautifulSoup(str(content), 'html.parser')
    for tag in soup.find_all(['script', 'style', 'iframe', 'form', 'input', 'button', 'object', 'embed', 'video', 'audio', 'svg', 'link', 'meta']):
        tag.decompose()
    # The official editor uses styled spans and short paragraphs as headings.
    for tag in soup.find_all(style=True):
        if re.search(r'font-weight\s*:\s*(?:bold|[6-9]00)', tag.get('style', ''), re.I) and tag.name in {'span','font'}:
            tag.name = 'strong'
    for tag in soup.find_all('p'):
        text = tag.get_text(' ', strip=True)
        if not tag.find('img') and len(text) <= 45:
            if re.match(r'^[◎◆■【]', text): tag.name = 'h2'
            elif re.match(r'^(?:[一二三四五六七八九十]+[、.．]|[0-9]{1,2}[、．]|[（(][一二三四五六七八九十0-9]+[）)])', text): tag.name = 'h3'
    allowed = {'p','br','strong','b','em','i','h1','h2','h3','h4','ul','ol','li','blockquote','table','thead','tbody','tr','td','th','img'}
    for tag in list(soup.find_all()):
        if tag.name not in allowed:
            tag.unwrap()
            continue
        if tag.name == 'img':
            url = urljoin(base_url, tag.get('src') or tag.get('data-src') or '')
            parsed = urlsplit(url)
            host = parsed.hostname or ''
            if parsed.scheme not in {'http','https'} or not any(host == domain or host.endswith('.' + domain) for domain in ('xoyo.com','jx3.com','jx3box.com')):
                tag.decompose()
                continue
            tag.attrs = {'src': url, 'alt': str(tag.get('alt') or ''), 'loading': 'eager'}
        else:
            tag.attrs = {}
    # Flatten layout wrappers; preserve paragraphs, lists and tables as units.
    blocks = []
    for node in list(soup.contents):
        if isinstance(node, NavigableString):
            if str(node).strip():
                blocks.append('<p>' + html.escape(str(node).strip()) + '</p>')
        elif node.get_text(strip=True) or node.find('img') or node.name == 'img':
            if node.name == 'p' and len(node.get_text()) > 700 and not node.find('img'):
                text = node.get_text()
                blocks.extend('<p>' + html.escape(text[i:i+600]) + '</p>' for i in range(0, len(text), 600))
            else:
                blocks.append(str(node))
    if not blocks:
        raise ArticleError('文章暂时没有正文')
    return blocks


def paginate(blocks, limit=1750):
    pages, current, used = [], [], 0
    for block in blocks:
        parsed = BeautifulSoup(block, 'html.parser')
        height = math.ceil(len(parsed.get_text()) / 31) * 47 + sum(min(620, 880*int(img.get('height', 620))/max(1,int(img.get('width', 880))))+40 for img in parsed.find_all('img')) + 24
        if current and used + height > limit:
            pages.append(''.join(current)); current, used = [], 0
        current.append(block); used += height
    if current:
        pages.append(''.join(current))
    return pages


def news_summary(data):
    soup = BeautifulSoup(''.join(clean_article(data['content'], data.get('url',''))), 'html.parser')
    heading_tag = 'h1' if len(soup.find_all('h1')) >= 2 else 'h2'
    headings = soup.find_all(heading_tag)
    points = list(dict.fromkeys(tag.get_text(' ', strip=True) for tag in headings))[:4]
    paragraphs = [tag.get_text(' ', strip=True) for tag in soup.find_all('p') if len(tag.get_text(strip=True)) >= 25]
    lead = paragraphs[0] if paragraphs else ''
    lead = lead if len(lead) <= 180 else lead[:180].rstrip('，；、 ') + '…'
    if not points:
        points = [text if len(text) <= 90 else text[:90]+'…' for text in paragraphs[1:4]]
    pictures, seen = [], set()
    # One representative picture from each major section; do not send the entire product gallery.
    for heading in headings:
        siblings = list(heading.find_next_siblings())
        boundary = next((i for i,node in enumerate(siblings) if node.name == heading_tag), len(siblings))
        siblings = siblings[:boundary]
        if any(word in heading.get_text() for word in ('小橙武','外观','武器','时装')):
            start = next((i for i,node in enumerate(siblings) if node.name in {'h2','h3','h4'}), 0)
            siblings = siblings[start:]
        for node in siblings:
            if node.name == heading_tag:
                break
            picture = node if node.name == 'img' else node.find('img')
            if picture and picture['src'] not in seen:
                pictures.append({'url':picture['src'],'caption':heading.get_text(' ',strip=True)})
                seen.add(picture['src']);break
        if len(pictures) == 3:
            break
    if not pictures:
        picture = soup.find('img')
        if picture:
            pictures.append({'url':picture['src'],'caption':''})
    return {'title':data['title'],'date':data.get('date',''),'lead':lead,'points':points,'pictures':pictures}




class ArticleService:
    def __init__(self, api, http, renderer):
        self.api, self.http, self.renderer = api, http, renderer
        self.cache = TTLCache(max_entries=100)

    async def _image(self, url):
        async def load():
            result = await self.http.request_image(url, timeout=10)
            from PIL import Image
            with Image.open(io.BytesIO(result.data)) as image:
                width, height = image.size
            return {'src':'data:image/webp;base64,' + base64.b64encode(result.data).decode(), 'width':width, 'height':height}
        return await self.cache.get_or_load('article-image', url, 3600, load)

    async def render_summary(self, data):
        summary = news_summary(data)
        key = hashlib.sha256(str(summary).encode()).hexdigest()
        async def load():
            images = await asyncio.gather(*(self._image(row['url']) for row in summary['pictures']), return_exceptions=True)
            pictures = [{**row, **image} for row, image in zip(summary['pictures'], images) if isinstance(image, dict)]
            path = await self.renderer.render('news_summary', {**summary, 'pictures': pictures}, options={'width':1000, 'device_scale_factor':1})
            return [path]
        paths = await self.cache.get_or_load('news-summary', key, 60, load)
        if any(not Path(path).is_file() for path in paths):
            self.cache.clear('news-summary')
            paths = await self.cache.get_or_load('news-summary', key, 60, load)
        return paths

    async def render_content(self, data):
        key = hashlib.sha256(str(data).encode()).hexdigest()
        async def load():
            blocks = clean_article(data['content'], data.get('url', ''))
            soup = BeautifulSoup(''.join(blocks), 'html.parser')
            images = list(soup.find_all('img'))
            sources = list(dict.fromkeys(img['src'] for img in images))
            resolved = await asyncio.gather(*(self._image(url) for url in sources))
            mapping = dict(zip(sources, resolved))
            for image in images:
                image.attrs.update(mapping[image['src']])
            content = ''.join(str(node) for node in soup.contents if str(node).strip())
            columns = 2 if len(soup.get_text()) > 650 else 1
            width = 1600 if columns == 2 else 1000
            path = await self.renderer.render('article', {**data, 'content': content, 'columns': columns}, options={'width': width, 'device_scale_factor': 1})
            return [path]
        paths = await self.cache.get_or_load('article', key, 60, load)
        if any(not Path(path).is_file() for path in paths):
            self.cache.clear('article')
            paths = await self.cache.get_or_load('article', key, 60, load)
        return paths

    async def from_news(self, row, *, compact=False):
        data = article_data(row)
        if not official_url(data['url']): raise ArticleError('暂时没有可读取的官网链接')
        key = canonical_url(data['url'])
        async def load():
            paths = await self.renderer.render_callback('<!doctype html><html><body></body></html>', {}, {'snapshot_url':data['url'], 'width':900, 'device_scale_factor':1.5})
            if not isinstance(paths, list) or not paths: raise ArticleError('新闻分页暂时无法生成')
            return paths
        paths = await self.cache.get_or_load('official-snapshot', key, 1800, load)
        if any(not Path(path).is_file() for path in paths):
            self.cache.clear('official-snapshot')
            paths = await self.cache.get_or_load('official-snapshot', key, 1800, load)
        return paths

    async def from_announcement(self, row):
        data = article_data(row)
        if not data['content']:
            rows = await self.api.announce(10)
            data = next((article_data(item) for item in rows if canonical_url(article_data(item)['url']) == canonical_url(data['url'])), data)
        if not data['content']: raise ArticleError('公告暂时没有返回正文')
        return await self.render_content(data)

    async def from_event(self, action, detail):
        if action not in {2002, 2003}: return []
        if not official_url(article_data(detail)['url']): return []
        return await self.from_announcement(detail) if action == 2003 else await self.from_news(detail)

    async def close(self):
        await self.cache.close()
