"""启动百宝箱自己的本机渲染进程；复用已有服务，保留外部端点。"""
import asyncio
import contextlib
import hashlib
import io
import zipfile
import os
import shutil
import signal
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from .render import RenderError


class LocalRenderService:
    def __init__(self, workdir: Path):
        self.workdir = workdir
        self.proc = None
        self.session = None
        self.lock = asyncio.Lock()
        self.closed = False
        self.references = {}

    async def healthy(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=1))
        try:
            async with self.session.get("http://127.0.0.1:8999/health") as response:
                return response.status == 200 and (await response.json()).get("code") == 0
        except (aiohttp.ClientError, TimeoutError, ValueError):
            return False

    async def ensure(self, endpoint: str):
        address = urlparse(endpoint)
        if address.scheme != "http" or address.hostname not in {"127.0.0.1", "localhost"} or address.port != 8999:
            return
        async with self.lock:
            if self.closed:
                raise RenderError("图片服务已关闭")
            if await self.healthy():
                return
            if self.proc is None or self.proc.returncode is not None:
                chromium = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
                if not chromium:
                    raise RenderError("服务器未安装 Chromium")
                self.workdir.mkdir(parents=True, exist_ok=True)
                log_path = self.workdir / "render.log"
                if log_path.exists() and log_path.stat().st_size > 2 * 1024 * 1024:
                    log_path.replace(self.workdir / "render.previous.log")
                env = dict(os.environ, T2I_WORKDIR=str(self.workdir), T2I_HOST="127.0.0.1", T2I_PORT="8999", T2I_CHROMIUM=chromium)
                with log_path.open("ab") as log:
                    self.proc = await asyncio.create_subprocess_exec(sys.executable, "-m", "jx3portal.render_worker", cwd=str(Path(__file__).resolve().parents[1]), env=env, stdout=log, stderr=asyncio.subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if await self.healthy():
                    return
                if self.proc.returncode is not None:
                    break
                await asyncio.sleep(.2)
            raise RenderError("图片服务暂时不可用，请稍后再试")

    async def render(self, template, data, options):
        """本机页面直接交给 T2I，避免通用 Markdown 渲染器注入代码高亮脚本。"""
        key = hashlib.sha256(template.encode()).hexdigest()
        payload = {'tmpldata': data, 'options': options, 'json': False}
        if key in self.references:
            payload['tmpl_id'] = self.references[key]
        else:
            payload['tmpl'] = template
        for attempt in range(2):
            async with self.session.post('http://127.0.0.1:8999/text2img/generate', json=payload, timeout=aiohttp.ClientTimeout(total=60 if options.get('snapshot_url') else 30)) as response:
                if response.status == 409 and 'tmpl_id' in payload:
                    self.references.pop(key, None)
                    payload.pop('tmpl_id')
                    payload['tmpl'] = template
                    continue
                if response.status != 200 or response.content_type not in {'image/jpeg', 'image/png', 'application/zip'}:
                    raise RenderError('图片生成失败，请稍后再试')
                image = await response.read()
                reference = response.headers.get('X-T2I-Template-Id')
                if reference:
                    self.references[key] = reference
                    if len(self.references) > 32:
                        self.references.pop(next(iter(self.references)))
                folder = self.workdir / 'output'
                folder.mkdir(parents=True, exist_ok=True)
                if response.content_type == 'application/zip':
                    return await asyncio.to_thread(self._save_pages, image, folder)
                path = folder / (uuid.uuid4().hex + ('.png' if response.content_type == 'image/png' else '.jpg'))
                await asyncio.to_thread(path.write_bytes, image)
                return str(path)
        raise RenderError('图片模板加载失败，请稍后再试')

    @staticmethod
    def _save_pages(raw, folder):
        prefix = uuid.uuid4().hex
        paths = []
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for name in sorted(archive.namelist()):
                if not name.endswith('.jpg'): continue
                path = folder / f'{prefix}-{len(paths)+1}.jpg'
                path.write_bytes(archive.read(name));paths.append(str(path))
        if not paths: raise RenderError('新闻正文暂时无法读取')
        return paths

    async def close(self):
        self.closed = True
        async with self.lock:
            if self.proc is not None and self.proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    self.proc.send_signal(signal.SIGINT)
                try:
                    await asyncio.wait_for(self.proc.wait(), timeout=5)
                except TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(self.proc.pid, signal.SIGKILL)
                    await self.proc.wait()
            if self.session is not None:
                await self.session.close()
