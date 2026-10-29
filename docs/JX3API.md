# JX3API 接口参考

> 本文件由 JX3API 官方 OpenAPI 文档（https://www.jx3api.com/openapi）整理，记录插件使用的接口路径、等级、Ticket 要求与参数。
>
> 等级说明：LV.0 免费、LV.1 会员、LV.2 高级会员。标注「需 ticket」的接口还必须配置推栏 Ticket。
>
> 插件启动时使用内置功能目录，不依赖本文件运行；本文件仅用于开发和排障。


## `/active/calendar` — 活动日历 (LV.0)

- 分类：活动日历
- 参数：num(integer,可选):天数偏移（单日）或区间半径（list）; mode(string,可选):'day' 单日 / 'list' 前后区间

## `/active/celebs` — 地图活动 (LV.0)

- 分类：活动日历
- 参数：name(string,必填):事件名称

## `/arena/awesome` — 名剑排行 (LV.1) [需ticket]

- 分类：名剑相关
- 参数：mode(integer,必填):服务器名称; limit(integer,必填):显示数量

## `/arena/recent` — 名剑战绩 (LV.1) [需ticket]

- 分类：名剑相关
- 参数：server(string,必填):服务器名称; name(string,必填):角色名称; mode(string,可选):比赛模式

## `/arena/schools` — 名剑统计 (LV.1) [需ticket]

- 分类：名剑相关
- 参数：mode(integer,必填):比赛模式

## `/auction/records` — 阵营拍卖 (LV.2)

- 分类：阵营竞拍
- 参数：server(string,必填):服务器名称; name(string,可选):物品名称; limit(integer,可选):限制数量

## `/battle/records` — 帮战记录 (LV.0)

- 分类：帮战记录
- 参数：server(string,必填):查询信息

## `/calcd/attribute` — 装备属性 (LV.2)

- 分类：角色属性
- 参数：server(string,必填):服务器名称; name(string,必填):角色名称; format(string,可选):返回格式：calcd 返回计算后的装备详情与属性面板，client 返回客户端原始格式

## `/calcd/detail` — 装备详情 (LV.2)

- 分类：角色属性
- 参数：server(string,必填):服务器名称; name(string,必填):角色名称; kungfu(string,必填):心法名称，如花间游; type(string,必填):装备类型：秘境挑战 / 竞技对抗 / 休闲 / 通用; format(string,可选):返回格式：calcd 返回计算后的装备详情与属性面板，client 返回客户端原始格式

## `/calcd/records` — 装备记录 (LV.2)

- 分类：角色属性
- 参数：server(string,必填):服务器名称; name(string,必填):角色名称

## `/card/cached` — 名片缓存 (LV.2)

- 分类：角色名片
- 参数：server(string,必填):服务器名称; name(string,必填):角色名称

## `/card/preset` — 名片预设 (LV.2) [需ticket]

- 分类：角色名片
- 参数：server(string,必填):服务器名称; name(string,必填):角色名称

## `/card/random` — 随机名片 (LV.2)

- 分类：角色名片
- 参数：server(string,必填):服务器名称; force(string,可选):门派名称; body(string,可选):体型名称

## `/card/record` — 名片记录 (LV.2)

- 分类：角色名片
- 参数：server(string,必填):服务器名称; name(string,必填):角色名称

## `/card/records` — 名片历史 (LV.2)

- 分类：角色名片
- 参数：server(string,必填):服务器名称; name(string,必填):角色名称; like(boolean,可选):是否只看点赞

## `/castle/status` — 关隘首领 (LV.2)

- 分类：世界首领
- 参数：无

## `/chat/records` — 角色聊天 (LV.2)

- 分类：聊天记录
- 参数：server(string,必填):服务器名称; name(string,必填):角色名称; limit(integer,可选):每页数量; page(integer,可选):页码

## `/chitu/records` — 今日赤兔 (LV.2)

- 分类：赤兔查询
- 参数：无

## `/chitu/week/records` — 本周赤兔 (LV.2)

- 分类：赤兔查询
- 参数：无

## `/duowan/statistics` — 统战歪歪 (LV.0)

- 分类：多玩语音
- 参数：server(string,可选):服务器名称

## `/event/collect` — 奇遇汇总 (LV.1)

- 分类：奇遇相关
- 参数：server(string,必填):服务器名称; num(integer,可选):统计天数

## `/event/missing` — 未触发的 (LV.1)

- 分类：奇遇相关
- 参数：server(string,必填):服务器名称; name(string,必填):角色名称

## `/event/recent` — 近期奇遇 (LV.1)

- 分类：奇遇相关
- 参数：server(string,必填):服务器名称; limit(integer,可选):显示数量

## `/event/records` — 奇遇记录 (LV.1)

- 分类：奇遇相关
- 参数：server(string,必填):服务器名称; name(string,必填):角色名称; full(integer,可选):是否返回完整列表（含未触发）

