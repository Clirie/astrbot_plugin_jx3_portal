"""从咩咩的业务处理迁入；请求、权限与出图共用百宝箱服务。"""
from __future__ import annotations
import asyncio,hashlib,html,json,logging,math,re,time
from dataclasses import dataclass
from copy import deepcopy
from datetime import datetime
from typing import Any,Dict,List,Optional
from urllib.parse import urlsplit,urlunsplit,urlencode
from ..jx3api import JX3APIError,MissingCredential
from ..http import HttpError
from .market_design import market_page
from .utils import gold_to_parts,week_to_num,compare_date_str,format_time,format_remaining
from .tuilan_cd import CD_CACHE_ENDPOINT,TuilanCDClient,TuilanCDError,build_cd_page
logger=logging.getLogger(__name__)

@dataclass
class APIErrorResponse:
    code: Any
    message: str

def text_part(value): return {"type":"text","text":str(value)}
def image_part(value): return {"type":"image","path":str(value)}
async def load_template(name): return name.removesuffix(".html")

ROLE_RANK_NAMES = {
    "名士五十强",
    "老江湖五十强",
    "兵甲藏家五十强",
    "名师五十强",
    "阵营英雄五十强",
    "薪火相传五十强",
    "庐园广记一百强",
}

TONG_RANK_NAMES0 = {
    "赛季恶人五十强",
    "赛季浩气五十强",
    "本周恶人五十强",
    "本周浩气五十强",
}

TONG_RANK_NAMES1 = {
    "浩气神兵宝甲五十强",
    "恶人神兵宝甲五十强",
    "浩气爱心帮会五十强",
    "恶人爱心帮会五十强",
}

TONG_RANK_NAMES2 = {
    "上周恶人五十强",
    "上周浩气五十强",
}

GUILD_RANK_OPTIONS = {
    "1": "浩气神兵宝甲五十强",
    "2": "恶人神兵宝甲五十强",
    "3": "浩气爱心帮会五十强",
    "4": "恶人爱心帮会五十强",
}

CAMP_RANK_OPTIONS = {
    "1": "赛季恶人五十强",
    "2": "赛季浩气五十强",
    "3": "上周恶人五十强",
    "4": "上周浩气五十强",
    "5": "本周恶人五十强",
    "6": "本周浩气五十强",
}

OTHER_RANK_OPTIONS = {
    "1": "名士五十强",
    "2": "老江湖五十强",
    "3": "兵甲藏家五十强",
    "4": "名师五十强",
    "5": "阵营英雄五十强",
    "6": "薪火相传五十强",
    "7": "庐园广记一百强",
}

RANK_NAMES = frozenset().union(
    ROLE_RANK_NAMES,
    TONG_RANK_NAMES0,
    TONG_RANK_NAMES1,
    TONG_RANK_NAMES2,
)

