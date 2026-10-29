"""QQ native command buttons; business actions still use the normal command path."""
import asyncio
import logging
import random
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class Button:
    label: str
    command: str
    enter: bool = True

@dataclass
class MenuReply:
    text: str
    buttons: tuple[Button, ...]
    owner: str = ''

    def fallback(self):
        return self.text + '\n\n' + '\n'.join(f'{button.label}：{button.command}' for button in self.buttons)


def keyboard(menu):
    buttons = []
    for index, button in enumerate(menu.buttons):
        permission = {'type':0, 'specify_user_ids':[menu.owner]} if menu.owner else {'type':2}
        buttons.append({'id':str(index), 'render_data':{'label':button.label[:30], 'visited_label':button.label[:30], 'style':1}, 'action':{'type':2, 'data':'/' + button.command.lstrip('/'), 'enter':button.enter, 'permission':permission, 'unsupport_tips':'请使用文字指令'}})
    columns = 2 if len(buttons) <= 10 else 3 if len(buttons) <= 15 else 5
    return {'content':{'rows':[{'buttons':buttons[i:i+columns]} for i in range(0,len(buttons),columns)]}}


async def send_menu(event, menu):
    if not hasattr(event, 'get_platform_name') or event.get_platform_name() not in {'qq_official','qq_official_webhook'}: return False
    if not 1 <= len(menu.buttons) <= 25: return False
    raw = event.message_obj.raw_message
    api = event.bot.api
    group = getattr(raw, 'group_openid', None)
    user = getattr(raw, 'user_openid', None) or getattr(getattr(raw, 'author', None), 'user_openid', None)
    if not group and not user: return False
    payload = {'msg_type':2, 'markdown':{'content':menu.text.strip()}, 'keyboard':keyboard(menu), 'msg_id':event.message_obj.message_id, 'msg_seq':random.randint(1,9999)}
    try:
        async with asyncio.timeout(8):
            result = await api.post_group_message(group_openid=group, **payload) if group else await api.post_c2c_message(openid=user, **payload)
        if not result: return False
        event._has_send_oper = True
        return True
    except Exception as exc:
        logger.warning('QQ button delivery failed: %s', type(exc).__name__)
        return False
