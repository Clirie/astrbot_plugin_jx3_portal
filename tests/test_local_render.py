import asyncio
import signal
from unittest.mock import AsyncMock, Mock, patch
from jx3portal.local_render import LocalRenderService


def test_external_renderer_unchanged(tmp_path):
    async def run():
        service = LocalRenderService(tmp_path)
        service.healthy = AsyncMock()
        await service.ensure("https://render.example/text2img")
        await service.ensure("http://127.0.0.1:8000/text2img")
        service.healthy.assert_not_awaited()
        assert service.proc is None
        await service.close()
    asyncio.run(run())


def test_existing_renderer_reused_and_not_stopped(tmp_path):
    async def run():
        service = LocalRenderService(tmp_path)
        service.healthy = AsyncMock(return_value=True)
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as spawn:
            await service.ensure("http://localhost:8999/text2img")
            await service.close()
            spawn.assert_not_awaited()
        assert service.proc is None
    asyncio.run(run())


def test_concurrent_start_and_owned_shutdown(tmp_path):
    async def run():
        service = LocalRenderService(tmp_path)
        service.healthy = AsyncMock(side_effect=[False, True, True, True])
        process = Mock(returncode=None, wait=AsyncMock(return_value=0))
        with patch("shutil.which", return_value="/usr/bin/chromium"), patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=process) as spawn:
            await asyncio.gather(*(service.ensure("http://127.0.0.1:8999") for _ in range(3)))
            spawn.assert_awaited_once()
            args = spawn.call_args
            assert args.kwargs["env"]["T2I_WORKDIR"] == str(tmp_path)
            assert args.args[1:] == ("-m", "jx3portal.render_worker")
            assert "miemie" not in args.kwargs["cwd"]
            await service.close()
        process.send_signal.assert_called_once_with(signal.SIGINT)
        process.wait.assert_awaited_once()
    asyncio.run(run())


def test_dead_worker_restarted_on_next_render(tmp_path):
    async def run():
        service = LocalRenderService(tmp_path)
        service.proc = Mock(returncode=1)
        service.healthy = AsyncMock(side_effect=[False, True])
        replacement = Mock(returncode=0)
        with patch("shutil.which", return_value="/usr/bin/chromium"), patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=replacement) as spawn:
            await service.ensure("http://127.0.0.1:8999")
            spawn.assert_awaited_once()
            assert service.proc is replacement
            await service.close()
    asyncio.run(run())