class GameData:
    def __init__(self,api,settings):
        self.api=api
        self.settings=settings
        self._config=settings._config
        self._cache=None
        self._tuilan_cd=TuilanCDClient()

    @property
    def token(self): return self.settings.token
    @property
    def ticket(self): return self.settings.ticket

    async def close(self):
        await self._tuilan_cd.close()

    async def _cached_request(self,path,params=None,out="data",force_refresh=False):
        params={k:v for k,v in (params or {}).items() if k not in {"token","ticket"}}
        fresh=force_refresh or path.startswith("/card/")
        try:
            data=await self.api.request(path,params,use_cache=not fresh)
        except JX3APIError as exc:
            message="暂无相关记录。" if str(exc.code) in {"400","404"} else "查询服务暂不可用，请稍后再试。"
            if str(exc.code) in {"401","403"}:message="当前查询凭据无权读取这项数据，请联系管理员。"
            return APIErrorResponse(exc.code,message),{}
        return deepcopy(data),{}

    async def _request_api(self,path,params,processor=None,template=None,force_refresh=False):
        result=self._init_return_data()
        data,metadata=await self._cached_request(path,params,force_refresh=force_refresh)
        if isinstance(data,APIErrorResponse):return {"code":data.code,"msg":data.message}
        if data is None:return {"code":404,"msg":"暂无相关记录。"}
        if processor:await processor(data,result)
        else:result["data"]=data
        if not result.get("data"):
            result.update(code=404,msg=result.get("msg") or "暂无相关记录。")
            return result
        if isinstance(result["data"],str):template=""
        result.update(code=200,temp=(template or "").removesuffix(".html"),_cache=metadata)
        return result

    def _init_return_data(self) -> Dict[str, Any]:
            """初始化标准的返回数据结构"""
            return {
                "code": 0,
                "msg": "",
                "data": {},
                "temp": "",
                "icons": {}
            }

    async def xingxiashijian(self,name: str) -> Dict[str, Any]:
        """地图活动"""
        # 数据处理
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:
            return_data["data"]["items"] = data
            return_data["data"]["name"] = name

        return await self._request_api(
            path="/active/celebs",
            params={ "name": name},
            processor=processor,
            template="xingxiashijian.html"
        )

    async def guanaishouling(self) -> Dict[str, Any]:
        """关隘首领"""
        # 数据处理
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:
            groups = [
                {
                    "server": group.get("server", ""),
                    "records": [
                        {
                            "camp_name": item.get("campName", ""),
                            "castle": item.get("castle", ""),
                            "str_status": item.get("statusText", ""),
                            "start_time": format_time(item.get("startTime")),
                            "end_time": format_time(item.get("endTime")),
                            "remaining_time": format_remaining(item.get("endTime")),
                        }
                        for item in group.get("data", [])
                        if isinstance(item, dict)
                    ],
                }
                for group in data
                if isinstance(group, dict) and group.get("data")
            ]

            groups = [group for group in groups if group["records"]]

            if not groups:
                return_data["msg"] = "未查询到关隘首领信息"
                return return_data

            return_data["data"] = {
                "groups": groups,
                "update_time": ""
            }

        return await self._request_api(
            path="/castle/status",
            params={"token": self.token},
            processor=processor,
            template="guanaishouling.html"
        )

    async def benrichitu(self) -> Dict[str, Any]:
        """本日赤兔"""
        # 数据处理
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:
            if not data or not isinstance(data, list):
                return_data["data"] = "今日赤兔 暂无数据"
                return 
            
            result_lines = ["今日赤兔"]
            for item in data:
                result_lines.extend([
                    f"时间：{item['date']}",
                    f"区服：{item['server']}",
                    f"地图：{item['mapName']}",
                ])

            return_data["data"] = "\n".join(result_lines).rstrip()
            
        return await self._request_api(
            path="/chitu/records",
            params={"token": self.token},
            processor=processor,
            template=""
        )        

    async def benzhouchitu(self) -> Dict[str, Any]:
        """本周赤兔"""
        # 数据处理
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:
            if not data or not isinstance(data, list):
                return_data["data"] = "本周赤兔 暂无数据"
                return 
            
            result_lines = ["本周赤兔"]
            for item in data:
                result_lines.extend([
                    f"时间：{item['date']}",
                    f"区服：{item['server']}",
                    f"地图：{item['mapName']}",
                ])

            return_data["data"] = "\n".join(result_lines).rstrip()
            
        return await self._request_api(
            path="/chitu/week/records",
            params={"token": self.token},
            processor=processor,
            template=""
        )  

    async def zhenyingevent(self,name: str,limit: str) -> Dict[str, Any]:
        """阵营事件"""
        # 数据处理
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:
            for item in data:
                item["seizeTime"] = format_time(item.get("seizeTime"))

            return_data["data"] = {
                "items": data,
                "update_time": ""
            }
            
        return await self._request_api(
            path="/fenxian/records",
            params={"token": self.token,"name": name, "limit": limit},
            processor=processor,
            template="zhenyingevent.html"
        )  

    async def yanhuachaxun(self, server: str, name: str, limit: int) -> Dict[str, Any]:
        """烟花记录"""
        # 数据处理
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:
            data = data[:limit]
            for item in data:
                item["time"] = format_time(item.get("time"))

            return_data["data"]["list"] = data
            
        return await self._request_api(
            path="/firework/records",
            params={"token": self.token,"name": name, "server": server},
            processor=processor,
            template="yanhuan.html"
        )  

    async def shuma(self,server:str) -> Dict[str, Any]:
        """刷马"""
        # 数据处理
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:    
            return_data["data"] = (
                f"【阴山大草原】\n{', '.join(data.get('阴山大草原') or [])}\n"
                f"【鲲鹏岛】\n{', '.join(data.get('鲲鹏岛') or [])}\n"
                f"【黑戈壁】\n{', '.join(data.get('黑戈壁') or [])}\n"
            )
            
        return await self._request_api(
            path="/ranch/chat",
            params={"token": self.token, "server": server},
            processor=processor,
            template=""
        )  

    async def machang(self, server: str, expired: int) -> Dict[str, Any]:
        """马场"""
        # 数据处理
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            data0 = data.get("data") 
            return_data["data"] = (
                f"【区服】：{data.get('server')}\n"
                f"【阴山大草原】\n{', '.join(data0.get('阴山大草原') or [])}\n"
                f"【鲲鹏岛】\n{', '.join(data0.get('鲲鹏岛') or [])}\n"
                f"【黑戈壁】\n{', '.join(data0.get('黑戈壁') or [])}\n"
                f"【龙泉府 / 进图（21:10）】\n{', '.join(data0.get('龙泉府 / 进图（21:10）') or [])}\n"
                f"\n{data.get('note')}\n"
            )
            
        return await self._request_api(
            path="/ranch/records",
            params={"token": self.token, "server": server, "expired": expired},
            processor=processor,
            template=""
        )  

    async def zhanji(self, name: str, server:str, mode:str) -> Dict[str, Any]:
        """战绩"""
        # 数据处理
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:
            performance_key = {
                "22": "2v2",
                "33": "3v3",
                "55": "5v5",
            }.get(str(mode), "3v3")
            performance = data.get("performance") or {}
            current = performance.get(performance_key) if isinstance(performance, dict) else None
            return_data["data"] = dict(
                data, currentPerformance=current if isinstance(current, dict) else {},
                mode_name=performance_key, history=data.get("history") or [],
            )
            
        return await self._request_api(
            path="/arena/recent",
            params={"server": server, "name":name, "mode":mode, "token": self.token, "ticket": self.ticket},
            processor=processor,
            template="zhanji.html"
        )  

    async def mingjianpaihang(self, limit: str, mode:str) -> Dict[str, Any]:
        """名剑排行"""
        # 数据处理
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            return_data["data"]["lists"] = data
            return_data["data"]["mode"] = mode
            
        return await self._request_api(
            path="/arena/awesome",
            params={"limit": limit, "mode":mode, "token": self.token, "ticket": self.ticket},
            processor=processor,
            template="mingjianpaihang.html"
        )          

    async def mingjiantongji(self, mode: str) -> Dict[str, Any]:
        """名剑统计"""
        # 数据处理
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            return_data["data"] = {
                "items": data,
                "mode": mode,
                "update_time": ""
            }
            
        return await self._request_api(
            path="/arena/schools",
            params={"mode": mode, "token": self.token, "ticket": self.ticket},
            processor=processor,
            template="mingjiantongji.html"
        )         

    async def kuafumingjian(self, server: str, mode: int = 1) -> Dict[str, Any]:
        """跨服名剑榜。"""
        mode_names = {0: "2v2", 1: "3v3", 2: "5v5"}

        async def processor(data: Any, return_data: Dict[str, Any]) -> None:
            items = data.get("data") or []
            if not isinstance(items, list):
                items = []

            return_data["data"] = {
                "items": [item for item in items if isinstance(item, dict)],
                "name": data.get("name") or "跨服名剑榜",
                "server": data.get("server") or server or "全区",
                "mode_name": mode_names[mode],
                "update_time": format_time(data.get("time")),
            }

        return await self._request_api(
            path="/rank/arena",
            params={"server": server, "mode": mode, "token": self.token},
            processor=processor,
            template="kuafumingjian.html",
        )

    async def wulinzhengba(self, server: str, camp: int = 1) -> Dict[str, Any]:
        """武林争霸赛帮会榜。"""
        camp_names = {1: "浩气盟", 2: "恶人谷"}

        def format_match_time(value: Any) -> str:
            try:
                total_seconds = int(value)
            except (TypeError, ValueError):
                return ""
            if total_seconds < 0:
                return ""

            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours:
                return f"{hours}时{minutes:02d}分{seconds:02d}秒"
            return f"{minutes}分{seconds:02d}秒"

        async def processor(data: Any, return_data: Dict[str, Any]) -> None:
            items = data.get("data") or []
            if not isinstance(items, list):
                items = []

            rank_items = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                rank_item = item.copy()
                rank_item["lastMatchTimeText"] = format_match_time(
                    item.get("lastMatchTime")
                )
                rank_items.append(rank_item)

            return_data["data"] = {
                "items": rank_items,
                "name": data.get("name") or "武林争霸赛",
                "server": data.get("server") or server or "全区",
                "camp_name": camp_names[camp],
                "update_time": format_time(data.get("time")),
            }

        return await self._request_api(
            path="/rank/championship",
            params={"server": server, "camp": camp, "token": self.token},
            processor=processor,
            template="wulinzhengba.html",
        )

    async def _bounty_rank(self,server: str,path: str,fallback_name: str,show_hostile_count: bool,) -> Dict[str, Any]:
        """处理捕快荣誉和江湖浪客共用的榜单结构。"""

        async def processor(data: Any, return_data: Dict[str, Any]) -> None:
            items = data.get("data") or []
            if not isinstance(items, list):
                items = []

            return_data["data"] = {
                "items": [item for item in items if isinstance(item, dict)],
                "name": data.get("name") or fallback_name,
                "server": data.get("server") or server or "全区",
                "show_hostile_count": show_hostile_count,
                "update_time": format_time(data.get("time")),
            }

        return await self._request_api(
            path=path,
            params={"server": server, "token": self.token},
            processor=processor,
            template="bounty_rank.html",
        )

    async def bukairongyu(self, server: str) -> Dict[str, Any]:
        """捕快荣誉榜。"""
        return await self._bounty_rank(
            server=server,
            path="/rank/constable",
            fallback_name="捕快荣誉榜",
            show_hostile_count=False,
        )

    async def jianghulangke(self, server: str) -> Dict[str, Any]:
        """江湖浪客榜。"""
        return await self._bounty_rank(
            server=server,
            path="/rank/outlaw",
            fallback_name="江湖浪客榜",
            show_hostile_count=True,
        )

    async def juedoutiaozhan(self,server: str,mode: int = 1,) -> Dict[str, Any]:
        """决斗挑战榜。"""
        mode_names = {1: "公开", 2: "私密"}

        async def processor(data: Any, return_data: Dict[str, Any]) -> None:
            items = data.get("data") or []
            if not isinstance(items, list):
                items = []

            now_timestamp = int(datetime.now().timestamp())
            rank_items = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                rank_item = item.copy()
                try:
                    timeout = int(item.get("timeOut"))
                except (TypeError, ValueError):
                    remaining_time = ""
                else:
                    remaining_time = (
                        format_remaining(timeout)
                        if timeout > now_timestamp
                        else "已结束"
                    )
                rank_item["remainingTime"] = remaining_time
                rank_items.append(rank_item)

            return_data["data"] = {
                "items": rank_items,
                "name": data.get("name") or "决斗挑战榜",
                "server": data.get("server") or server or "全区",
                "mode_name": mode_names[mode],
                "update_time": format_time(data.get("time")),
            }

        return await self._request_api(
            path="/rank/wanted",
            params={"server": server, "mode": mode, "token": self.token},
            processor=processor,
            template="juedoutiaozhan.html",
        )

    async def rank_statistical(self, name: str, server: str) -> Dict[str, Any]:
        """排行榜单"""

        if name in ROLE_RANK_NAMES:
            template_name = "rank_role.html"
        elif name in TONG_RANK_NAMES0:
            template_name = "rank_tong0.html"
        elif name in TONG_RANK_NAMES1:
            template_name = "rank_tong1.html"
        elif name in TONG_RANK_NAMES2:
            template_name = "rank_tong2.html"

        # 数据处理
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            items = data.get("data") or []
            if isinstance(items, list):
                items = items[:50]
            else:
                items = []

            return_data["data"] = {
                "items": items,
                "server": data.get("server", server),
                "rank_name": data.get("name", name),
                "update_time": ""
            }
            
        return await self._request_api(
            path="/rank/statistics",
            params={"server": server, "name": name, "token": self.token},
            processor=processor,
            template=template_name
        )   

    async def shilianpaixing(self, name: str, server: str) -> Dict[str, Any]:
        """试炼排行"""
        # 数据处理
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            items = data.get("data", [])

            return_data["data"] = {
                "items": items,
                "name": data.get("name", name),
                "server": data.get("server", server),
                "update_time": format_time(data.get("time"))
            }
            
        return await self._request_api(
            path="/rank/trials",
            params={"server": server,"name": name,"token": self.token,},
            processor=processor,
            template="shilianpaixing.html"
        )   

    async def zhengyingpaimai(self, server: str, name: str, limit: int) -> Dict[str, Any]:
        """阵营拍卖"""
        # 数据处理
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            for item in data:
                item["time"] =  format_time(item["time"])
            return_data["data"]["list"] = data

            return_data["data"]["trend_svg"] = self._trend_svg(
                [
                    (
                        str(item.get("time") or "")[:10],
                        self._parse_gold_amount(item.get("itemAmount")),
                    )
                    for item in data or []
                    if isinstance(item, dict)
                ],
                title="拍卖成交价走势",
                unit="金",
                limit=14,
                fmt=lambda value: f"{value:,.0f}",
            )
            
        return await self._request_api(
            path="/auction/records",
            params={"server": server, "name": name, "limit": limit, "token": self.token},
            processor=processor,
            template="zhengyingpaimai.html"
        )           

    async def dilujilu(self, server: str) -> Dict[str, Any]:
        """的卢拍卖"""
        # 数据处理
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            for item in data:
                item["refreshTime"] = format_time(item["refreshTime"]) 
                item["captureTime"] = format_time(item["captureTime"])
                item["auctionTime"] = format_time(item["auctionTime"])
            return_data["data"]["list"] = data

            return_data["data"]["trend_svg"] = self._trend_svg(
                [
                    (
                        str(item.get("auctionTime") or "")[:10],
                        self._parse_gold_amount(item.get("auctionAmount")),
                    )
                    for item in data or []
                    if isinstance(item, dict)
                ],
                title="的卢拍卖价走势",
                unit="金",
                limit=14,
                fmt=lambda value: f"{value:,.0f}",
            )
            
        return await self._request_api(
            path="/steed/records",
            params={"server": server, "token": self.token},
            processor=processor,
            template="dilujilu.html"
        ) 

    async def chengbeng(self, Name: str, server: str, source: int):
        return await self.recipe(server, Name, source)

    async def recipe(self, server, name, source=0):
        data,_=await self._cached_request('/trade/manufacture',{'name':name,'server':server,'source':source})
        if isinstance(data,APIErrorResponse):return {'code':data.code,'msg':data.message}
        if not data or not data.get('items'):return {'code':404,'msg':'没有找到这个制作配方。'}
        rows=[];updated=[]
        for row in data['items']:
            price=row.get('price');value=price.get('lowestPrice') if isinstance(price,dict) else price
            if isinstance(price,dict) and price.get('updatedAt'):updated.append(price['updatedAt'])
            quantity=row.get('quantity',0)
            rows.append([row.get('name',''),quantity,'商店' if row.get('type')=='store' else '交易行',f'{value/10000:,.2f}' if isinstance(value,(int,float)) else '—',f'{value*quantity/10000:,.2f}' if isinstance(value,(int,float)) else '—'])
        minimum=data.get('createItemMin');maximum=data.get('createItemMax');total=(data.get('total') or {}).get('lowestTotal')
        facts=[('精力',data.get('costVigor','—')),('产出',str(minimum) if minimum==maximum else f'{minimum}–{maximum}'),('单位','金')]
        if total is not None:facts.append(('材料最低合计',f'{total/10000:,.2f} 金'))
        if updated:facts.append(('报价日期',format_time(min(updated))[:10]+' — '+format_time(max(updated))[:10]))
        return {'code':200,'temp':'game_records','data':{'title':data.get('name') or name,'subtitle':server+' · 制作配方','facts':facts,'columns':['材料','数量','来源','最低单价','小计'],'rows':rows,'description':'\n'.join(tip.get('text','') for tip in data.get('tipInfo',[]))}}

    async def bianhao(self, id: str) -> Dict[str, Any]:
        """编号搜索"""
        # 数据处理
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            if not isinstance(data, dict):
                return_data["data"] = "账号角色数据格式错误"
                return

            # 同时兼容完整接口数据和直接传入 data 字段
            data = data.get("data", data)

            if not isinstance(data, dict):
                return_data["data"] = "账号角色数据为空"
                return

            # 将 replyContent 中的 HTML 转换为纯文本
            detail = str(data.get("replyContent") or "")
            detail = re.sub(r"<br\s*/?>", "\n", detail, flags=re.IGNORECASE)
            detail = re.sub(r"<[^>]+>", "", detail)
            detail = html.unescape(detail).strip() or "暂无账号详细信息"

            # 交易状态
            trade_status = {
                1: "公示中",
                2: "出售中",
                3: "出售中",
                4: "已售出",
                5: "已下架",
            }.get(data.get("tradeStatus"), f"状态码 {data.get('tradeStatus', '未知')}")

            # 调价记录，接口中的时间为毫秒时间戳
            update_prices = data.get("updatePrices") or []
            update_price_text = "\n".join(
                f"{index}. {format_time(int(item.get('updateTime') or 0) // 1000)}："
                f"{item.get('updatePrice', 0)} 元"
                for index, item in enumerate(update_prices, start=1)
                if isinstance(item, dict)
            ) or "暂无调价记录"

            return_data["data"] = (
                f"【万宝楼账号】\n"
                f"{data.get('replyTitle') or '暂无标题'}\n\n"

                f"【角色信息】\n"
                f"区服：{data.get('serverName') or '未知'}\n"
                f"角色：{data.get('roleName') or '未知'}\n"
                f"等级：{data.get('roleLevel') or 0}\n"
                f"门派：{data.get('forceName') or '未知'}\n"
                f"体型：{data.get('bodyName') or '未知'}\n"
                f"阵营：{data.get('campName') or '未知'}\n\n"

                f"【账号数据】\n"
                f"装备分数：{data.get('equipScore') or 0}\n"
                f"江湖资历：{data.get('seniorityNum') or 0}\n"
                f"约见次数：{data.get('meetingNum') or 0}\n"
                f"关注人数：{data.get('followNum') or 0}\n\n"

                f"【交易信息】\n"
                f"挂牌价格：{data.get('priceNum') or 0} 元\n"
                f"交易状态：{trade_status}\n"
                f"商品编号：{data.get('id') or '未知'}\n"
                f"发布时间：{format_time(data.get('replyTime') or 0)}\n\n"

                f"【调价记录】\n"
                f"{update_price_text}\n\n"

                f"【账号详情】\n"
                f"{detail}"
            )
            
        return await self._request_api(
            path="/trade/wanbaolou",
            params={"id": id,"token": self.token},
            processor=processor,
            template=""
        ) 

    async def bangzhanjilu(self, server: str) -> Dict[str, Any]:
        """帮战记录"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            for item in data:
                item["startTime"] = format_time(item["startTime"])
                item["durationSeconds"] = format_remaining(item["durationSeconds"])
                item["endTime"] = format_time(item["endTime"])

            return_data["data"] = {
                "items": data,
                "server": server,
                "update_time": "",
            }
            
        return await self._request_api(
            path="/battle/records",
            params={"server": server},
            processor=processor,
            template="bangzhanjilu.html"
        ) 

    async def zhueevent(self,server: str,limit: str) -> Dict[str, Any]:
        """诛恶事件"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            for item in data:
                item["time"] = format_time(item["time"])

            return_data["data"] = {
                "items": data,
                "update_time": ""
            }
            
        return await self._request_api(
            path="/wicked/records",
            params={"token": self.token, "server": server, "limit": limit},
            processor=processor,
            template="zhueevent.html"
        ) 

    async def jueshemingpian(
        self, server: str, name: str, force_refresh: bool = False
    ) -> Dict[str, Any]:
        """查询角色名片。"""
        return await self.card_remote(server, name, force_refresh=force_refresh)

    async def shuijimingpian(self, server:str, force: str, body:str,) -> Dict[str, Any]:
        """随机名片"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            url = data.get("showAvatar")
            if not url:
                return_data["msg"] = "未获取到名片图片"
                return return_data

            server_name = data.get("serverName")
            role_name = data.get("roleName")
            msg = f"{server_name}-{role_name}"

            return_data["data"] = [
                text_part(msg),
                image_part(url),
            ]
            
        return await self._request_api(
            path="/card/random",
            params={"server": server, "body": body, "force":force, "token": self.token},
            processor=processor,
            template=""
        ) 

    async def shuoyoumingpian(self, server: str, name: str) -> Dict[str, Any]:
        """名片历史"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            chain = []
            for m in data:
                status = "当前展示" if m.get("showActive") else "未展示"
                msg = f"第{m.get('showIndex')}张 {status}"
                url = m.get("showAvatar")

                if not url:
                    logger.warning(f"第{m.get('showIndex')}张名片缺少图片URL，已跳过")
                    continue

                chain.extend([
                    text_part(msg),
                    image_part(url),
                ])

            if not chain:
                return_data["msg"] = "未获取到有效的名片数据"
                return return_data

            return_data["data"] = chain

        return await self._request_api(
            path="/card/records",
            params={"server": server, "name": name, "token": self.token},
            processor=processor,
            template=""
        ) 

    async def qiyuhuizong(self, server: str, num: int) -> Dict[str, Any]:
        """奇遇汇总"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            for item in data:
                latest = item.get("last") or {}
                item["latest_name"] = latest.get("name") or "—"
                item["latest_time"] = format_time(latest.get("time")) if latest.get("time") else ""

            return_data["data"] = {
                "items": data,
                "server": server,
                "num": num,
                "update_time": ""
            }
            
        return await self._request_api(
            path="/event/collect",
            params={"server": server, "num": num, "token": self.token},
            processor=processor,
            template="qiyuhuizong.html"
        ) 

    async def weizuoqiyu(self, server: str, name: str, ) -> Dict[str, Any]:
        """未出奇遇"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            return_data["data"]["ptqy"] = []
            return_data["data"]["jsqy"] = []
            return_data["data"]["name"] = name
            return_data["data"]["server"] = server

            for item in data:
                try:
                    level = int(item.get("level", 0))
                except (TypeError, ValueError):
                    continue

                event_item = {
                    "event": item.get("name"),
                    "time": "未触发"
                }

                if level == 1:
                    return_data["data"]["ptqy"].append(event_item)
                elif level == 2:
                    return_data["data"]["jsqy"].append(event_item)

            if not return_data["data"]["ptqy"] and not return_data["data"]["jsqy"]:
                return_data["msg"] = "未查询到未做普通或绝世奇遇"
                return return_data
            
        return await self._request_api(
            path="/event/missing",
            params={"server": server, "name": name, "token": self.token},
            processor=processor,
            template="weizuoqiyu.html"
        ) 

    async def jinqiqiyu(self, server: str, limit: int) -> Dict[str, Any]:
        """近期奇遇"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            for item in data:
                item["time"] = format_time(item.get("time"))

            return_data["data"] = {
                "items": data,
                "server": server,
                "update_time": ""
            }

        return await self._request_api(
            path="/event/recent",
            params={"server": server, "limit": limit, "token": self.token},
            processor=processor,
            template="jinqiqiyu.html"
        ) 

    async def qiyutongji(self, name: str, server: str, limit: int) -> Dict[str, Any]:
        """奇遇统计"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            for item in data:
                item["time"] = format_time(item.get("time"))

            return_data["data"] = {
                "items": data,
                "server": server,
                "update_time": "",
                "qiyuname": name
            }

        return await self._request_api(
            path="/event/statistics",
            params={"name": name, "server": server, "limit": limit, "token": self.token},
            processor=processor,
            template="qiyuliebiao.html"
        ) 

    async def jingnai(self, name: str, server: str) -> Dict[str, Any]:
        return await self.role_monster(server,name)

    async def baizhan(self) -> Dict[str, Any]:
        """百战首领"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            return_data["data"] = data
            return_data["data"]["start"]  = format_time(data["start"])   
            return_data["data"]["end"]  = format_time(data["end"])   

        return await self._request_api(
            path="/monster/weekly",
            params= { "token": self.token},
            processor=processor,
            template="baizhan.html"
        ) 

    async def chengjiuchaxun(self, server:str, role:str, name:str) -> Dict[str, Any]:
        """成就查询"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            return_data["data"] = data

        return await self._request_api(
            path="/role/achievement",
            params= {"server": server, "role": role, "name": name, "token": self.token},
            processor=processor,
            template="chengjiu.html"
        ) 

    async def zhenyan(self, name: str) -> Dict[str, Any]:
        """阵眼"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            items = data.get("data", [])
            if not isinstance(items, list) or not items:
                return_data["msg"] = "未查询到该心法阵眼信息"
                return return_data

            result_msg = f"{data.get('name', name)}-{data.get('skillName', '')}\n"
            for item in items:
                if not isinstance(item, dict):
                    continue
                result_msg += f"{item.get('name', '')}：{item.get('desc', '')}\n"

            return_data["data"] = result_msg.rstrip()

        return await self._request_api(
            path="/school/matrix",
            params= {"name": name, "ticket": self.ticket, "token": self.token},
            processor=processor,
            template=""
        ) 

    async def zilipaixing(self,server: str, school: str) -> Dict[str, Any]:
        """资历排行"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            return_data["data"] = {
                "items": data,
                "school": school,
                "server": server,
                "update_time": ""
            }

        return await self._request_api(
            path="/school/seniority",
            params= {"server": server,"school": school,"ticket": self.ticket,"token": self.token,},
            processor=processor,
            template="zilipaixing.html"
        ) 

    async def jineng(self, name: str,update:int) -> Dict[str, Any]:
        """技能"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            groups = []
            for group in data:
                if not isinstance(group, dict):
                    continue

                skills = group.get("data", [])
                if not isinstance(skills, list) or not skills:
                    continue

                parsed_skills = []
                for skill in skills:
                    if not isinstance(skill, dict):
                        continue

                    parsed_skills.append({
                        "name": skill.get("name", ""),
                        "icon": skill.get("icon", ""),
                        "desc": skill.get("desc", ""),
                        "interval": skill.get("interval", ""),
                        "distance": skill.get("distance", ""),
                        "release_type": skill.get("releaseType", ""),
                        "weapon": skill.get("weapon", ""),
                    })

                if parsed_skills:
                    groups.append({
                        "title": group.get("class", "其他技能"),
                        "skills": parsed_skills,
                    })

            if not groups:
                return_data["msg"] = "未查询到该心法技能信息"
                return return_data

            return_data["data"] = {
                "name": name,
                "groups": groups,
                "update_time": ""
            }

        return await self._request_api(
            path="/school/skills",
            params= {"name": name,"update": update, "ticket": self.ticket, "token": self.token},
            processor=processor,
            template="jineng.html"
        ) 

    async def qixue(self, name: str, update:int) -> Dict[str, Any]:
        """奇穴"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            level_titles = {
                1: "主奇穴",
                2: "第一重",
                3: "第二重",
                4: "第三重",
                5: "第四重",
                6: "第五重",
                7: "第六重",
                8: "混池",
            }

            groups = []
            for group in data:
                if not isinstance(group, dict):
                    continue

                level = group.get("level")
                try:
                    level_key = int(level)
                except (TypeError, ValueError):
                    level_key = 0

                items = group.get("data", [])
                if not isinstance(items, list) or not items:
                    continue

                parsed_items = []
                for item in items:
                    if not isinstance(item, dict):
                        continue

                    class_value = item.get("class")
                    is_active = class_value == 1 or str(class_value) == "1"
                    parsed_items.append({
                        "name": item.get("name", ""),
                        "icon": item.get("icon", ""),
                        "desc": item.get("desc", ""),
                        "class_text": "主动" if is_active else "被动",
                        "interval": item.get("interval", "") if is_active else "",
                    })

                if parsed_items:
                    groups.append({
                        "level": level_key,
                        "title": level_titles.get(level_key, f"第{level_key}组"),
                        "talents": parsed_items,
                    })

            if not groups:
                return_data["msg"] = "未查询到该心法奇穴信息"
                return return_data

            groups.sort(key=lambda item: item["level"])
            return_data["data"] = {
                "name": name,
                "groups": groups,
                "update_time": ""
            }

        return await self._request_api(
            path="/school/talent",
            params= {"name": name,"update": update, "ticket": self.ticket, "token": self.token},
            processor=processor,
            template="qixue.html"
        ) 

    async def juesheliaotian(self, server:str, name: str, limit:int, page:int) -> Dict[str, Any]:
        """角色聊天"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            chat_list = data.get("list", [])

            for item in chat_list:
                item["time"] = format_time(item.get("time", 0))

            return_data["data"] = data

        return await self._request_api(
            path="/chat/records",
            params= {"server": server,"name": name, "limit": limit, "page": page, "token": self.token},
            processor=processor,
            template="juesheliaotian.html"
        ) 

    async def tongzhanyy(self, server: str) -> Dict[str, Any]:
        """统战歪歪"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            lines = ["【统战歪歪】"]
            for group in data:
                group_server = group.get("server", "")
                channels = group.get("data", [])

                if len(lines) > 1:
                    lines.append("")
                lines.append(f"服务器：{group_server}")

                for item in channels:
                    if not isinstance(item, dict):
                        continue

                    short_id = item.get("esid") or item.get("asid", "")
                    lines.extend([
                        f"阵营：{item.get('campName', '')}",
                        f"频道ID：{item.get('sid', '')}",
                        f"短位ID：{short_id}",
                        f"在线人数：{item.get('users', '')}",
                        f"频道名：{item.get('snick', '')}",
                        "",
                    ])

                    return_data["data"] = "\n".join(lines)

        return await self._request_api(
            path="/duowan/statistics",
            params= {"server": server},
            processor=processor,
            template=""
        ) 

    async def xiaoyao(self, name:str) -> Dict[str, Any]:
        """小吃小药"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            result = {}

            for item in data:
                k = item["kungfu"]
                color = item["color"]
                cls = item["class"]
                name = item["name"]

                if k not in result:
                    result[k] = {
                        "kungfu": k,
                        "purple": {},
                        "blue": {}
                    }

                if color == "紫":
                    result[k]["purple"][cls] = name
                else:
                    result[k]["blue"][cls] = name

            return_data["data"]["items"] = list(result.values())

        return await self._request_api(
            path="/food/list",
            params= {"name": name},
            processor=processor,
            template="xiaoyao.html"
        ) 

    async def pianzhi(self, server:str, uid: str) -> Dict[str, Any]:
        """骗子查询"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            records = data["records"]

            if not records:
                result_msg = "未找到该用户行骗记录，很棒！继续保持！"
            else:
                result_msg = ""

                for record in records:
                    result_msg += f"区服：{record['server']}  标签：{record['tieba']}\n\n"

                    for item in record["data"]:
                        result_msg += f"标题：{item['title']}\n"
                        result_msg += f"地址：{item['url']}\n"
                        result_msg += f"ID：{item['tid']}\n"
                        result_msg += f"内容：{item['text']}\n"
                        result_msg += (
                            f"时间：{datetime.fromtimestamp(item['time']).strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                        )

                    result_msg += "\n\n"
            return_data["data"] = result_msg

        return await self._request_api(
            path="/fraud/detail",
            params= {"server": server, "uid": uid, "token": self.token},
            processor=processor,
            template=""
        ) 

    async def huajia(self,server: str, name: str, map: str) -> Dict[str, Any]:
        """家园鲜花"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            return_data["data"]["data"] = data
            return_data["data"]["server"] = server

            rows = data.get("list") if isinstance(data, dict) else data
            return_data["data"]["trend_svg"] = self._trend_svg(
                self._series_from_rows(rows),
                title="鲜花价格走势",
                unit="金",
            )

        return await self._request_api(
            path="/home/flower",
            params= {"server": server, "name": name,  "map": map},
            processor=processor,
            template="huajia.html"
        ) 

    async def zhuangshi(self,name: str) -> Dict[str, Any]:
        """家园装饰"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            return_data["data"]["data"] = data

        return await self._request_api(
            path="/home/furniture",
            params= { "name": name},
            processor=processor,
            template="zhuangshi.html"
        ) 

    async def qiwu(self,name: str) -> Dict[str, Any]:
        """器物图谱"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            return_data["data"]["data"] = data
            return_data["data"]["name"] = name

        return await self._request_api(
            path="/home/travel",
            params= { "name": name},
            processor=processor,
            template="qiwu.html"
        ) 

    async def shitu(self, label: int, server: str, keyword: str, limit:int) -> Dict[str, Any]:
        """师徒招募"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            items = data
            if not items:
                return_data["msg"] = "未查询到师徒招募信息"
                return return_data

            title = "收徒信息" if label == 1 else "拜师信息"
            return_data["data"] = {
                "items": items,
                "server": server,
                "keyword": keyword,
                "type_value": label,
                "title": title,
                "update_time": ""
            }

        return await self._request_api(
            path="/mentor/search",
            params= {"label": label, "server": server, "keyword": keyword, "limit": limit, "token": self.token},
            processor=processor,
            template="shitu.html"
        ) 

    async def tuanduizhaomu(self, server: str, label:int, keyword: str, limit:int) -> Dict[str, Any]:
        """团队招募"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            for item in data:
                item["createTime"] = format_time(item["createTime"])   
                item["maxMemberCount"] = f"{item['currentMemberCount']}/{item['maxMemberCount']}"
                return_data["data"]["list"] = data

        return await self._request_api(
            path="/recruit/search",
            params= {"server": server, "label": label, "keyword": keyword, "limit": limit, "token": self.token},
            processor=processor,
            template="tuanduizhaomu.html"
        ) 

    async def jiemi(self) -> Dict[str, Any]:
        """解密"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            return_data["data"] = "\n".join([
                "解密",
                f"当前时间：{data.get('nowTime', '')}",
                f"当前节点：{data.get('nowNode', '')}",
                f"当前结果：{data.get('nowResult', '')}",
                f"下轮节点：{data.get('nextNode', '')}",
                f"下轮结果：{data.get('nextResult', '')}",
                f"剩余时间：{data.get('intervalTime', '')}",
            ])

        return await self._request_api(
            path="/mech/decrypt",
            params= {"token": self.token},
            processor=processor,
            template=""
        ) 

    async def diaoluo(self, name: str, server: str, limit: int ) -> Dict[str, Any]:
        """物品掉落记录"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            for item in data:
                item["time"] = format_time(item.get("time"))

            return_data["data"] = {
                "items": data,
                "name": name,
                "limit": limit,
                "server": server,
                "update_time": ""
            }

        return await self._request_api(
            path="/reward/statistics",
            params= {"server": server, "name": name, "limit": limit, "token": self.token},
            processor=processor,
            template="diaoluo.html"
        ) 

    async def tiebawujia(self, name: str, server: str, limit: int ) -> Dict[str, Any]:
        """贴吧物价"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            lines = [
                f"贴吧物价：{name}",
                f"服务器：{server}",
                f"记录数：{len(data)}",
                "",
            ]

            for index, item in enumerate(data, start=1):
                if not isinstance(item, dict):
                    continue

                item_time = item.get("time", "")
                if item_time:
                    try:
                        item_time = datetime.fromtimestamp(int(item_time)).strftime("%Y-%m-%d %H:%M:%S")
                    except (TypeError, ValueError, OSError):
                        item_time = str(item_time)

                lines.extend([
                    f"{index}. {item.get('name', '')}",
                    f"区服：{item.get('zone', '')}  服务器：{item.get('server', '')}",
                    f"内容：{item.get('context', '')}",
                    f"回复：{item.get('reply', '')}  楼层：{item.get('floor', '')}",
                    f"时间：{item_time}",
                    f"链接：https://tieba.baidu.com/p/{item.get('url', '')}",
                    "",
                ])

            if len(lines) <= 4:
                return_data["msg"] = "未查询到贴吧物价记录"
                return return_data

            return_data["data"] = "\n".join(lines).rstrip()

        return await self._request_api(
            path="/tieba/item/records",
            params= {"server": server,"name": name,"limit": limit,"token": self.token,},
            processor=processor,
            template=""
        ) 

    async def bagua(self, tags: str, server:str, limit:str ) -> Dict[str, Any]:
        """八卦"""
        async def processor(data: Any, return_data: Dict[str, Any]) -> None:   
            if not data:
                result_msg = f"未找到相关 {tags} 记录。\n"
                result_msg += f"可选范围：818 616 鬼网三 鬼网3 树洞 记录 教程 街拍 故事 避雷 吐槽 提问"
            else:
                result_msg = f"类型：【{tags}】\n\n"

                for item in data:
                    result_msg += f"{item['title']}\n"
                    result_msg += f"服务器：{item['server']}\n"
                    result_msg += f"所属吧：{item['name']}\n"
                    result_msg += f"链接：https://tieba.baidu.com/p/{item['url']}\n"
                    result_msg += f"日期：{item['date']}\n\n"
            return_data["data"] = result_msg

        return await self._request_api(
            path="/tieba/random",
            params= {"server": server,"tags": tags,"limit": limit,"token": self.token,},
            processor=processor,
            template=""
        ) 

    async def fubengjilu(self, server:str, name: str ) -> Dict[str, Any]:
        """Resolve the requested role, then read its current CD from Tuilan."""
        result = self._init_return_data()
        ticket = str(self._config.get("jx3api_ticket") or "").strip()
        if not ticket:
            result["msg"] = "副本 CD 需要推栏登录凭据，请管理员配置推栏标识。"
            return result
        if not str(self.token or "").strip():
            result["msg"] = "查询角色需要 JX3API Token，请管理员完成配置。"
            return result

        async def weekly_names():
            # Optional calendar lookup is capped separately; a slow calendar
            # must not hold up the real progress query.
            try:
                data, _ = await asyncio.wait_for(self._cached_request(
                    "/active/calendar", {"server": server}), timeout=2)
                if isinstance(data, dict):
                    weekly = data.get("weekly")
                    if isinstance(weekly, dict) and isinstance(weekly.get("raid"), list):
                        return [s for s in weekly["raid"][:16] if isinstance(s, str)]
            except Exception:
                pass
            return []

        (detail, _), weekly = await asyncio.gather(
            self._cached_request("/role/detail", {
                "server": server, "name": name, "history": 0, "token": self.token}),
            weekly_names(),
        )
        if isinstance(detail, APIErrorResponse) or not isinstance(detail, dict) or not detail.get("globalId"):
            result["msg"] = "未能取得角色标识，请检查服务器和角色名，或稍后重试。"
            return result
        if detail.get("roleName") != name or detail.get("serverName") != server:
            result["msg"] = "角色资料与查询的服务器或名称不一致，请使用角色当前的服务器和名称。"
            return result
        global_id = str(detail["globalId"])
        try:
            if self._cache:
                raids, metadata = await self._cache.request_api(
                    CD_CACHE_ENDPOINT,
                    {"role": global_id, "__credential_scope": hashlib.sha256(ticket.encode()).hexdigest()},
                    lambda: self._tuilan_cd.get(global_id, ticket),
                    lambda value: isinstance(value, list),
                )
            else:
                raids = await self._tuilan_cd.get(global_id, ticket)
                metadata = {"created_at": int(time.time()), "hit": False}
        except TuilanCDError as exc:
            result["msg"] = str(exc)
            return result
        result["data"] = build_cd_page(raids, weekly, self._config.get("dungeon_cd_focus"))
        result["data"].update(name=name, server=server)
        result["_cache"] = metadata
        result["temp"] = await load_template("fubenjilu.html")
        result["code"] = 200
        return result

    @staticmethod
    def _short_number(value: Any) -> str:
        """把大数字格式化成带 万 / 亿 单位的短文本。"""
        if value is None or value == "":
            return "—"
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        if number >= 100000000:
            return f"{number / 100000000:.2f}亿"
        if number >= 10000:
            return f"{number / 10000:.2f}万"
        if number == int(number):
            return f"{int(number)}"
        return f"{number:.2f}"

    def _hint(self, *lines: str) -> Dict[str, Any]:
        """构造一条纯文本用法提示，避免缺参时报“参数错误”。"""
        return_data = self._init_return_data()
        return_data["code"] = 200
        return_data["data"] = "\n".join(lines)
        return return_data

    async def trial_seasons(self) -> Dict[str, Any]:
        """试炼之地赛季列表"""

        async def processor(data: Any, return_data: Dict[str, Any]) -> None:
            lines = []
            for item in data or []:
                if not isinstance(item, dict):
                    continue
                bosses = "、".join(str(boss) for boss in (item.get("bosses") or []))
                lines.append(
                    f"· {item.get('season') or '未知赛季'}"
                    f"（最高 {item.get('maxFloor') or '?'} 层）\n"
                    f"　{bosses or '暂无首领数据'}"
                )
            if lines:
                return_data["data"] = "【试炼之地 · 赛季一览】\n" + "\n".join(lines)
            else:
                return_data["data"] = "暂未获取到赛季数据"

        return await self._request_api(
            path="/trial/seasons",
            params={"token": self.token},
            processor=processor,
        )

    async def trial_bosses(self, season: str = "", floor: int = 1) -> Dict[str, Any]:
        """试炼之地各层首领血量与秒伤"""
        if not str(season or "").strip():
            seasons = await self.trial_seasons()
            return self._hint(
                "用法：试炼秒伤 赛季 层数（层数范围 1-120）",
                "例：试炼秒伤 太极秘录 1",
                "",
                str(seasons.get("data") or "暂未获取到赛季数据"),
            )

        async def processor(data: Any, return_data: Dict[str, Any]) -> None:
            if not isinstance(data, dict):
                return_data["msg"] = "未获取到试炼数据"
                return
            lines = []
            for item in data.get("bosses") or []:
                if not isinstance(item, dict):
                    continue
                line = (
                    f"· {item.get('boss') or '未知首领'}"
                    f"　血量 {self._short_number(item.get('hp'))}"
                    f"　完美 {self._short_number(item.get('perfectDps'))}"
                    f"　通关 {self._short_number(item.get('clearDps'))}"
                )
                if item.get("note"):
                    line += f"\n　备注：{item['note']}"
                lines.append(line)
            head = (
                f"【试炼之地 · {data.get('season') or season}"
                f" 第 {data.get('floor') or floor} 层】\n"
            )
            if lines:
                return_data["data"] = head + "\n".join(lines)
            else:
                return_data["data"] = head + "暂未获取到首领数据"

        return await self._request_api(
            path="/trial/bosses",
            params={"season": season, "floor": floor, "token": self.token},
            processor=processor,
        )

    async def trade_item_search(self, name: str = "") -> Dict[str, Any]:
        """外观搜索"""
        if not str(name or "").strip():
            return self._hint(
                "用法：外观搜索 外观名称",
                "例：外观搜索 幽昙",
            )

        async def processor(data: Any, return_data: Dict[str, Any]) -> None:
            items = [item for item in (data or []) if isinstance(item, dict)]
            lines = []
            for item in items[:10]:
                alias = item.get("alias")
                suffix = f"（{alias}）" if alias else ""
                lines.append(
                    f"· {item.get('name') or '未知'}{suffix}\n"
                    f"　{item.get('category') or '未分类'}"
                    f"｜原价 {item.get('retail') or '?'} 元"
                    f"｜上架 {item.get('date') or '未知'}"
                )
            if lines:
                return_data["data"] = (
                    f"【外观搜索 · {name}】共 {len(items)} 条\n" + "\n".join(lines)
                )
            else:
                return_data["data"] = f"未找到与「{name}」匹配的外观"

        return await self._request_api(
            path="/trade/item/search",
            params={"name": name, "token": self.token},
            processor=processor,
        )

    async def trade_item_records(
        self, name: str = "", server: str = ""
    ) -> Dict[str, Any]:
        """外观历史成交价"""
        if not str(name or "").strip():
            return self._hint(
                "用法：外观价格 外观名称 [服务器]",
                "例：外观价格 幽昙月影·阑珊·豪华 唯我独尊",
            )

        async def processor(data: Any, return_data: Dict[str, Any]) -> None:
            if not isinstance(data, dict) or not data.get("name"):
                return_data["msg"] = "未找到该外观的历史成交记录"
                return
            alias = data.get("alias")
            suffix = f"（{alias}）" if alias else ""
            head = (
                f"【{data.get('name')}{suffix}】\n"
                f"{data.get('category') or '未分类'}"
                f"｜原价 {data.get('retail') or '?'} 元"
                f"｜上架 {data.get('date') or '未知'}\n"
            )
            lines = []
            for group in data.get("list") or []:
                if not isinstance(group, dict):
                    continue
                rows = [
                    row for row in (group.get("list") or []) if isinstance(row, dict)
                ]
                if server:
                    matched = [
                        row
                        for row in rows
                        if str(row.get("server") or "") == str(server)
                    ]
                    if matched:
                        rows = matched
                if not rows:
                    continue
                lines.append(f"· {group.get('name') or '未知区'}")
                for row in rows[:5]:
                    lines.append(
                        f"　{row.get('date') or '?'}　{row.get('server') or '?'}"
                        f"　{self._short_number(row.get('value'))} 元"
                        f"　成交 {row.get('sale') or '?'}"
                    )
            if lines:
                return_data["data"] = head + "\n".join(lines)
            else:
                return_data["data"] = head + "暂无成交记录"

        params: Dict[str, Any] = {"name": name, "token": self.token}
        if str(server or "").strip():
            params["server"] = server

        return await self._request_api(
            path="/trade/item/records",
            params=params,
            processor=processor,
        )

    async def event_strategy(self, name: str = "") -> Dict[str, Any]:
        """奇遇攻略信息"""
        if not str(name or "").strip():
            return self._hint(
                "用法：奇遇攻略 奇遇名称",
                "例：奇遇攻略 塞外宝驹",
            )

        async def processor(data: Any, return_data: Dict[str, Any]) -> None:
            if not isinstance(data, dict) or not data.get("name"):
                return_data["msg"] = "未找到该奇遇"
                return
            box = data.get("box")
            return_data["data"] = (
                f"【{data.get('name')}】\n"
                f"类型：{data.get('type') or '未知'}\n"
                f"等级：{data.get('level') or '?'}\n"
                f"攻略盒子：{box if box else '暂无'}"
            )

        return await self._request_api(
            path="/event/strategy",
            params={"name": name, "token": self.token},
            processor=processor,
        )

    async def skill_calculate(self, cooldown: float = 1.5) -> Dict[str, Any]:
        """急速计算"""

        async def processor(data: Any, return_data: Dict[str, Any]) -> None:
            lines = []
            for row in data or []:
                if not isinstance(row, dict):
                    continue
                try:
                    percent = float(row.get("hastePercent") or 0)
                except (TypeError, ValueError):
                    percent = 0.0
                level = row.get("level")
                lines.append(
                    f"· {row.get('nowFrame') or '?'} 帧"
                    f"　读条 {self._short_number(row.get('duration'))} 秒"
                    f"　急速 {percent:.2f}%"
                    f"　等级需求 {level if level is not None else '?'}"
                )
            head = (
                f"【急速计算 · 技能 CD {self._short_number(cooldown)} 秒】\n"
                f"（帧数相同的档位只保留最低急速）\n"
            )
            if lines:
                return_data["data"] = head + "\n".join(lines)
            else:
                return_data["data"] = head + "暂未获取到急速档位"

        return await self._request_api(
            path="/skill/calculate",
            params={"cooldown": cooldown, "token": self.token},
            processor=processor,
        )

    async def school_search(
        self, kungfu: str = "", mode: str = ""
    ) -> Dict[str, Any]:
        """推栏推荐配装"""
        if not str(kungfu or "").strip():
            return self._hint(
                "用法：推栏配装 心法 [模式]",
                "例：推栏配装 太虚剑意　推栏配装 剑纯",
            )

        async def processor(data: Any, return_data: Dict[str, Any]) -> None:
            rows = [row for row in (data or []) if isinstance(row, dict)]
            lines = []
            for index, row in enumerate(rows[:5], 1):
                tuilan = row.get("tuilanInfo") or {}
                author = tuilan.get("nickname") or "未知"
                tags = "、".join(str(tag) for tag in (row.get("tags") or []))
                line = (
                    f"{index}. {row.get('title') or '无标题'}\n"
                    f"　作者：{author}"
                    f"　装分：{self._short_number(row.get('score'))}"
                )
                if tags:
                    line += f"　标签：{tags}"
                if row.get("content"):
                    line += f"\n　{str(row['content'])[:80]}"
                lines.append(line)
            if lines:
                return_data["data"] = (
                    f"【推栏配装 · {kungfu}】共 {len(rows)} 条\n" + "\n".join(lines)
                )
            else:
                return_data["data"] = f"未找到「{kungfu}」的推荐配装"

        params: Dict[str, Any] = {
            "name": kungfu,
            "ticket": self.ticket,
            "token": self.token,
        }
        if str(mode or "").strip():
            params["mode"] = mode

        return await self._request_api(
            path="/school/search",
            params=params,
            processor=processor,
        )

    async def card_preset(self, server: str, name: str) -> Dict[str, Any]:
        """推栏名片预设图（图片链接为短时效签名，必须绕过缓存）"""

        async def processor(data: Any, return_data: Dict[str, Any]) -> None:
            if not isinstance(data, dict):
                return_data["msg"] = "未获取到名片预设"
                return
            url = data.get("showCardPresetUrl")
            if not url:
                return_data["msg"] = "未获取到名片预设图片"
                return
            return_data["data"] = [
                text_part(f"{server}-{name}　名片预设"),
                image_part(url),
                text_part(f"获赞总数：{data.get('praiseTotalCount') or 0}"),
            ]

        return await self._request_api(
            path="/card/preset",
            params={
                "server": server,
                "name": name,
                "ticket": self.ticket,
                "token": self.token,
            },
            processor=processor,
            force_refresh=True,
        )

    async def card_remote(
        self, server: str, name: str, force_refresh: bool = False
    ) -> Dict[str, Any]:
        """请求上游刷新名片；更新失败时明确报错。"""
        result = self._init_return_data()
        data, metadata = await self._cached_request(
            "/card/record",
            {"server": server, "name": name, "token": self.token},
            force_refresh=force_refresh,
        )
        result["_cache"] = metadata
        if isinstance(data, APIErrorResponse):
            result["msg"] = data.message or "名片更新失败，请稍后重试"
            return result
        if not isinstance(data, dict):
            result["msg"] = "未获取到名片，请稍后重试"
            return result
        if data.get("roleName") and str(data["roleName"]) != name:
            result["msg"] = "返回的名片与查询角色不符，请稍后重试"
            return result
        url = str(data.get("showAvatar") or "").strip()
        try:
            parsed = urlsplit(url)
            valid_url = parsed.scheme in {"https", "http"} and bool(parsed.hostname)
        except ValueError:
            valid_url = False
        if not valid_url:
            result["msg"] = "未获取到名片图片，请稍后重试"
            return result

        # 该图片服务会覆盖同一路径，用快照版本避免聊天端复用旧图。
        # 带签名参数的 URL 保持原样，以免签名失效。
        version = data.get("cacheTime") or metadata.get("created_at")
        if parsed.hostname == "static.nicemoe.cn" and not parsed.query and version:
            revision = hashlib.sha256(str(version).encode()).hexdigest()[:12]
            url = urlunsplit(parsed._replace(query=urlencode({"v": revision})))
        raw_likes = data.get("showLike")
        likes = str(raw_likes) if type(raw_likes) in (int, str) else ""
        likes = str(int(likes)) if re.fullmatch(r"[0-9]+", likes) else "暂未获取"
        result["data"] = [
            text_part(f"{data.get('serverName') or server}-{data.get('roleName') or name}"),
            image_part(url),
            text_part(f"点赞：{likes}"),
        ]
        result["code"] = 200
        return result

    @staticmethod
    def _parse_gold_amount(value: Any) -> Optional[float]:
        """把「4万6000金」「700万1200金」这类文本解析成数字。"""
        if value is None or value == "":
            return None
        if isinstance(value, (int, float)):
            return float(value) if value > 0 else None
        text = str(value)
        total = 0.0
        matched = False
        for match in re.finditer(r"([0-9]+(?:\.[0-9]+)?)\s*万", text):
            total += float(match.group(1)) * 10000
            matched = True
        rest = re.sub(r"[0-9]+(?:\.[0-9]+)?\s*万", "", text)
        for match in re.finditer(r"([0-9]+(?:\.[0-9]+)?)", rest):
            total += float(match.group(1))
            matched = True
        return total if matched and total > 0 else None

    @classmethod
    def _series_from_rows(cls, rows: Any) -> List[tuple]:
        """从结构未知的记录列表里尽力抽出 (日期, 数值)。"""
        if not isinstance(rows, list):
            return []
        date_keys = (
            "date", "time", "day", "datetime",
            "refreshTime", "auctionTime", "createTime",
        )
        value_keys = (
            "value", "price", "money", "amount",
            "wanbaolou", "auctionAmount", "jin",
        )
        series = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            day = ""
            for key in date_keys:
                if row.get(key):
                    day = str(row[key])[:10].replace("/", "-")
                    break
            if not day:
                continue
            value = None
            for key in value_keys:
                if row.get(key) not in (None, ""):
                    value = cls._parse_gold_amount(row[key])
                    if value:
                        break
            if value:
                series.append((day, value))
        return series

    @staticmethod
    def _nice_step(span: float, target: int = 4) -> float:
        """取一个"好看"的刻度步长（1/2/2.5/5/10 档）。"""
        if span <= 0:
            return 1.0
        raw = span / max(target, 1)
        magnitude = 10 ** int(math.floor(math.log10(raw))) if raw > 0 else 1
        for mult in (1, 2, 2.5, 5, 10):
            step = magnitude * mult
            if step >= raw:
                return float(step)
        return float(magnitude * 10)

    @staticmethod
    def _build_trend(series: List[tuple], limit: int = 12, fmt=None) -> Dict[str, Any]:
        """把 (日期, 价格) 序列换算成 SVG 坐标；同一天多条取均值。"""
        grouped: Dict[str, List[float]] = {}
        for day, value in series or []:
            if not day or value in (None, ""):
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if number <= 0:
                continue
            grouped.setdefault(str(day)[:10], []).append(number)

        merged = sorted(
            (day, sum(values) / len(values)) for day, values in grouped.items()
        )[-limit:]
        if len(merged) < 2:
            return {}

        formatter = fmt or (lambda value: f"{value:,.0f}")
        values = [value for _, value in merged]
        low, high = min(values), max(values)
        if high <= low:
            high = low + max(low * 0.05, 1.0)

        step = GameData._nice_step(high - low)
        axis_low = math.floor(low / step) * step
        while axis_low + step * 4 < high:
            axis_low += step
        axis_high = axis_low + step * 4
        span = axis_high - axis_low or 1

        left, right, top, bottom = 104.0, 936.0, 32.0, 262.0
        x_step = (right - left) / (len(merged) - 1)

        coords = []
        for index, (day, value) in enumerate(merged):
            x = left + x_step * index
            y = bottom - (value - axis_low) / span * (bottom - top)
            coords.append((round(x, 1), round(y, 1), day, value))

        peak, lowest = max(values), min(values)
        if len(merged) <= 8:
            candidates = list(range(len(merged)))
        else:
            candidates = list(range(0, len(merged), 2)) + [
                values.index(peak),
                values.index(lowest),
            ]

        # 按横坐标排序后做避让，相邻标签太近就丢掉后一个
        keep, last_x = [], None
        for index in sorted(set(candidates)):
            x = coords[index][0]
            if last_x is not None and x - last_x < 62:
                continue
            keep.append(index)
            last_x = x
        for index in (values.index(peak), values.index(lowest)):
            if index not in keep:
                keep.append(index)
        keep = set(keep)

        trend_points = []
        for index, (x, y, day, value) in enumerate(coords):
            if index == 0:
                anchor = "start"
            elif index == len(coords) - 1:
                anchor = "end"
            else:
                anchor = "middle"
            trend_points.append(
                {
                    "x": x,
                    "y": y,
                    "anchor": anchor,
                    "peak": value == peak,
                    "label": formatter(value) if index in keep else "",
                }
            )

        area = (
            f"M {coords[0][0]},{bottom} "
            + " ".join(f"L {x},{y}" for x, y, _, _ in coords)
            + f" L {coords[-1][0]},{bottom} Z"
        )

        y_ticks = [
            {
                "y": round(top + (bottom - top) * i / 4, 1),
                "label": formatter(axis_high - (axis_high - axis_low) * i / 4),
            }
            for i in range(5)
        ]

        xtick_indexes = (0, len(coords) // 2, len(coords) - 1)
        anchors = ("start", "middle", "end")
        x_ticks = [
            {
                "x": coords[index][0],
                "label": coords[index][2],
                "anchor": anchors[position],
            }
            for position, index in enumerate(xtick_indexes)
        ]

        return {
            "trend_polyline": " ".join(f"{x},{y}" for x, y, _, _ in coords),
            "trend_area": area,
            "trend_points": trend_points,
            "y_ticks": y_ticks,
            "x_ticks": x_ticks,
            "trend_count": len(coords),
        }

    @classmethod
    def _trend_svg(
        cls,
        series: Any,
        title: str = "历史价格走势",
        unit: str = "",
        limit: int = 12,
        fmt=None,
        foot: str = "数据来自 JX3API / 万宝楼 / 百度贴吧，仅供参考",
    ) -> str:
        """生成自包含的 SVG 走势图（内联样式，任何模板塞进去就能用）。"""
        geometry = cls._build_trend(series, limit=limit, fmt=fmt)
        if not geometry:
            days = sorted(
                {
                    str(day)[:10]
                    for day, value in (series or [])
                    if day and value not in (None, "")
                }
            )
            if not days:
                return ""
            if len(days) == 1:
                reason = f"成交记录都集中在 {days[0]} 一天，构不成走势"
            else:
                reason = "成交记录不足 2 天，暂不绘制走势"
            return (
                '<div class="jx3-trend">'
                + cls._TREND_STYLE
                + '<div class="jx3-trend__head">'
                + f'<span class="jx3-trend__title">{html.escape(title)}</span>'
                + '<span class="jx3-trend__hint">数据不足</span>'
                + "</div>"
                + f'<div class="jx3-trend__empty">{html.escape(reason)}</div>'
                + f'<div class="jx3-trend__foot">{html.escape(foot)}</div>'
                + "</div>"
            )

        parts = [
            '<div class="jx3-trend">',
            cls._TREND_STYLE,
            '<div class="jx3-trend__head">',
            f'<span class="jx3-trend__title">{html.escape(title)}</span>',
        ]
        if unit:
            parts.append(
                f'<span class="jx3-trend__unit">单位：{html.escape(unit)}</span>'
            )
        parts.append(
            f'<span class="jx3-trend__hint">共 {geometry["trend_count"]} 个数据点</span>'
        )
        parts.append("</div>")

        parts.append(
            '<svg viewBox="0 0 1000 320" width="100%" role="img">'
            "<defs>"
            '<linearGradient id="jx3TrendFill" x1="0" y1="0" x2="0" y2="1">'
            '<stop offset="0%" stop-color="#d97757" stop-opacity="0.20"></stop>'
            '<stop offset="100%" stop-color="#d97757" stop-opacity="0"></stop>'
            "</linearGradient>"
            "</defs>"
        )
        parts.append(f'<path class="trend-area" d="{geometry["trend_area"]}"></path>')

        for tick in geometry["y_ticks"]:
            parts.append(
                f'<line class="grid-line" x1="104" y1="{tick["y"]}" '
                f'x2="936" y2="{tick["y"]}"></line>'
            )
            parts.append(
                f'<text class="axis-text" x="94" y="{tick["y"] + 5}" '
                f'text-anchor="end">{html.escape(tick["label"])}</text>'
            )

        parts.append(
            f'<polyline class="trend-line" points="{geometry["trend_polyline"]}">'
            "</polyline>"
        )

        for point in geometry["trend_points"]:
            css = "peak-dot" if point["peak"] else "trend-dot"
            parts.append(
                f'<circle class="{css}" cx="{point["x"]}" cy="{point["y"]}" r="3.6">'
                "</circle>"
            )
        for point in geometry["trend_points"]:
            if point["label"]:
                parts.append(
                    f'<text class="trend-label" x="{point["x"]}" '
                    f'y="{point["y"] - 12}" text-anchor="{point["anchor"]}">'
                    f'{html.escape(point["label"])}</text>'
                )

        for tick in geometry["x_ticks"]:
            parts.append(
                f'<text class="axis-text" x="{tick["x"]}" y="304" '
                f'text-anchor="{tick["anchor"]}">{html.escape(tick["label"])}</text>'
            )

        parts.append("</svg>")
        parts.append(f'<div class="jx3-trend__foot">{html.escape(foot)}</div>')
        parts.append("</div>")
        return "".join(parts)

    @staticmethod
    def _parse_tieba_price(text: str, keyword: str = "") -> Optional[int]:
        """从贴吧正文里抠出价格，优先取紧跟外观名称的 3-6 位数字。"""
        if not text:
            return None
        if keyword:
            match = re.search(
                re.escape(keyword) + r"[^0-9]{0,6}([0-9]{3,6})", text
            )
            if match:
                return int(match.group(1))
        match = re.search(r"([0-9]{3,6})", text)
        return int(match.group(1)) if match else None

    @classmethod
    def _market_render_data(
        cls,
        data: Any,
        tieba_source: Any = None,
        fallback_name: str = "",
        trend_title: str = "历史价格走势",
        trend_unit: str = "元",
    ) -> Dict[str, Any]:
        """把外观价格接口的返回整理成价格页需要的渲染数据。"""
        sale_status = {
            1: "出售", 2: "收购", 3: "想出", 4: "想收",
            5: "成交", 6: "正出", 7: "公示",
        }
        if not isinstance(data, dict):
            data = {}

        name = data.get("name") or fallback_name
        groups = {
            group.get("name"): group
            for group in (data.get("list") or [])
            if isinstance(group, dict)
        }

        notice = [
            item
            for item in ((groups.get("公示期") or {}).get("list") or [])
            if isinstance(item, dict)
        ]
        sale = [
            item
            for item in ((groups.get("在售期") or {}).get("list") or [])
            if isinstance(item, dict)
        ]

        deals = []
        for zone, group in groups.items():
            if zone in {"公示期", "在售期"}:
                continue
            for item in (group.get("list") or []):
                if not isinstance(item, dict):
                    continue
                deals.append(
                    {
                        "date": str(item.get("date") or ""),
                        "server": str(item.get("server") or ""),
                        "value": item.get("value"),
                        "status": sale_status.get(item.get("sale"), "记录"),
                    }
                )
        deals.sort(key=lambda row: row["date"], reverse=True)

        tieba = []
        for item in (tieba_source or []):
            if not isinstance(item, dict):
                continue
            context = str(item.get("context") or "")
            price = cls._parse_tieba_price(context, name)
            if not price:
                continue
            if "出" in context:
                status = "出售"
            elif "收" in context:
                status = "收购"
            else:
                status = "贴吧"
            try:
                day = datetime.fromtimestamp(
                    int(item.get("time") or 0)
                ).strftime("%Y-%m-%d")
            except (TypeError, ValueError, OSError, OverflowError):
                day = ""
            tieba.append(
                {
                    "date": day,
                    "server": str(item.get("server") or ""),
                    "value": price,
                    "status": status,
                }
            )
        tieba.sort(key=lambda row: row["date"], reverse=True)

        return market_page(dict(data, name=name), notice, sale, deals, tieba)

    async def equipment(self, server, name, mode='attribute', kungfu='', kind='秘境挑战'):
        params={'server':server,'name':name}
        if mode != 'records':params['format']='calcd'
        if mode == 'detail':params.update(kungfu=kungfu,type=kind)
        async def portrait():
            try:
                async with asyncio.timeout(1.2):
                    return await self.api.request('/card/cached',{'server':server,'name':name},ttl=300),{}
            except (TimeoutError,JX3APIError,MissingCredential,HttpError):return None,{}
        if mode == 'records':data,_=await self._cached_request('/calcd/'+mode,params);card=None
        else:
            (data,_),(card,_)=await asyncio.gather(self._cached_request('/calcd/'+mode,params),portrait())
        if isinstance(data,APIErrorResponse):return {'code':data.code,'msg':data.message}
        if not data:return {'code':404,'msg':'没有查到这套装备。'}
        subtitle=server+' · '+name
        if mode == 'records':
            rows=[[row['kungfuName'],row['equipType'],format_time(row.get('cacheTime'))] for row in data.get('equipList',[])]
            return {'code':200,'temp':'game_records','data':{'title':'装备记录','subtitle':subtitle,'facts':[],'columns':['心法','用途','更新时间'],'rows':rows}}
        from .equipment import equipment_view
        view=equipment_view(data,server,name)
        if isinstance(card,dict) and card.get('roleName')==view['title'] and card.get('serverName')==view['server'] and card.get('showAvatar'):
            view['portrait']=card['showAvatar'];view['portrait_date']=format_time(card.get('cacheTime'))[:10]
        return {'code':200,'temp':'equipment','data':view}

    async def role_monster(self, server, name, keyword='全部', page=1):
        data,_=await self._cached_request('/monster/records',{'server':server,'name':name})
        if isinstance(data,APIErrorResponse):return {'code':data.code,'msg':data.message}
        if not data:return {'code':404,'msg':'没有查到百战记录。'}
        rows=[row for row in data.get('skillList',[]) if not row.get('bDeprecated')]
        if keyword != '全部':rows=[row for row in rows if keyword in row.get('szSkillName','') or keyword in row.get('szBossName','')]
        if not rows:return {'code':404,'msg':'没有找到这个百战技能。'}
        pages=max(1,math.ceil(len(rows)/24))
        if page>pages:return {'code':400,'msg':f'共 {pages} 页。用法：角色百战 {server} {name} {keyword} 页码'}
        records=[[row.get('szSkillName',''),row.get('szBossName','')] for row in rows[(page-1)*24:page*24]]
        facts=[('精力',data.get('skillEnergy','—')),('耐力',data.get('skillStamina','—')),('页码',f'{page} / {pages}')]
        return {'code':200,'temp':'game_records','data':{'title':'百战技能','subtitle':server+' · '+name,'facts':facts,'columns':['技能','首领'],'rows':records}}

    async def card_cached(self, server, name):
        data,_=await self._cached_request('/card/cached',{'server':server,'name':name})
        if isinstance(data,APIErrorResponse):return {'code':data.code,'msg':data.message}
        if not data or not data.get('showAvatar'):return {'code':404,'msg':'没有查到历史名片。'}
        info=server+' · '+name+'\n点赞 '+str(data.get('showLike',0))
        if data.get('cacheTime'):info+='\n更新于 '+format_time(data['cacheTime'])
        return {'code':200,'data':[text_part(info),image_part(data['showAvatar'])]}

    async def words(self, kind, name=''):
        data,_=await self._cached_request('/saohua/'+kind,{'name':name} if name else {},force_refresh=True)
        if isinstance(data,APIErrorResponse):return {'code':data.code,'msg':data.message}
        if isinstance(data,str):text=data
        elif isinstance(data,list) and all(isinstance(item,str) for item in data):text='\n'.join(data)
        elif isinstance(data,dict):text='\n'.join(str(data[key]) for key in ('answer','hearten','content','text') if isinstance(data.get(key),str))
        else:text=''
        return {'code':200,'data':text} if text else {'code':404,'msg':'暂时没有取到内容。'}

    async def role_history(self, server, name):
        data=await self.api.role_detail(server,name,history=1)
        history=data.get('roleHistory') or {};rows=[]
        for field,label in [('roleNames','角色名'),('TongNames','帮会')]:
            for row in history.get(field,[]):
                rows.append((row.get('time') or 0,[format_time(row.get('time')),label,row.get('server') or server,row.get('name') or '—']))
        rows.sort(key=lambda row:row[0],reverse=True)
        if not rows:return {'code':404,'msg':'没有查到历史记录。'}
        return {'code':200,'temp':'game_records','data':{'title':'角色历史','subtitle':server+' · '+name,'facts':[],'columns':['记录时间','类型','区服','名称'],'rows':[row[1] for row in rows[:30]]}}

    async def activity(self, category, num=0):
        if num:
            data=await self.api.calendar(num,'list');today=data.get('today',{}).get('date','');days=[row for row in data.get('total',[]) if row.get('date','')>=today][:num+1]
        else:days=[await self.api.calendar(0,'day')]
        label={'battle':'战场','war':'大战','lucky':'福缘宠物','orecar':'矿车'}[category];rows=[]
        for row in days:
            value=row.get(category)
            if not value:continue
            rows.append([row.get('date',''),'周'+row.get('week',''), '、'.join(value) if isinstance(value,list) else value])
        if not rows:return {'code':404,'msg':'没有查到'+label+'安排。'}
        return {'code':200,'temp':'game_records','data':{'title':label+'安排','subtitle':'','facts':[],'columns':['日期','星期',label],'rows':rows}}

    async def event_count(self, server, name):
        data=await self.api.event_records(server,name,full=1)
        if not isinstance(data,list) or not data:return {'code':404,'msg':'没有查到奇遇记录。'}
        groups={2:set(),1:set(),3:set()};collected={2:set(),1:set(),3:set()}
        for row in data:
            level=row.get('level');label=row.get('event')
            if level not in groups or not label:continue
            groups[level].add(label)
            if row.get('status')==1:collected[level].add(label)
        rows=[[label,len(collected[level]),len(groups[level]-collected[level])] for level,label in [(2,'绝世'),(1,'普通'),(3,'宠物')]]
        return {'code':200,'temp':'game_records','data':{'title':'奇遇收集','subtitle':server+' · '+name,'facts':[],'columns':['类别','已触发','未触发'],'rows':rows}}
