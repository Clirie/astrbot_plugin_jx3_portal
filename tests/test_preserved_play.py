import asyncio,logging
from datetime import date
from types import SimpleNamespace
from jx3portal.game.tarot import load_deck,draw_cards,reading_topic,select_reading
from jx3portal.game.daily_tarot import daily_card,load_secret
from jx3portal.game.birth_chart import parse_birth,make_bazi
from jx3portal.game.fortune import LoveBook,library
from jx3portal.privacy_logging import ConversationFilter


def test_preserved_deck_topics_and_daily_identity(tmp_path):
    assert len(load_deck())==78
    assert reading_topic('最近能得到想要的外观吗')=='求物'
    cards=draw_cards(3)
    assert len({card['id'] for card in cards})==3
    assert select_reading(cards[0],'求物')['reading']
    secret=load_secret(tmp_path)
    assert len(secret)==32 and load_secret(tmp_path)==secret
    first=daily_card('qq\0alice',secret,date(2026,10,26))
    assert first==daily_card('qq\0alice',secret,date(2026,10,26))
    assert first['signature']!=daily_card('qq\0bob',secret,date(2026,10,26))['signature']
    assert first['signature']!=daily_card('qq\0alice',secret,date(2026,10,27))['signature']


def test_birth_and_answers_stay_offline():
    birth,gender=parse_birth('2000-08-16 04:30 女',True)
    assert len(make_bazi(birth,gender)['pillars'])==4
    assert len(library('love_answers'))==60
    book=LoveBook(library_name='love_answers')
    assert len({book.draw(owner='alice')['id'] for _ in range(12)})==12


def test_chat_log_filter_preserves_metrics():
    guard=ConversationFilter()
    message=logging.LogRecord('astrbot',logging.INFO,'/core/event_bus.py',1,'private body',(),None,func='_print_event')
    assert not guard.filter(message)
    metric=logging.LogRecord('jx3portal',logging.INFO,'service.py',1,'render seconds=2',(),None)
    assert guard.filter(metric)
    traced=logging.LogRecord('astrbot',logging.INFO,'other.py',1,'private trace',(),None)
    traced.category='user_chat'
    assert not guard.filter(traced)
