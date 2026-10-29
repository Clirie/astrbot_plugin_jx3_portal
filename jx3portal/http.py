"""Shared async HTTP connections with bounded response size and total deadlines."""
from __future__ import annotations

import asyncio
import json
import io
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any
import aiohttp
from .telemetry import Telemetry

DEFAULT_UA = 'AstrBot-JX3-Portal/1.0 (+https://github.com/AstrBotDevs/AstrBot)'
DEFAULT_MAX_BYTES = 8 * 1024 * 1024

class HttpError(Exception):
    def __init__(self, message: str, *, status: int | None = None, path: str = '', body: Any = None) -> None:
        super().__init__(message)
        self.message, self.status, self.path, self.body = message, status, path, body

class NetworkError(HttpError):
    pass

class HTTPStatusError(HttpError):
    pass

@dataclass
class HttpResult:
    data: Any
    status: int
    elapsed_ms: int
    bytes: int


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return '' if value is None else str(value)


def build_url(url: str, params: dict[str, Any] | None = None) -> str:
    pairs = []
    for key, value in (params or {}).items():
        if value is not None:
            pairs.extend((str(key), _stringify(item)) for item in (value if isinstance(value, (list, tuple, set)) else [value]))
    if not pairs:
        return url
    parsed = urllib.parse.urlsplit(url)
    query = parsed.query + ('&' if parsed.query else '') + urllib.parse.urlencode(pairs)
    return urllib.parse.urlunsplit(parsed._replace(query=query))


def _decode(raw: bytes, content_type: str) -> Any:
    if not raw:
        return None
    text = raw.decode('utf-8-sig', errors='replace')
    try:
        return json.loads(text)
    except ValueError:
        if 'json' in content_type.lower():
            raise HttpError('数据暂时无法读取，请稍后再试。') from None
        return text