## `/event/statistics` — 奇遇统计 (LV.1)

- 分类：奇遇相关
- 参数：server(string,可选):服务器名称; name(string,必填):奇遇名称; limit(integer,可选):显示数量

## `/event/strategy` — 奇遇攻略 (LV.1)

- 分类：奇遇相关
- 参数：name(string,必填):奇遇名称

## `/exam/search` — 科举答案 (LV.0)

- 分类：科举搜索
- 参数：subject(string,必填):科举试题; limit(integer,可选):返回数量

## `/fenxian/records` — 阵营奉献 (LV.2)

- 分类：阵营事件
- 参数：name(string,可选):阵营名称; limit(integer,可选):显示数量

## `/firework/records` — 烟花记录 (LV.2)

- 分类：烟花事件
- 参数：server(string,必填):服务器名称; name(string,必填):角色名称

## `/food/list` — 小吃小药 (LV.0)

- 分类：小吃小药
- 参数：name(string,可选):心法名称

## `/fraud/detail` — 骗子查询 (LV.1)

- 分类：骗子查询
- 参数：server(string,可选):服务器名称; uid(integer,必填):角色 UID

## `/home/flower` — 家园鲜花 (LV.0)

- 分类：家园相关
- 参数：server(string,必填):服务器名称; name(string,可选):鲜花名称; map(string,可选):地图名称

## `/home/furniture` — 家园装饰 (LV.0)

- 分类：家园相关
- 参数：name(string,必填):装饰名称

## `/home/travel` — 器物图谱 (LV.0)

- 分类：家园相关
- 参数：name(string,必填):器物名称

## `/mech/decrypt` — 秘境方位 (LV.1)

- 分类：秘境方位
- 参数：无

## `/mentor/search` — 师徒列表 (LV.1)

- 分类：师徒相关
- 参数：label(integer,必填):师徒类型; server(string,必填):服务器大区; keyword(string,可选):关键字; limit(integer,可选):显示数量

## `/monster/records` — 角色百战 (LV.2)

- 分类：百战记录
- 参数：server(string,必填):服务器名称; name(string,必填):角色名称

## `/monster/weekly` — 百战首领 (LV.2)

- 分类：百战记录
- 参数：无

## `/news/announce` — 维护公告 (LV.0)

- 分类：新闻公告
- 参数：limit(integer,可选):显示数量

## `/news/records` — 新闻资讯 (LV.0)

- 分类：新闻公告
- 参数：limit(integer,可选):显示数量

## `/ranch/chat` — 马场预告 (LV.2)

- 分类：马场查询
- 参数：server(string,必填):服务器名称

## `/ranch/records` — 马场事件 (LV.1)

- 分类：马场查询
- 参数：server(string,必填):服务器名称; expired(integer,可选):是否包含已过期

## `/rank/arena` — 跨服名剑 (LV.2)

- 分类：排行榜单
- 参数：server(string,可选):服务器名称; mode(integer,可选):竞技模式 0=2v2/1=3v3/2=5v5

## `/rank/championship` — 武林争霸 (LV.2)

- 分类：排行榜单
- 参数：server(string,可选):服务器名称; camp(integer,可选):阵营 1=浩气/2=恶人

## `/rank/constable` — 捕快荣誉 (LV.2)

- 分类：排行榜单
- 参数：server(string,可选):服务器名称

## `/rank/outlaw` — 江湖浪客 (LV.2)

- 分类：排行榜单
- 参数：server(string,可选):服务器名称

## `/rank/statistics` — 排行统计 (LV.1)

- 分类：排行榜单
- 参数：server(string,可选):服务器名称; name(string,必填):榜单名称

## `/rank/trials` — 试炼之地 (LV.1)

- 分类：排行榜单
- 参数：server(string,可选):服务器名称; name(string,必填):榜单名称

## `/rank/wanted` — 决斗挑战 (LV.2)

- 分类：排行榜单
- 参数：server(string,可选):服务器名称; mode(integer,可选):1=公开/2=私密

## `/recruit/search` — 团队招募 (LV.1)

- 分类：团队招募
- 参数：server(string,必填):服务器大区; label(integer,必填):服务类型; keyword(string,可选):关键字; limit(integer,必填):显示数量

## `/reward/statistics` — 掉落统计 (LV.1)

- 分类：掉落统计
- 参数：server(string,可选):服务器名称; name(string,必填):物品名称; limit(integer,必填):显示数量

## `/role/achievement` — 成就查询 (LV.2)

- 分类：角色信息
- 参数：server(string,必填):服务器名称; role(string,必填):角色名称; name(string,必填):成就名称

## `/role/detail` — 角色详情 (LV.1)

- 分类：角色信息
- 参数：server(string,必填):服务器大区; name(string,必填):角色名称; history(integer,可选):是否返回改名 / 帮会历史

## `/sand/records` — 沙盘据点 (LV.1)

- 分类：阵营沙盘
- 参数：server(string,必填):服务器名称

