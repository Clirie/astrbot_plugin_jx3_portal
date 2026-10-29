from jx3portal.buttons import MenuReply, send_menu
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from jx3portal.replies import ImageReply, MessageParts, PendingReply


class PlainResult(tuple):
    def use_t2i(self, value): return self
    def use_markdown(self, value): return self

def test_all_reply_parts_reach_pipeline_before_stopping():
    tree=ast.parse((Path(__file__).parents[1]/'main.py').read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='JX3PortalPlugin')
    fn=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='on_all_message');fn.decorator_list=[]
    module=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),ast.ClassDef(name='Listener',bases=[],keywords=[],body=[fn],decorator_list=[])],type_ignores=[])
    ns={'asyncio':asyncio,'logger':Mock(),'ImageReply':ImageReply,'MessageParts':MessageParts,'PendingReply':PendingReply,'MenuReply':MenuReply,'send_menu':send_menu,'split_message':lambda t:[t]}
    exec(compile(ast.fix_missing_locations(module),'<listener>','exec'),ns)
    listener=ns['Listener']();listener.telemetry=Mock();listener.command_map={'更新':'announce'};listener.resolve_command=lambda e:('更新',[],'announce');listener.telemetry=Mock()
    async def load():return ImageReply('/tmp/market.jpg')
    async def run():
        for reply,expected in [(MessageParts([{'type':'image','path':'/tmp/one.jpg'},{'type':'image','path':'/tmp/two.jpg'},{'type':'text','text':'日期 标题 https://jx3.xoyo.com/'}]),['image','image','text']),(ImageReply('/tmp/one.jpg',extra_paths=['/tmp/two.jpg']),['image','image']),(PendingReply('商品文字',load),['text','image']),('文字',['text']),(None,[])]:
            e=SimpleNamespace(stopped=False,should_call_llm=Mock(),plain_result=lambda t:PlainResult(('text',t)),image_result=lambda p:('image',p))
            e.stop_event=lambda:setattr(e,'stopped',True);listener.commands=SimpleNamespace(run=AsyncMock(return_value=reply));sent=[]
            async for result in listener.on_all_message(e):
                # AstrBot's scheduler ends a generator when event.is_stopped() is true.
                assert not e.stopped
                sent.append(result[0])
            assert sent==expected and e.stopped
            e.should_call_llm.assert_called_once_with(False)
        e.stopped=False;listener.commands.run=AsyncMock(side_effect=RuntimeError('upstream failure'));sent=[]
        async for result in listener.on_all_message(e):
            assert not e.stopped
            sent.append(result[0])
        assert sent==['text'] and e.stopped
    asyncio.run(run())


def test_announcement_caption_is_in_same_message_as_image():
    tree=ast.parse((Path(__file__).parents[1]/'main.py').read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='JX3PortalPlugin')
    fn=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='on_all_message');fn.decorator_list=[]
    module=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),ast.ClassDef(name='Listener',bases=[],keywords=[],body=[fn],decorator_list=[])],type_ignores=[])
    ns={'asyncio':asyncio,'logger':Mock(),'ImageReply':ImageReply,'MessageParts':MessageParts,'PendingReply':PendingReply,'MenuReply':MenuReply,'send_menu':send_menu,'split_message':lambda t:[t]};exec(compile(ast.fix_missing_locations(module),'<listener>','exec'),ns)
    listener=ns['Listener']();listener.telemetry=Mock();listener.command_map={'更新':'announce'};listener.resolve_command=lambda e:('更新',[],'announce');listener.commands=SimpleNamespace(run=AsyncMock(return_value=ImageReply('/tmp/update.jpg',caption='日期 标题 https://jx3.xoyo.com/')))
    chain=Mock()
    for name in ['file_image','message','use_t2i','use_markdown']:getattr(chain,name).return_value=chain
    event=SimpleNamespace(make_result=Mock(return_value=chain),stop_event=Mock(),should_call_llm=Mock(),image_result=Mock())
    async def run():assert [r async for r in listener.on_all_message(event)]==[chain]
    asyncio.run(run());chain.file_image.assert_called_once_with('/tmp/update.jpg');chain.message.assert_called_once_with('日期 标题 https://jx3.xoyo.com/');chain.use_t2i.assert_called_once_with(False);chain.use_markdown.assert_called_once_with(False);event.image_result.assert_not_called()