class HttpClient:
    def __init__(self, *, user_agent: str = DEFAULT_UA) -> None:
        self.user_agent = user_agent
        self._session: aiohttp.ClientSession | None = None
        self._media_session: aiohttp.ClientSession | None = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(limit=16, limit_per_host=6, ttl_dns_cache=300)
            self._session = aiohttp.ClientSession(connector=connector, cookie_jar=aiohttp.DummyCookieJar(), trust_env=True, headers={'User-Agent': self.user_agent})
        return self._session

    def _get_media_session(self):
        if self._media_session is None or self._media_session.closed:
            connector = aiohttp.TCPConnector(limit=4, limit_per_host=3, ttl_dns_cache=300)
            self._media_session = aiohttp.ClientSession(connector=connector, cookie_jar=aiohttp.DummyCookieJar(), trust_env=True, headers={'User-Agent': self.user_agent})
        return self._media_session

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
        if self._media_session is not None:
            await self._media_session.close()
            self._media_session = None

    async def _request(self, method: str, url: str, *, params=None, json_body=None, form_body=None, headers=None, timeout=20, retries=1, max_bytes=DEFAULT_MAX_BYTES, source='http', telemetry=None, binary=False) -> HttpResult:
        method = method.upper()
        # Retrying an image generation POST can charge twice. Only reads retry.
        retries = max(0, min(5, int(retries))) if method in {'GET', 'HEAD'} else 0
        timeout = max(0.05, float(timeout))
        started = time.monotonic()
        path = urllib.parse.urlsplit(url).path
        request_headers = {'Accept': '*/*' if binary else 'application/json', **(headers or {})}
        payload = None
        if json_body is not None:
            payload = json.dumps(json_body, ensure_ascii=False).encode('utf-8')
            request_headers.setdefault('Content-Type', 'application/json')
        elif form_body is not None:
            payload = urllib.parse.urlencode(form_body).encode('utf-8')
            request_headers.setdefault('Content-Type', 'application/x-www-form-urlencoded')
        error = None
        try:
            # Includes pool wait, retry attempts and response body reads.
            async with asyncio.timeout(timeout):
                for attempt in range(retries + 1):
                    if time.monotonic() - started >= timeout:
                        break
                    try:
                        budget = max(0.01, timeout - (time.monotonic() - started))
                        limits = aiohttp.ClientTimeout(total=budget, connect=min(8, budget), sock_read=budget)
                        async with (self._get_media_session() if binary else self._get_session()).request(method, build_url(url, params), data=payload, headers=request_headers, timeout=limits) as response:
                            chunks, size = [], 0
                            async for chunk in response.content.iter_chunked(64 * 1024):
                                size += len(chunk)
                                if size > max_bytes:
                                    raise HttpError('返回内容过大，暂时无法读取。', status=response.status, path=path)
                                chunks.append(chunk)
                            raw = b''.join(chunks)
                            if response.status >= 400:
                                try:
                                    body = _decode(raw, response.headers.get('Content-Type', ''))
                                except HttpError:
                                    body = None
                                raise HTTPStatusError(f'HTTP {response.status}', status=response.status, path=path, body=body)
                            data = raw if binary else _decode(raw, response.headers.get('Content-Type', ''))
                            elapsed = int((time.monotonic() - started) * 1000)
                            if telemetry is not None:
                                telemetry.record_http(source=source, path=path, ok=True, status=response.status, duration_ms=elapsed)
                            return HttpResult(data, response.status, elapsed, size)
                    except HTTPStatusError as exc:
                        error = exc
                        if exc.status not in {502, 503, 504}:
                            break
                    except (aiohttp.ClientConnectorCertificateError, aiohttp.ClientSSLError):
                        error = NetworkError('数据服务连接异常，请稍后再试。', path=path)
                        break
                    except (aiohttp.ClientError, OSError, TimeoutError):
                        error = NetworkError('数据服务暂时没有响应，请稍后再试。', path=path)
                    except HttpError as exc:
                        error = exc
                        break
                    if attempt < retries:
                        remaining = timeout - (time.monotonic() - started)
                        if remaining <= 0:
                            break
                        await asyncio.sleep(min(0.2 * (attempt + 1), remaining))
        except TimeoutError:
            error = NetworkError('查询超时，请稍后再试。', path=path)
        error = error or HttpError('查询失败，请稍后再试。', path=path)
        if telemetry is not None:
            telemetry.record_http(source=source, path=path, ok=False, status=error.status, duration_ms=(time.monotonic() - started) * 1000, message=f'{path} · {error.message}')
        raise error

    async def request_image(self, url: str, *, timeout=10, max_bytes=20*1024*1024) -> HttpResult:
        """Read only enough bytes to decode the first frame of a static preview."""
        from PIL import Image, UnidentifiedImageError
        def decode(raw):
            try:
                with Image.open(io.BytesIO(raw)) as picture:
                    picture.seek(0)
                    picture.load()
                    picture.thumbnail((1200, 1600))
                    output = io.BytesIO()
                    picture.convert('RGB').save(output, format='WEBP', quality=88)
                    return output.getvalue()
            except (OSError, UnidentifiedImageError):
                return None
        start = time.monotonic()
        try:
            async with asyncio.timeout(timeout):
                async with self._get_media_session().get(url, headers={'Accept':'image/*','Referer':url}, timeout=aiohttp.ClientTimeout(total=None, connect=min(8, timeout))) as response:
                    if response.status >= 400:
                        raise HTTPStatusError(f'HTTP {response.status}', status=response.status)
                    raw = bytearray(); checked = 0
                    async for chunk in response.content.iter_chunked(256*1024):
                        raw.extend(chunk)
                        if len(raw) > max_bytes:
                            raise HttpError('配图过大，暂时无法读取。')
                        if len(raw)-checked < 128*1024:
                            continue
                        checked = len(raw)
                        picture = await asyncio.to_thread(decode, bytes(raw))
                        if picture:
                            return HttpResult(picture, response.status, int((time.monotonic()-start)*1000), len(raw))
                    picture = await asyncio.to_thread(decode, bytes(raw))
                    if picture:
                        return HttpResult(picture, response.status, int((time.monotonic()-start)*1000), len(raw))
                    raise HttpError('配图暂时无法读取。')
        except (TimeoutError, aiohttp.ClientError) as exc:
            raise NetworkError('配图暂时没有响应。') from exc

    async def request_json(self, method: str, url: str, *, params=None, json_body=None, form_body=None, headers=None, timeout=20, retries=1, max_bytes=DEFAULT_MAX_BYTES, source='http', telemetry: Telemetry | None = None) -> HttpResult:
        return await self._request(method, url, params=params, json_body=json_body, form_body=form_body, headers=headers, timeout=timeout, retries=retries, max_bytes=max_bytes, source=source, telemetry=telemetry)

    async def request_bytes(self, method: str, url: str, *, params=None, headers=None, timeout=60, max_bytes=20 * 1024 * 1024, source='http', telemetry: Telemetry | None = None) -> HttpResult:
        return await self._request(method, url, params=params, headers=headers, timeout=timeout, retries=0, max_bytes=max_bytes, source=source, telemetry=telemetry, binary=True)