## `/saohua/answer` — 答案之书 (LV.0)

- 分类：骚话语录
- 参数：无

## `/saohua/content` — 舔狗日志 (LV.0)

- 分类：骚话语录
- 参数：无

## `/saohua/context` — 分类语录 (LV.2)

- 分类：骚话语录
- 参数：name(string,必填):语录分类（疯狂星期四 / 彩虹屁 / 毒鸡汤 / 朋友圈）

## `/saohua/drink` — 喝什么 (LV.0)

- 分类：骚话语录
- 参数：无

## `/saohua/eat` — 吃什么 (LV.0)

- 分类：骚话语录
- 参数：无

## `/saohua/random` — 随机骚话 (LV.0)

- 分类：骚话语录
- 参数：无

## `/saohua/zhanan` — 渣男语录 (LV.0)

- 分类：骚话语录
- 参数：无

## `/school/matrix` — 阵眼效果 (LV.1) [需ticket]

- 分类：心法配装
- 参数：name(string,必填):职业名称

## `/school/search` — 配装搜索 (LV.2) [需ticket]

- 分类：心法配装
- 参数：name(string,必填):门派名称; mode(string,可选):玩法模式

## `/school/seniority` — 资历榜单 (LV.1) [需ticket]

- 分类：心法配装
- 参数：server(string,可选):服务器名称; school(string,可选):门派名称

## `/school/skills` — 技能信息 (LV.1) [需ticket]

- 分类：心法配装
- 参数：name(string,必填):门派名称; update(integer,可选):是否更新

## `/school/talent` — 奇穴信息 (LV.1) [需ticket]

- 分类：心法配装
- 参数：name(string,必填):门派名称; update(integer,可选):是否更新

## `/server/status/check` — 大区状态 (LV.0)

- 分类：大区状态
- 参数：server(string,可选):服务器名称; type(integer,可选):状态类型：1=数据库合集，其他=xoyo 在线状态

## `/skill/calculate` — 急速计算 (LV.2)

- 分类：急速计算
- 参数：cooldown(number,可选):技能 cd

## `/skill/rework` — 技改记录 (LV.0)

- 分类：急速计算
- 参数：无

## `/sound/converter` — 语音合成 (LV.0)

- 分类：语音合成
- 参数：appkey(string,必填):阿里云 appkey; access(string,必填):AccessKeyId; secret(string,必填):AccessKeySecret; voice(string,可选):发音人; format(string,可选):音频编码; sample_rate(integer,可选):音频采样率; volume(string,可选):音量; speech_rate(string,可选):语速; pitch_rate(string,可选):语调; text(string,必填):语音内容

## `/steed/records` — 的卢拍卖 (LV.2)

- 分类：的卢拍卖
- 参数：server(string,可选):服务器名称

## `/tieba/item/records` — 外观记录 (LV.1)

- 分类：百度贴吧
- 参数：server(string,可选):服务器名称; name(string,必填):物品名称; limit(integer,可选):返回数量

## `/tieba/random` — 百度贴吧 (LV.1)

- 分类：百度贴吧
- 参数：tags(string,必填):帖子类型; server(string,可选):服务器名称; limit(integer,可选):返回数量

## `/trade/demon` — 金价行情 (LV.1)

- 分类：物价交易
- 参数：server(string,可选):服务器名称; limit(integer,可选):显示数量

## `/trade/item/records` — 外观价格 (LV.1)

- 分类：物价交易
- 参数：name(string,必填):物品名称; server(string,可选):服务器名称

## `/trade/item/search` — 外观搜索 (LV.1)

- 分类：物价交易
- 参数：name(string,必填):物品名称

## `/trade/manufacture` — 成本计算 (LV.2)

- 分类：物价交易
- 参数：server(string,必填):服务器名称; name(string,必填):成品名称; source(integer,可选):价格来源 0=交易行/1=jx3box

## `/trade/records` — 物品价格 (LV.1)

- 分类：物价交易
- 参数：name(string,必填):物品名称; server(string,可选):服务器名称

## `/trade/wanbaolou` — 编号搜索 (LV.2)

- 分类：物价交易
- 参数：id(string,必填):角色编号

## `/trial/bosses` — 秒伤计算 (LV.1)

- 分类：试炼之地
- 参数：season(string,必填):赛季名称：暗影千机 / 山海源流 / 太极秘录 / 丝路风语; floor(integer,必填):层数 1-120

## `/trial/seasons` — 赛季列表 (LV.1)

- 分类：试炼之地
- 参数：无

## `/tuilan/achievement` — 资历分布 (LV.2) [需ticket]

- 分类：资历分布
- 参数：server(string,必填):服务器名称; name(string,必填):角色名称; class(integer,可选):资历分类; subclass(string,可选):资历子类

## `/wicked/records` — 诛恶事件 (LV.2)

- 分类：诛恶事件
- 参数：server(string,可选):服务器名称; limit(integer,可选):显示数量
