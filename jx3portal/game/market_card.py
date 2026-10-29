"""物价文字资料与相关外观。"""
from datetime import datetime
from zoneinfo import ZoneInfo


def market_card(data, options):
    lines=[('默认查询：' if options else '当前查询：')+str(data.get('name') or '')]
    if options:
        lines+=['','—— 相关外观 ——']
        for key,label in options.items():
            name,_,alias=str(label).partition('｜')
            lines.append(f'{key}. {name}'+(f'（{alias}）' if alias else ''))
        lines+=['','↑ 10 秒内回复序号换款']
    lines+=['','—— 外观资料 ——']
    for label,key in [('别名','alias'),('发售','date'),('官方售价','retail'),('不绑定限时','unbound_duration'),('绑定限时','bound_duration'),('不绑定限量','unbound_limit')]:
        value=data.get(key)
        if value not in (None,'',0):lines.append(label+'：'+str(value)+('元' if key=='retail' else ''))
    lines+=['','—— 报价摘要 ——']
    price_start=len(lines)
    for group in data.get('list') or []:
        if not isinstance(group,dict) or group.get('name')!='在售期':continue
        rows=[row for row in group.get('list',[]) if isinstance(row,dict) and isinstance(row.get('value'),(int,float)) and row['value']>0 and row.get('date')]
        if rows:
            latest=max(str(row['date'])[:10] for row in rows);value=min(row['value'] for row in rows if str(row['date'])[:10]==latest)
            label='万宝楼在售：'+f'{value:,.0f}'+'元起'
            if latest!=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat():label+='（'+latest+'）'
            lines.append(label)
    player_rows=[row for group in data.get('list') or [] if isinstance(group,dict) and group.get('name') not in {'公示期','在售期'} for row in group.get('list',[]) if isinstance(row,dict) and isinstance(row.get('value'),(int,float)) and row['value']>0 and row.get('date')]
    for label,kinds in [('玩家收购',{2,4}),('玩家出售',{1,3}),('玩家成交',{5})]:
        rows=[r for r in player_rows if r.get('sale') in kinds]
        if not rows: continue
        day=max(str(r['date'])[:10] for r in rows);values=sorted({r['value'] for r in rows if str(r['date'])[:10]==day})
        price=f'{values[0]:,.0f}' if len(values)==1 else f'{values[0]:,.0f}–{values[-1]:,.0f}'
        lines.append(label+'：'+price+'元（'+day+'）')
    if len(lines)==price_start: lines=lines[:-2]
    return '\n'.join(lines).strip()
