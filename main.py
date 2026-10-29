"""百宝箱入口：指令目录直接映射到 CommandService，管理启动、卸载和后台路由。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from sys import maxsize
from typing import Any
from urllib.parse import urlsplit

_PLUGIN_DIR = Path(__file__).resolve().parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

# AstrBot hot reload drops ``main`` but may keep old submodules in sys.modules.
for _module_name in list(sys.modules):
    if _module_name == "jx3portal" or _module_name.startswith("jx3portal."):
        sys.modules.pop(_module_name, None)

from astrbot.api import AstrBotConfig, logger  # noqa: E402
from astrbot.api.event import AstrMessageEvent, filter  # noqa: E402
from astrbot.api.star import Context, Star, StarTools, register  # noqa: E402

try:  # AstrBot >= 4.10 plugin visual views
    from astrbot.api.web import error_response, json_response, request  # noqa: E402

    WEB_API_AVAILABLE = True
except Exception:  # pragma: no cover - older AstrBot
    WEB_API_AVAILABLE = False

    class _FallbackQuery(dict):
        pass

    class _FallbackRequest:
        query = _FallbackQuery()
        username = None

        async def json(self, default=None):
            return default

    request = _FallbackRequest()  # type: ignore

    def json_response(data=None, **kwargs):
        return data

    def error_response(message, **kwargs):
        return {"status": "error", "message": str(message)}

from jx3portal import PLUGIN_DESC, PLUGIN_NAME, PLUGIN_VERSION  # noqa: E402
from jx3portal.admin import AdminController, AdminError  # noqa: E402
from jx3portal.articles import ArticleService
from jx3portal.buttons import MenuReply, send_menu
from jx3portal.aliases import ServerAliasService  # noqa: E402
from jx3portal.cache import TTLCache  # noqa: E402
from jx3portal.commands import CommandService, ImageReply, MessageParts, PendingReply
from jx3portal.game.catalog import GAME_MAP  # noqa: E402
from jx3portal.doubao import DoubaoClient  # noqa: E402
from jx3portal.weibo import WeiboService
from jx3portal.event_push import EventPushService  # noqa: E402
from jx3portal.format import split_message  # noqa: E402
from jx3portal.http import HttpClient  # noqa: E402
from jx3portal.jx3api import JX3APIClient  # noqa: E402
from jx3portal.jx3box import JX3BOXClient  # noqa: E402
from jx3portal.online import OnlineService  # noqa: E402
from jx3portal.paid import PaidService  # noqa: E402
from jx3portal.local_render import LocalRenderService
from jx3portal.render import ImageRenderer, RenderError  # noqa: E402
from jx3portal.settings import Settings  # noqa: E402
from jx3portal.privacy_logging import PrivacyLogging
from jx3portal.telemetry import Telemetry  # noqa: E402
from jx3portal.tuilan import TuilanService  # noqa: E402


@register(
    PLUGIN_NAME,
    "JX3 Portal",
    PLUGIN_DESC,
    PLUGIN_VERSION,
)
class JX3PortalPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.conf = config if config is not None else {}
        self.data_dir = self._resolve_data_dir()

        self.settings = Settings(self.conf, self.data_dir, self._save_config)
        log_limit = self.settings.get_int("admin_log_limit", minimum=50, maximum=1000)
        self.telemetry = Telemetry(max_logs=log_limit)
        self.privacy_logging = PrivacyLogging()
        self.cache = TTLCache(max_entries=800)
        self.http = HttpClient()
        self.api = JX3APIClient(self.settings, self.http, self.cache, self.telemetry)
        self.box = JX3BOXClient(self.settings, self.http, self.cache, self.telemetry)
        self.tuilan = TuilanService(self.settings, self.api)
        self.aliases = ServerAliasService(self.data_dir)
        self.paid = PaidService(self.settings, self.data_dir)
        self.online = OnlineService(
            self.settings, self.api, self.http, self.telemetry
        )
        self.doubao = DoubaoClient(self.settings, self.http, self.data_dir)
        self.local_render = LocalRenderService(self.data_dir / "renderer")
        self.renderer = ImageRenderer(self._render_html, cache_dir=self.data_dir / "render-cache", asset_origin=self._asset_origin)
        self.articles = ArticleService(self.api, self.http, self.renderer)
        self.events = EventPushService(
            self.settings, self.paid, self._push_send, self.data_dir, preview_callback=self.articles.from_event, server_filter=self._push_matches_server
        )
        self.weibo = WeiboService(self.data_dir, self.articles, self.renderer, self._push_send, self.events)
        self.events.on_change = self.weibo.sync_targets
        self.commands = CommandService(
            self.settings,
            self.api,
            self.box,
            self.tuilan,
            self.cache,
            self.telemetry,
            paid=self.paid,
            online=self.online,
            events=self.events,
            doubao=self.doubao,
            aliases=self.aliases,
            renderer=self.renderer,
            articles=self.articles,
            weibo=self.weibo,
        )
        self.admin = AdminController(
            settings=self.settings,
            api=self.api,
            box=self.box,
            tuilan=self.tuilan,
            cache=self.cache,
            telemetry=self.telemetry,
            commands=self.commands,
            paid=self.paid,
            events=self.events,
            doubao=self.doubao,
            online=self.online,
            aliases=self.aliases,
            renderer=self.renderer,
            astrbot_version=self._astrbot_version(),
            data_dir=self.data_dir,
        )
        self.admin.card_styles = self.commands.card_styles

        self.register_web_apis()
        # Filled by initialize(); the listener ignores messages before that.
        self.command_map: dict[str, Any] = {}

        logger.info("剑网3百宝箱已加载（v%s）", PLUGIN_VERSION)

    # ------------------------------------------------------------------ setup
    @staticmethod
    def _resolve_data_dir() -> Path:
        try:
            return Path(StarTools.get_data_dir(PLUGIN_NAME))
        except TypeError:  # older signature without the plugin name
            try:
                return Path(StarTools.get_data_dir())
            except Exception:  # pragma: no cover - defensive
                return _PLUGIN_DIR / "data"
        except Exception:  # pragma: no cover - defensive
            return _PLUGIN_DIR / "data"

    @staticmethod
    def _astrbot_version() -> str:
        try:
            import astrbot

            return str(getattr(astrbot, "__version__", "") or "")
        except Exception:  # pragma: no cover
            return ""

    def _save_config(self) -> Any:
        saver = getattr(self.conf, "save_config", None)
        if callable(saver):
            return saver()
        return True

    async def initialize(self) -> None:
        self.settings.migrate_command_keys()
        self.privacy_logging.install()
        try:
            await self.local_render.ensure(self._render_endpoint())
        except RenderError as exc:
            logger.warning("本地渲染服务启动失败：%s", exc)
        await self.commands.game.initialize()
        self.ini_command_map()
        await self.events.start()
        await self.weibo.start()
        self.telemetry.log("info", "plugin", f"插件启动（v{PLUGIN_VERSION}）")
        logger.info(
            "剑网3百宝箱初始化完成：%d 个指令入口，Token=%s Ticket=%s 事件推送=%s",
            len(self.command_map),
            "已配置" if self.settings.token else "未配置",
            "已配置" if self.settings.ticket else "未配置",
            "开启" if self.settings.event_push_enabled else "关闭",
        )

    async def _push_matches_server(self, session_id: str, server: str) -> bool:
        bindings = self.commands.game.bindings
        if bindings is None:
            return False
        row = await bindings.sql.fetch_one("SELECT server FROM portal_servers WHERE session=?", (session_id,))
        bound = self.aliases.resolve(row["server"]) if row else ""
        return bool(bound and bound == self.aliases.resolve(server))

    async def _push_send(self, session_id: str, text: str, images: list[str] | None = None) -> None:
        """EventPushService -> AstrBot message chain adapter."""

        try:
            from astrbot.api.event import MessageChain

            chain = MessageChain().message(text)
            for path in images or []:
                chain.file_image(path)
            if not await self.context.send_message(session_id, chain):
                raise RuntimeError('推送会话未匹配可用平台')
        except Exception:
            logger.warning("事件推送发送失败")
            raise

    def _render_endpoint(self) -> str:
        config = self.context.get_config() or {}
        strategy = self.context.html_renderer.network_strategy
        return str(config.get("t2i_endpoint") or strategy.BASE_RENDER_URL)

    def _asset_origin(self) -> str:
        endpoint = urlsplit(self._render_endpoint())
        if endpoint.scheme == 'http' and endpoint.hostname in {'127.0.0.1', 'localhost'} and endpoint.port == 8999:
            return 'http://127.0.0.1:8999/static/'
        return ''

    async def _render_html(
        self, template: str, data: dict[str, Any], options: dict[str, Any] | None = None
    ) -> str:
        """AstrBot Star.html_render adapter; raises a readable error if absent."""
        renderer = getattr(self, "html_render", None)
        if not callable(renderer):
            raise RenderError("当前 AstrBot 版本不支持 html_render，无法生成图片")
        await self.local_render.ensure(self._render_endpoint())
        if self._asset_origin():
            return await self.local_render.render(template, data, options or {})
        return str(await renderer(template, data, options=options, return_url=False))

    async def terminate(self) -> None:
        await self.weibo.close()
        try:
            await self.events.close()
        except Exception:  # pragma: no cover - defensive
            pass
        try:
            await self.box.close()
        except Exception:  # pragma: no cover - defensive
            pass
        await self.commands.market.close()
        await self.commands.game.close()
        await self.articles.close()
        await self.renderer.close()
        await self.local_render.close()
        await self.cache.close()
        await self.http.close()
        self.privacy_logging.close()
        logger.info("剑网3百宝箱已卸载")

    # ------------------------------------------------------------- command map
    def ini_command_map(self) -> None:
        self.command_map = {}
        for spec in self.commands.specs():
            if spec.key not in GAME_MAP and not callable(getattr(self.commands, "_cmd_" + spec.key, None)):
                raise RuntimeError("指令缺少实现：" + spec.key)
            for alias in (spec.name, *spec.aliases):
                self.command_map[alias] = spec.key
        logger.info("已注册 %d 个指令入口", len(self.command_map))

    def parse_message(self, text: str) -> list[str] | None:
        """Split a chat message into command and arguments."""

        value = str(text or "").strip()
        if not value:
            return None
        if value.startswith("/"):
            value = value[1:].strip()
        if not value:
            return None
        return value.split()

    def resolve_command(self, event: AstrMessageEvent):
        """Identify a command from processed and platform-original text.

        AstrBot may strip mentions/prefixes differently per adapter, so both
        ``event.message_str`` and ``message_obj.message_str`` are checked, just
        like the reference plugin does.
        """

        if not self.command_map:
            return None
        candidates = [
            getattr(event, "message_str", ""),
            getattr(getattr(event, "message_obj", None), "message_str", ""),
        ]
        seen: set[str] = set()
        for text in candidates:
            if not isinstance(text, str):
                continue
            stripped = text.strip()
            if not stripped or stripped in seen:
                continue
            seen.add(stripped)
            parts = self.parse_message(stripped)
            if not parts:
                continue
            cmd, *args = parts
            if cmd not in self.command_map:
                for prefix in ('物价选', '物价'):
                    if cmd.startswith(prefix) and len(cmd) > len(prefix):
                        args = [cmd[len(prefix):], *args];cmd = prefix;break
            key = self.command_map.get(cmd) or self.command_map.get(cmd.lower())
            if key is None or not self.commands.effective_enabled(key):
                continue
            if cmd.lower() in {"剑三", "剑网3", "jx3", "j3"} and args:
                sub = args[0]
                sub_key = self.command_map.get(sub) or self.command_map.get(sub.lower())
                if sub_key is not None and sub_key != key:
                    if not self.commands.effective_enabled(sub_key):
                        continue
                    return sub, args[1:], sub_key
            return cmd, args, key
        return None

    @filter.event_message_type(
        filter.EventMessageType.ALL,
        priority=maxsize - 10,
    )
    async def on_all_message(self, event: AstrMessageEvent):
        """Single listener: resolve the command map and stop propagation."""

        if not self.command_map:
            logger.debug("插件尚未初始化完成，忽略消息")
            return

        # ★ 名片生图菜单回复（回复序号）✅
        try:
            _raw0 = str(getattr(event, "message_str", "")).strip()
            if _raw0 and getattr(self.commands, "_card_pending", None):
                _card_reply = await self.commands._card_pending_reply(event, _raw0)
                if _card_reply is not None:
                    event.should_call_llm(False)
                    event.stop_event()
                    if isinstance(_card_reply, ImageReply):
                        yield event.make_result().file_image(
                            _card_reply.path).use_t2i(False)
                    else:
                        yield event.plain_result(str(_card_reply)).use_t2i(False)
                    return
        except Exception:
            logger.debug("名片生图菜单处理失败", exc_info=True)

        resolved = self.resolve_command(event)
        if resolved is None:
            raw = str(getattr(event, 'message_str', '')).strip()
            if self.commands.market.choices.numeric_reply(event, raw): resolved = ('物价选', [raw], 'trade_select')
            else: return
        cmd, args, key = resolved
        started = asyncio.get_running_loop().time()

        # Keep the pipeline running until every reply part has been sent.
        event.should_call_llm(False)
        try:
            try:
                text = await self.commands.run(key, event, " ".join(args))
            except Exception:  # pragma: no cover - last-resort guard
                logger.exception("指令 %s 执行失败", cmd)
                text = f"{cmd}暂时查询失败，请稍后再试。"
            if isinstance(text, MenuReply):
                if not await send_menu(event, text): yield event.plain_result(text.fallback()).use_t2i(False).use_markdown(False)
                return
            if isinstance(text, PendingReply):
                if not text.menu or not await send_menu(event, text.menu):
                    yield event.plain_result(text.text).use_t2i(False).use_markdown(False)
                if text.on_sent: text.on_sent()
                try:
                    async with asyncio.timeout(35): text = await text.load()
                except Exception as exc:
                    self.telemetry.log('warn', 'market', '物价出图失败：' + type(exc).__name__)
                    text = '物价图暂时生成失败，请稍后重试。'
            if not text:
                return
            if isinstance(text, ImageReply):
                try:
                    for index, path in enumerate((text.path, *text.extra_paths)):
                        if text.caption and index == 0:
                            yield event.make_result().file_image(path).message(text.caption).use_t2i(False).use_markdown(False)
                        else:
                            yield event.image_result(path)
                    if text.menu and not await send_menu(event, text.menu):
                        yield event.plain_result(text.menu.fallback()).use_t2i(False).use_markdown(False)
                except Exception:  # pragma: no cover - platform specific
                    logger.exception("发送生成图片失败")
                    yield event.plain_result("图片生成成功，但发送失败。")
                return
            if isinstance(text, MessageParts):
                for part in text.parts:
                    if part["type"] == "image": yield event.image_result(part["path"])
                    else:
                        for chunk in split_message(part["text"]): yield event.plain_result(chunk)
                return
            for chunk in split_message(text):
                yield event.plain_result(chunk)
        finally:
            self.telemetry.record_command_duration(key, (asyncio.get_running_loop().time() - started) * 1000, "reply")
            event.stop_event()

    # ------------------------------------------------------------- web routes
    def register_web_apis(self) -> None:
        if not WEB_API_AVAILABLE or not hasattr(self.context, "register_web_api"):
            logger.warning(
                "当前 AstrBot 版本不支持插件可视化视图；"
                "仍可通过插件配置页填写 Token / Ticket。"
            )
            return
        routes: list[tuple[str, Any, list[str], str]] = [
            ("bootstrap", self.web_bootstrap, ["GET"], "Dashboard bootstrap"),
            ("settings/save", self.web_save_settings, ["POST"], "Save settings"),
            ("settings/secret/clear", self.web_clear_secret, ["POST"], "Clear a secret"),
            ("test", self.web_test, ["POST"], "Test an upstream connection"),
            ("token/stats", self.web_token_stats, ["POST"], "JX3API token usage"),
            ("commands/save", self.web_save_commands, ["POST"], "Save command switches"),
            ("cache/stats", self.web_cache_stats, ["GET"], "Cache statistics"),
            ("cache/clear", self.web_clear_cache, ["POST"], "Clear cache"),
            ("logs", self.web_logs, ["GET"], "Runtime logs"),
            ("logs/clear", self.web_clear_logs, ["POST"], "Clear runtime logs"),
            ("endpoints", self.web_endpoints, ["GET"], "JX3API endpoint catalog"),
            ("servers", self.web_servers, ["GET"], "Server list"),
            ("debug/request", self.web_debug, ["POST"], "Debug a JX3API request"),
            ("system", self.web_system, ["GET"], "System information"),
            ("stats/reset", self.web_reset_stats, ["POST"], "Reset statistics"),
            ("export", self.web_export, ["GET"], "Export config without secrets"),
            ("render/templates", self.web_render_templates, ["GET"], "Image templates"),
            ("render/preview", self.web_render_preview, ["POST"], "Render image preview"),
            ("aliases/summary", self.web_aliases_summary, ["GET"], "Server alias list"),
            ("card-styles/summary", self.web_card_styles_summary, ["GET"], "Card style list"),
            ("card-styles/save", self.web_card_styles_save, ["POST"], "Save card styles"),
            ("card-styles/delete", self.web_card_styles_delete, ["POST"], "Delete card style"),
            ("card-styles/reset", self.web_card_styles_reset, ["POST"], "Reset card styles"),
            ("aliases/save", self.web_aliases_save, ["POST"], "Save server aliases"),
            ("aliases/reset", self.web_aliases_reset, ["POST"], "Reset server aliases"),
            ("events/summary", self.web_events_summary, ["GET"], "Event push status"),
            ("events/session/save", self.web_events_session_save, ["POST"], "Save session subscriptions"),
            ("events/reload", self.web_events_reload, ["POST"], "Reconnect event channel"),
            ("paid/summary", self.web_paid_summary, ["GET"], "Paid authorization summary"),
            ("paid/groups/save", self.web_paid_group_save, ["POST"], "Save paid group"),
            ("paid/groups/delete", self.web_paid_group_delete, ["POST"], "Delete paid group"),
            ("paid/codes/generate", self.web_paid_codes_generate, ["POST"], "Generate activation codes"),
            ("paid/codes/delete", self.web_paid_codes_delete, ["POST"], "Delete activation code"),
            ("doubao/test", self.web_doubao_test, ["POST"], "Test Doubao credentials"),
            ("online/test", self.web_online_test, ["POST"], "Test online query service"),
        ]
        for suffix, handler, methods, desc in routes:
            self.context.register_web_api(
                f"/{PLUGIN_NAME}/{suffix}", handler, methods, desc
            )

    async def _json_payload(self) -> dict[str, Any]:
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            raise AdminError("请求体必须是 JSON 对象")
        return payload

    @staticmethod
    def _viewer() -> dict[str, Any]:
        try:
            return {"username": getattr(request, "username", None)}
        except Exception:  # pragma: no cover - defensive
            return {"username": None}

    def _fail(self, exc: BaseException, action: str):
        if isinstance(exc, AdminError):
            return error_response(exc.message, status_code=exc.status_code)
        logger.exception("%s失败", action)
        return error_response("服务器内部错误，请查看控制台日志", status_code=500)

    async def web_bootstrap(self):
        try:
            data = self.admin.bootstrap()
            data["viewer"] = self._viewer()
            return json_response(data)
        except Exception as exc:
            return self._fail(exc, "读取后台数据")

    async def web_save_settings(self):
        try:
            return json_response(self.admin.save_settings(await self._json_payload()))
        except Exception as exc:
            return self._fail(exc, "保存配置")

    async def web_clear_secret(self):
        try:
            return json_response(self.admin.clear_secret(await self._json_payload()))
        except Exception as exc:
            return self._fail(exc, "清除密钥")

    async def web_test(self):
        try:
            return json_response(await self.admin.test(await self._json_payload()))
        except Exception as exc:
            return self._fail(exc, "测试连接")

    async def web_token_stats(self):
        try:
            return json_response(await self.admin.token_stats(await self._json_payload()))
        except Exception as exc:
            return self._fail(exc, "读取 Token 用量")

    async def web_save_commands(self):
        try:
            return json_response(self.admin.save_commands(await self._json_payload()))
        except Exception as exc:
            return self._fail(exc, "保存指令配置")

    async def web_cache_stats(self):
        try:
            return json_response(self.admin.cache_stats())
        except Exception as exc:
            return self._fail(exc, "读取缓存")

    async def web_clear_cache(self):
        try:
            return json_response(self.admin.clear_cache(await self._json_payload()))
        except Exception as exc:
            return self._fail(exc, "清理缓存")

    async def web_logs(self):
        try:
            params = {
                "limit": _query_get("limit", "100"),
                "level": _query_get("level", ""),
                "q": _query_get("q", ""),
            }
            return json_response(self.admin.logs(params))
        except Exception as exc:
            return self._fail(exc, "读取日志")

    async def web_clear_logs(self):
        try:
            return json_response(self.admin.clear_logs())
        except Exception as exc:
            return self._fail(exc, "清空日志")

    async def web_endpoints(self):
        try:
            params = {"q": _query_get("q", "")}
            return json_response(self.admin.endpoints(params))
        except Exception as exc:
            return self._fail(exc, "读取接口目录")

    async def web_servers(self):
        try:
            force = str(_query_get("force", "0")).lower() in {"1", "true", "yes"}
            return json_response(await self.admin.servers(force=force))
        except Exception as exc:
            return self._fail(exc, "读取区服列表")

    async def web_debug(self):
        try:
            return json_response(await self.admin.debug_request(await self._json_payload()))
        except Exception as exc:
            return self._fail(exc, "接口调试")

    async def web_system(self):
        try:
            return json_response(self.admin.system())
        except Exception as exc:
            return self._fail(exc, "读取系统信息")

    async def web_reset_stats(self):
        try:
            return json_response(self.admin.reset_stats())
        except Exception as exc:
            return self._fail(exc, "重置统计")

    async def web_export(self):
        try:
            return json_response(self.admin.export_config())
        except Exception as exc:
            return self._fail(exc, "导出配置")

    async def web_render_templates(self):
        try:
            return json_response(self.admin.render_summary())
        except Exception as exc:
            return self._fail(exc, "读取图片模板")

    async def web_render_preview(self):
        try:
            return json_response(
                await self.admin.render_preview(await self._json_payload())
            )
        except Exception as exc:
            return self._fail(exc, "渲染图片模板")

    async def web_card_styles_summary(self):
        try:
            data = self.admin.card_styles_summary()
            return json_response(data)
        except Exception as exc:
            logger.exception("名片模板读取失败")
            return json_response({
                "ok": False,
                "rows": [],
                "message": f"{type(exc).__name__}: {exc}",
            })

    async def web_card_styles_save(self):
        try:
            return json_response(self.admin.card_styles_save(await self._json_payload()))
        except Exception as exc:
            logger.exception("名片模板操作失败：save")
            return json_response({"ok": False, "rows": [], "message": f"{type(exc).__name__}: {exc}"})

    async def web_card_styles_delete(self):
        try:
            return json_response(self.admin.card_styles_delete(await self._json_payload()))
        except Exception as exc:
            logger.exception("名片模板操作失败：delete")
            return json_response({"ok": False, "rows": [], "message": f"{type(exc).__name__}: {exc}"})

    async def web_card_styles_reset(self):
        try:
            return json_response(self.admin.card_styles_reset())
        except Exception as exc:
            logger.exception("名片模板操作失败：reset")
            return json_response({"ok": False, "rows": [], "message": f"{type(exc).__name__}: {exc}"})

    async def web_aliases_summary(self):
        try:
            return json_response(self.admin.aliases_summary())
        except Exception as exc:
            return self._fail(exc, "读取区服别名")

    async def web_aliases_save(self):
        try:
            return json_response(
                self.admin.save_aliases(await self._json_payload())
            )
        except Exception as exc:
            return self._fail(exc, "保存区服别名")

    async def web_aliases_reset(self):
        try:
            return json_response(self.admin.reset_aliases())
        except Exception as exc:
            return self._fail(exc, "恢复区服别名")

    async def web_events_summary(self):
        try:
            return json_response(self.admin.events_summary())
        except Exception as exc:
            return self._fail(exc, "读取事件推送状态")

    async def web_events_session_save(self):
        try:
            return json_response(
                self.admin.events_session_save(await self._json_payload())
            )
        except Exception as exc:
            return self._fail(exc, "保存会话事件订阅")

    async def web_events_reload(self):
        try:
            return json_response(await self.admin.events_reload())
        except Exception as exc:
            return self._fail(exc, "重连事件通道")

    async def web_paid_summary(self):
        try:
            return json_response(self.admin.paid_summary())
        except Exception as exc:
            return self._fail(exc, "读取付费授权")

    async def web_paid_group_save(self):
        try:
            return json_response(
                self.admin.paid_group_save(await self._json_payload())
            )
        except Exception as exc:
            return self._fail(exc, "保存付费群授权")

    async def web_paid_group_delete(self):
        try:
            return json_response(
                self.admin.paid_group_delete(await self._json_payload())
            )
        except Exception as exc:
            return self._fail(exc, "删除付费群授权")

    async def web_paid_codes_generate(self):
        try:
            return json_response(
                self.admin.paid_codes_generate(await self._json_payload())
            )
        except Exception as exc:
            return self._fail(exc, "生成激活码")

    async def web_paid_codes_delete(self):
        try:
            return json_response(
                self.admin.paid_codes_delete(await self._json_payload())
            )
        except Exception as exc:
            return self._fail(exc, "删除激活码")

    async def web_doubao_test(self):
        try:
            return json_response(await self.admin.doubao_test())
        except Exception as exc:
            return self._fail(exc, "测试豆包")

    async def web_online_test(self):
        try:
            return json_response(await self.admin.online_test(await self._json_payload()))
        except Exception as exc:
            return self._fail(exc, "测试在线查询")


def _query_get(name: str, default: str) -> str:
    try:
        value = request.query.get(name, default)
    except Exception:  # pragma: no cover - defensive
        return default
    if value is None:
        return default
    return str(value)
