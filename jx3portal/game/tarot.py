"""Offline tarot draws backed by the bundled 78-card reference library."""
import asyncio
import base64
import json
import re
import secrets
import time
from collections import OrderedDict, deque
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from .data import load_template

ROOT = Path(__file__).resolve().parents[2]

TOPICS = {
    '求物': ('获取与进展', r'外观|装备|玄晶|大铁|宠物|坐骑|掉落|奇遇|物品|东西|礼物|奖品|抽奖|抽中|抢购|买到|抢到'),
    '感情': ('感情与相处', r'爱情|感情|恋爱|恋人|伴侣|男友|女友|男朋友|女朋友|暗恋|表白|告白|暧昧|结婚|分手|复合|喜欢的人|他喜欢我|她喜欢我|青睐|追到'),
    '事业': ('工作与事业', r'工作|事业|求职|面试|升职|升迁|加薪|职场|同事|老板|客户|项目|录用|合同|offer'),
    '学业': ('学习与考试', r'学习|学业|考试|考研|考公|论文|毕业|学校|成绩|考上|录取|上岸|考证'),
}
RELATIONSHIP_ONLY = re.compile(
    r'爱情|爱意|爱恋|恋爱|情感|感情|浪漫|婚|伴侣|心碎|失恋|情欲|分手|爱与|真爱|爱的|恋人|恋情|情伤|爱上|'
    r'关系|家庭|家人|亲密|亲情|友情|友谊|相互吸引|吸引力|身心契合|不忠|渐行渐远'
)


def reading_topic(question):
    """Explicit prefix wins; ambiguous questions keep the general reading."""
    if not question:
        return '综合'
    explicit = re.match(r'^(求物|感情|事业|学业|综合)(?:$|[\s：:])', question)
    if explicit:
        return explicit.group(1)
    matched = [topic for topic, (_, pattern) in TOPICS.items() if re.search(pattern, question, re.I)]
    if len(matched) == 1:
        return matched[0]
    if len(matched) > 1:
        return '综合'
    if re.search(r'得到|获得|拿到|获取|能出|会出', question):
        return '求物'
    return '综合'


def select_reading(card, topic):
    """Keep a short, topic-relevant excerpt from the actual orientation."""
    meaning = card['reversed' if card['reversed_card'] else 'upright']
    if topic in ('求物', '事业', '学业'):
        meaning = [text for text in meaning if not RELATIONSHIP_ONLY.search(text)]
    if topic == '求物':meaning = [text for text in meaning if not re.search(r'学业|事业|工作|投资|财务|家族|健康|职场',text)]
    if topic == '学业':meaning = [text for text in meaning if not re.search(r'财务|投资|家族|财富|事业|工作|职场',text)]
    if topic == '事业':meaning = [text for text in meaning if not re.search(r'学业|考试|家族|健康',text)]
    focus = {'求物':r'机会|机遇|时机|愿望|心愿|目标|资源|等待|进展|回报|收获|成果|选择', '感情':r'感情|关系|沟通|情感|亲密|信任|相处|表达|相互', '事业':r'工作|事业|目标|协作|合作|计划|成果|领导|团队', '学业':r'学习|专注|求知|精进|知识|实践|目标|计划'}
    if topic in focus:meaning = sorted(meaning,key=lambda text:not bool(re.search(focus[topic],text)))
    # The source lists alternative facets, not six simultaneous verdicts.
    selected=[]
    for text in meaning:
        if any(len(set(text)&set(old))/max(1,len(set(text)|set(old)))>.45 for old in selected):continue
        selected.append(text)
        if len(selected)==3:break
    return {**card, 'reading': '，'.join(selected) + '。', 'keywords': []}


@lru_cache(maxsize=1)
def load_deck() -> tuple[dict, ...]:
    cards = json.loads((ROOT / 'data/tarot/cards.json').read_text(encoding='utf-8'))
    if len(cards) != 78 or len({card['id'] for card in cards}) != 78:
        raise ValueError('塔罗牌库需要 78 张不同的牌')
    for card in cards:
        if not all(card.get(key) for key in ('name', 'upright', 'reversed', 'symbolism', 'story')):
            raise ValueError('塔罗牌义不完整')
        if not (ROOT / 'templates/assets/tarot' / (card['id'] + '.jpg')).is_file():
            raise ValueError('塔罗牌面不完整')
    return tuple(cards)


@lru_cache(maxsize=78)
def card_image(card_id: str) -> str:
    # IDs originate exclusively from the packaged deck, never a message path.
    if card_id not in {card['id'] for card in load_deck()}:
        raise ValueError('无效牌面')
    raw = (ROOT / 'templates/assets/tarot' / (card_id + '.jpg')).read_bytes()
    return 'data:image/jpeg;base64,' + base64.b64encode(raw).decode('ascii')


def draw_cards(count: int, rng=None, exclude=()) -> list[dict]:
    if count not in (1, 3):
        raise ValueError('支持单张抽牌或三张牌阵')
    random = rng or secrets.SystemRandom()
    chosen = random.sample([card for card in load_deck() if card['id'] not in exclude], count)
    positions = ('本次抽牌',) if count == 1 else ('现状', '影响', '方向')
    result = []
    for card, position in zip(chosen, positions):
        reversed_ = bool(random.getrandbits(1))
        result.append({**card, 'position': position, 'reversed_card': reversed_,
                       'orientation': '逆位' if reversed_ else '正位',
                       'reading': '；'.join(card['reversed' if reversed_ else 'upright']) + '。',
                       'image': card_image(card['id'])})
    return result


class TarotDeck:
    def __init__(self, rng=None, clock=time.monotonic):
        self.rng=rng or secrets.SystemRandom();self.clock=clock;self.recent=OrderedDict()

    def draw(self, count, owner):
        now=self.clock()
        while self.recent and next(iter(self.recent.values()))[0]<=now:self.recent.popitem(last=False)
        history=self.recent.pop(owner,(0,deque(maxlen=6)))[1]
        cards=draw_cards(count,self.rng,history)
        history.extend(card['id'] for card in cards)
        if owner:
            self.recent[owner]=(now+1800,history)
            while len(self.recent)>512:self.recent.popitem(last=False)
        return cards


async def tarot_reading(question: str = '', count: int = 1, deck=None, owner='') -> dict:
    question = str(question or '').strip()
    if len(question) > 100:
        return {'code': 0, 'msg': '问题请控制在 100 字以内。例：塔罗 最近的工作安排', 'data': {}, 'temp': ''}
    topic = reading_topic(question)
    # Validate the bundled deck off the event loop on the first draw.
    try:
        await asyncio.to_thread(load_deck)
        cards = deck.draw(count,owner) if deck else draw_cards(count)
    except (OSError, ValueError):
        return {'code': 0, 'msg': '塔罗牌库暂时不可用，请联系管理员检查牌面与牌义文件。', 'data': {}, 'temp': ''}
    template = await load_template('tarot.html')
    return {'code': 200, 'msg': 'ok', 'temp': template, 'data': {
        'cards': [select_reading(card, topic) for card in cards],
        'question': re.sub(r'^(求物|感情|事业|学业|综合)(?:[\s：:]+|$)', '', question),
        'topic_key': topic,
        'topic': TOPICS[topic][0] if topic in TOPICS else '通用牌义',
        'spread': '单张抽牌' if count == 1 else '三张牌阵',
        'date': datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y.%m.%d'),
    }}
