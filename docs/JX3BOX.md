# JX3BOX（魔盒）接口说明

插件通过 JX3BOX 网站自身使用的公开读接口获取配装、宏和交易行数据。这些接口**不需要 API Key**，但属于网站内部接口，没有稳定性承诺；如果某天 404 或字段变化，需要按本文调整 `jx3portal/jx3box.py`。

## 服务地址（固定在代码中）

| 服务 | 地址 | 用途 |
| --- | --- | --- |
| CMS | `https://cms.jx3box.com` | 配装、宏、物品库 |
| NODE | `https://node.jx3box.com` | 预留；当前命令未使用 |
| 交易行 | `https://next2.jx3box.com` | 交易行成交价 |

地址写在 `jx3portal/jx3box.py` / `settings.py` 常量里，后台不提供输入框；测试时可通过 `JX3BOXClient(..., base_urls={...})` 注入 mock 地址。

所有请求由 `jx3portal/http.py` 发出，带 `Accept: application/json` 和插件 UA，默认超时 25 秒、失败重试 1 次。响应超过 8 MB 会被截断并报错。

## 响应外壳

CMS 接口通常返回：

```json
{
  "code": 0,
  "msg": "Success",
  "data": {}
}
```

`code == 0` 表示成功，客户端取出 `data`。部分接口（交易行 POST）直接返回数组。NestJS 风格错误可能是：

```json
{ "statusCode": 400, "error": "Bad Request", "message": "Invalid request query input" }
```

`JX3BOXClient` 会把 `statusCode >= 400` 转成 `JX3BOXError`。

## 1. 配装列表

```http
GET https://cms.jx3box.com/api/cms/app/pz
```

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `mount` | 是 | 心法 pzid，例如花间游 `10021` |
| `per` | — | 每页数量，插件取 1~20，默认 6 |
| `page` | — | 页码，固定 1 |
| `client` | — | `std` 正式服 / `origin` 缘起服 |
| `global_level` | — | 装等筛选，后台可配，默认 130 |
| `tags` | — | 玩法标签，例如 `PvE`、`PvP`；为空时不传 |
| `star` | — | 固定 `1` |

示例：

```bash
curl "https://cms.jx3box.com/api/cms/app/pz?per=2&page=1&client=std&global_level=130&mount=10021&star=1"
```

响应中的 `data`：

```json
{
  "total": 28,
  "per": 2,
  "pages": 14,
  "page": 1,
  "list": [
    {
      "id": 1765187,
      "mount": 10021,
      "title": "小cw花间",
      "tags": ["PvE"],
      "global_level": 130,
      "zlp": "暗影千机",
      "updated_at": "2026-09-26T11:52:18.000Z",
      "pz_author_info": { "display_name": "原始奶妈爱好者" }
    }
  ]
}
```

插件归一化为：

```json
{
  "id": 1765187,
  "title": "小cw花间",
  "author": "原始奶妈爱好者",
  "tags": ["PvE"],
  "level": 130,
  "season": "暗影千机",
  "updated": "2026-09-26T11:52:18.000Z",
  "url": "https://www.jx3box.com/pz/1765187"
}
```

`mount` 来自 `data/kungfu.json` 的 `pzid`，用户输入“花间”“奶花”“万花”等别名会先经 `assets.find_kungfu()` 归一化。

## 2. 一键宏

```http
GET https://cms.jx3box.com/api/cms/posts?subtype=花间游
```

- `subtype` 是心法全名（`花间游`、`云裳心经`……），不是别名。
- 返回 `data.list`，插件筛出 `post_type == "macro"` 且 `post_meta.data` 非空的帖子。
- 每个宏字段：

| 字段 | 说明 |
| --- | --- |
| `name` | 宏名称 |
| `desc` | 使用说明 |
| `macro` | 宏正文（多行 `/cast`） |
| `talent` | 奇穴字符串（不展示） |
| `speed` | 加速要求（不展示） |

