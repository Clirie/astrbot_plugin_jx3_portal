"""把装备接口字段整理为角色属性与装备明细。"""
from .utils import format_time
import re


def number(value):
    if isinstance(value, (int, float)):
        return f'{value:,.2f}'.rstrip('0').rstrip('.') if value % 1 else f'{value:,.0f}'
    return str(value if value is not None else '—')


def equipment_view(data, server, name):
    panel = {row['name']:row for row in data.get('panelList',[]) if isinstance(row,dict) and row.get('name')}
    sections = []; used = set()
    for title, fields in [
        ('核心属性', [('会心等级','会心'),('破防等级','破防'),('无双等级','无双'),('加速等级','加速')]),
        ('攻击与生存', [('面板攻击','面板攻击'),('基础攻击','基础攻击'),('治疗成效','治疗成效'),('基础治疗','基础治疗'),('气血上限','气血'),('外功防御','外功防御'),('内功防御','内功防御')]),
    ]:
        values=[]
        for key,label in fields:
            row=panel.get(key) or panel.get(label)
            if not row:continue
            used.add(row['name']);percent=row.get('percent')
            display=number(percent)+'%' if percent is not None and key in {'会心等级','破防等级','无双等级'} else number(row.get('value'))
            secondary=number(percent)+'%' if percent is not None and key not in {'会心等级','破防等级','无双等级'} else ''
            values.append({'name':label,'value':display,'secondary':secondary})
        if values:sections.append({'title':title,'items':values})
    main=[panel[key] for key in ['力道','元气','身法','根骨'] if key in panel]
    primary=max(main,key=lambda row:float(row.get('value') or 0)) if main else None
    others=[]
    for key,row in panel.items():
        if key in used or key.startswith('武器伤害') or key in {'力道','元气','身法','根骨'} and row is not primary:continue
        value=row.get('percent') if row.get('percent') is not None else row.get('value')
        if value in (None,0,'0',''):continue
        others.append({'name':key.replace('等级','').replace('值',''),'value':number(value)+('%' if row.get('percent') is not None else ''),'secondary':''})
    if others:sections.append({'title':'其他属性','items':others})
    slots={0:'武器',2:'暗器',3:'上衣',4:'帽子',5:'项链',6:'戒指',7:'戒指',8:'腰带',9:'腰坠',10:'下装',11:'鞋子',12:'护腕'}
    order={slot:i for i,slot in enumerate([4,3,8,12,10,11,5,9,6,7,2,0])}
    equipment=[]
    for raw in sorted(data.get('equipList',[]),key=lambda row:order.get(row.get('itemIndex'),99)):
        item=dict(raw);enchants=[]
        for key,label in [('minEnchant','附魔'),('maxEnchant','大附魔'),('colorDiamond','五彩石')]:
            value=item.get(key)
            if isinstance(value,dict) and value.get('itemName'):enchants.append({'label':label,'name':value['itemName']})
        stones={};gems=[]
        for gem in item.get('mountDiamond') or []:
            if isinstance(gem,dict) and gem.get('itemName'):
                label=gem['itemName'].replace('五行石（','').replace('）','');stones[label]=stones.get(label,0)+1
                grade=re.search(r'([一二三四五六七八九十0-9]+)级',gem['itemName'])
                gems.append({'grade':grade.group(1) if grade else '', 'name':gem['itemName']})
        item['gems']=gems
        item['refinement']=[i < int(item.get('strengthLevel') or 0) for i in range(int(item.get('maxStrengthLevel') or item.get('strengthLevel') or 0))]
        item.update(slot=slots.get(item.get('itemIndex'),''),enchants=enchants,stones=' · '.join(f'{label} ×{count}' for label,count in stones.items()),magic=' · '.join(word for word in str(item.get('magicType') or '').split(',') if word and word!='伤害'))
        item['icon']='https://icon.jx3box.com/icon/'+str(item['iconId'])+'.png' if str(item.get('iconId') or '').isdigit() else ''
        equipment.append(item)
    return {'title':data.get('roleName') or name,'server':data.get('serverName') or server,'kungfu':data.get('kungfuName') or '', 'force':data.get('forceName') or '', 'identity':' · '.join(str(data[key]) for key in ['bodyName','campName','tongName'] if data.get(key)), 'score':number(data.get('equipScore')), 'kind':data.get('equipType') or '', 'updated':format_time(data.get('cacheTime')), 'sections':sections, 'equipment':equipment}