插件取最新一篇宏帖，最多展示 3 个宏，并把正文截断到 700 字，避免聊天消息过长。

示例响应（节选）：

```json
{
  "code": 0,
  "data": {
    "list": [
      {
        "ID": 106438,
        "author": "巫山有云不下雨",
        "post_title": "万花输出宏",
        "post_type": "macro",
        "post_meta": {
          "data": [
            {
              "name": "青歌乘墨一键宏",
              "desc": "需要二段加速",
              "macro": "/cast 钟林毓秀\n/cast 兰摧玉折"
            }
          ]
        }
      }
    ]
  }
}
```

宏详情页：`https://www.jx3box.com/macro/{ID}`。

## 3. 物品库

```http
GET https://cms.jx3box.com/api/cms/pvx/item/group?client=std
```

响应 `data` 是分组数组，每组形如：

```json
{
  "id": 1,
  "label": "五行石",
  "items": [
    { "label": "五行石（六级）", "item_id": "5_24428", "icon": "7528" }
  ]
}
```

- `item_id` 形如 `5_24428`，交易行接口需要这个 ID，不是物品名。
- 插件首次查询时拉取全量分组，缓存在 `jx3box:items` 命名空间 24 小时；同时保留一份进程内索引，清理缓存时一起释放。
- 物品搜索排序：完全匹配 > 前缀匹配 > 包含匹配，最多返回 50 条。

## 4. 交易行成交价

```http
POST https://next2.jx3box.com/api/auction/
Content-Type: application/json
```

请求体：

```json
{
  "item_ids": ["5_24428", "5_24429"],
  "server": "梦江南",
  "aggregate_type": "hourly"
}
```

- 插件先用物品库把玩家输入的名字解析成最多 6 个 `item_id`，再请求价格。
- `aggregate_type` 固定 `hourly`。
- 响应通常为数组：

```json
[
  { "item_id": "5_24428", "price": 1200, "sample": 3, "server": "梦江南" }
]
```

| 字段 | 说明 |
| --- | --- |
| `price` | 成交价，单位铜 |
| `sample` | 样本数量 |
| `server` | 区服 |

插件把铜换算成“金 / 银 / 铜”，并按价格升序展示，最多 10 条。交易行缓存 60 秒，命名空间 `jx3box:auction`。

## 缓存与限流

| 命名空间 | 默认 TTL | 内容 |
| --- | --- | --- |
| `jx3box:builds` | `jx3box_cache_ttl`（默认 300 秒） | 配装列表 |
| `jx3box:macro` | 同上 | 宏帖 |
| `jx3box:items` | 86400 秒 | 全量物品库 |
| `jx3box:auction` | 60 秒 | 成交价 |

JX3BOX 是公开网站接口，请勿高频轮询。插件的指令冷却（默认 5~6 秒）和缓存可以覆盖正常群聊场景。

## 已知限制

- 没有官方 API Key / 文档承诺，接口路径和字段可能随网站改版变化。
- 配装结果受 `global_level` 影响；赛季切换后需要在后台调整装等。
- 宏帖可能只有正文没有结构化宏，此时插件会返回“该一键宏没有正文数据”。
- 交易行只查询物品库中已收录的物品；冷门外装可能搜不到。

## 相关文件

- 客户端实现：`jx3portal/jx3box.py`
- 格式化：`jx3portal/format.py` 的 `builds` / `macros` / `auction`
- 指令：`jx3portal/commands.py` 的 `builds` / `macro` / `auction`
- 心法映射：`data/kungfu.json`

## 1.1.2 宏库接口

先请求 `GET https://next2.jx3box.com/api/macro/tops?kungfu=花间游&size=3&client=std`，再用结果的 `pid` 请求 `GET https://cms.jx3box.com/api/cms/post/{pid}`，从 `post_meta.data` 读取宏正文。依据为魔盒当前宏页面加载的官方前端脚本，已实测。旧的 `/api/cms/posts?post_type=macro` 查询返回 HTTP 400。
