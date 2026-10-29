# 后台管理说明

## 入口

AstrBot WebUI → **插件** → **剑网3百宝箱** → **可视化视图**。

页面文件位于 `views/dashboard/`，由 AstrBot 以受限 iframe 加载，并通过 `window.AstrBotPluginView` bridge 调用 `main.py` 注册的后台路由。

- 需要 AstrBot 4.10+。
- 不要直接双击 `index.html`：它依赖 bridge 注入，脱离 AstrBot 会提示“没有检测到插件桥接”。
- 旧版 AstrBot 仍可通过插件配置页（`_conf_schema.json`）填写 Token / Ticket，但无法使用图形后台。

## 页面

| 页面 | 内容 |
| --- | --- |
| 概览 | 请求数 / 成功率 / 缓存命中率 / 运行时长、四项连接检测、JX3API 令牌状态卡片（手动 / 60 秒自动刷新）、最近 8 条活动、快速开始 |
| 接口配置 | Token、推栏 Ticket、JX3API 参数、默认区服、JX3BOX 固定地址、角色在线、豆包生图、日志条数 |
| 指令管理 | 27 个指令的启用开关、冷却、所有人 / 管理员权限、付费标记 |
| 区服别名 | 正式区服 / 别名映射、默认区服、恢复默认 |
| 事件推送 | 通道开关、WebSocket 地址、令牌、39 个事件（中文名 / 对应接口 / 类型）、目标会话、会话订阅状态（逐事件开关）、连接状态、重连 |
| 付费授权 | 付费模式、群聊白名单、到期时间、续期 / 停用 / 删除、激活码生成与复制 |
| 缓存与日志 | 缓存分区统计与清理、请求日志级别 / 关键词筛选、清空 |
| 接口调试 | 83 个 JX3API 接口的搜索、参数表单、鉴权方式、在线发送、JSON 查看 / 复制 |
| 系统信息 | 版本 / Python / AstrBot / 数据目录 / 统计 / 导出脱敏配置 |

保存配置、保存指令、清空缓存、清空日志、重置统计都有确认或结果提示。

## 后台路由

所有路由都带插件名前缀：

```text
/api/v1/plugins/extensions/astrbot_plugin_jx3_portal/<route>
```

视图里通过 bridge 调用时**不要**带插件名前缀：

```js
await bridge.apiGet("bootstrap");
await bridge.apiPost("settings/save", { jx3api: { token: "..." } });
```

| 路由 | 方法 | 说明 |
| --- | --- | --- |
| `bootstrap` | GET | 首屏数据：配置（掩码）、指令、统计、日志、Ticket 状态 |
| `settings/save` | POST | 保存配置 |
| `settings/secret/clear` | POST | 清除 Token / Ticket |
| `test` | POST | 连接测试，`target` = `connect` / `token` / `ticket` / `jx3box` / `doubao` / `online` / `events` / `all` |
| `token/stats` | POST | JX3API Token 等级 / 用量，`force` 可跳过 60 秒缓存 |
| `commands/save` | POST | 保存指令开关 / 冷却 / 权限；`reset: true` 恢复默认 |
| `cache/stats` | GET | 缓存统计 |
| `cache/clear` | POST | `scope` = `all` / `jx3api` / `jx3box` |
| `logs` | GET | `limit` / `level` / `q` 查询日志 |
| `logs/clear` | POST | 清空日志 |
| `endpoints` | GET | JX3API 接口目录，`q` 搜索 |
| `servers` | GET | 区服列表，`force=1` 强制刷新 |
| `debug/request` | POST | 调用任意 JX3API 路径 |
| `system` | GET | 运行环境与路径 |
| `stats/reset` | POST | 重置计数与运行时长 |
| `export` | GET | 导出脱敏配置（无 Token / Ticket） |
| `render/templates` | GET | 图片模板 / 素材清单 |
| `render/preview` | POST | 按页面 + JSON 数据预览图片 |
| `aliases/summary` | GET | 区服别名表 |
| `aliases/save` | POST | 保存区服别名（`rows`） |
| `aliases/reset` | POST | 恢复内置别名表 |
| `events/summary` | GET | 事件状态、事件目录、当前事件配置、会话订阅状态 |
| `events/session/save` | POST | 保存指定会话的事件开关（`session_id` + `actions`） |
| `events/reload` | POST | 重新连接事件通道 |
| `paid/summary` | GET | 付费模式、群白名单、激活码、统计 |
| `paid/groups/save` | POST | 新增 / 更新群授权；`extend_days` 续期 |
| `paid/groups/delete` | POST | 删除群授权 |
| `paid/codes/generate` | POST | 批量生成激活码（`days` / `count` / `note`） |
| `paid/codes/delete` | POST | 删除激活码 |
| `doubao/test` | POST | 检查豆包 Key / 模型列表 |
| `online/test` | POST | 用 `server` / `name` 测试第三方在线查询 |

## 配置写入

配置保存在 AstrBot 的插件配置中（`config.json`），后台和插件配置页共用同一组扁平键：

```text
jx3api_base_url, jx3api_token, jx3api_ticket,
jx3api_timeout, jx3api_retries, jx3api_cache_ttl,
default_server,
jx3box_timeout, jx3box_cache_ttl, jx3box_client,
jx3box_global_level,
online_api_url, online_api_token,
event_push_enabled, event_push_wss_url, event_push_token,
event_push_actions, event_push_sessions,
paid_enabled,
doubao_api_key, doubao_base_url, doubao_model,
doubao_size, doubao_watermark, doubao_timeout,
admin_log_limit
```

JX3BOX 的 CMS / NODE / 交易行地址固定在代码中，不再是配置项。

校验规则：

| 键 | 范围 / 规则 |
| --- | --- |
| `jx3api_base_url` | `http://` / `https://`，无 query / fragment |
| `jx3api_timeout` | 3 ~ 180 秒 |
| `jx3api_retries` | 0 ~ 5 |
| `jx3api_cache_ttl` | 0 ~ 86400 秒 |
| `jx3box_timeout` | 3 ~ 180 秒 |
| `jx3box_cache_ttl` | 0 ~ 86400 秒 |
| `jx3box_global_level` | 1 ~ 999 |
| `jx3box_client` | `std` / `origin` |
| `online_api_url` | 空，或域名 / `http(s)` 完整地址 |
| `event_push_wss_url` | `ws://` / `wss://`，空时回落默认值 |
| `event_push_actions` | 必须是 `EVENT_NAMES` 中的编号 |
| `event_push_sessions` | 会话 ID 字符串列表，最多 200 项 |
| `doubao_base_url` | `http(s)` 完整地址 |
| `doubao_size` | `1024x1024` / `2K` 等 |
| `doubao_timeout` | 10 ~ 300 秒 |
| `admin_log_limit` | 50 ~ 1000 |

密钥规则：

- 保存时传空字符串 = 不修改；
- 传 `****abcd` = 视为掩码，不修改；
- 只有「清除」按钮会真正清空；
- 返回给前端的 `settings` 只有 `token_masked` / `token_configured` / `token_length`。

## 区服别名

- 数据保存在插件数据目录的 `server_aliases.json`；首次运行从 `data/server_aliases.json` 种子复制。
- `aliases/save` 的 `rows` 为 `[{"server": "梦江南", "aliases": ["双梦", "电五"]}]`。
- 别名不能和正式区服重名，也不能被两个区服共用。
- 指令解析、默认区服、`开服` 过滤都会走别名映射。

## 指令配置

指令开关不放在 AstrBot 配置里，而是保存在插件数据目录的 `commands.json`：

```json
{
  "disabled": ["news"],
  "cooldowns": { "role": 9 },
  "permissions": { "doctor": "admin" }
}
```

- `disabled`：关闭的指令 key；
- `cooldowns`：覆盖默认冷却，0 ~ 3600 秒；
- `permissions`：`all` 或 `admin`，覆盖 `CommandSpec.admin_only`。

`commands/save` 会校验 key 必须在 `COMMAND_MAP` 中，防止写入未知指令。保存后会清空内存里的冷却计时。

付费指令由 `CommandSpec.paid` 标记，不能通过后台单独改成免费；要整体开放，请关闭「付费查询闸门」。

## 事件推送

- `event_push_enabled`：总开关；关闭时 `EventPushService` 不连接。
- `event_push_wss_url`：WebSocket 地址，默认 `wss://socket.nicemoe.cn`。
- `event_push_token`：为空时用 `jx3api_token`；非空则覆盖。
- `event_push_actions`：全局事件选择；后台勾选后保存。
- `event_push_sessions`：目标会话列表；群成员可用「事件推送 开启」自助加入。
- 保存 `event_push_enabled` / URL / 令牌后，后台会自动重连；也可以点「重连」。

## 付费授权

数据保存在插件数据目录：

- `paid_state.json`：白名单与激活码一起提交，保存失败不生效。
- 旧的 `paid_groups.json` / `activation_codes.json` 仅用于首次兼容读取，保留原文件。

后台只能通过 `/paid/*` 路由修改，避免把授权数据写进 AstrBot 配置。到期判断在读取时完成，不会因为长时间不访问而误判有效。

## 豆包 / 在线

- 豆包 Key 只显示掩码；`doubao/test` 调 `/models` 做低成本探活，404 时提示用一次生图验证。
- 在线查询令牌与 JX3API Token 独立；`online/test` 需要区服和角色名，会实际走一遍 JX3API 角色详情 + 第三方在线接口。

## 缓存

| 命名空间 | 内容 | 默认 TTL |
| --- | --- | --- |
| `jx3api` | JX3API 响应 | `jx3api_cache_ttl`（60 秒） |
| `jx3box:builds` | 配装 | `jx3box_cache_ttl`（300 秒） |
| `jx3box:macro` | 宏帖 | 同上 |
| `jx3box:items` | 全量物品库 | 86400 秒 |
| `jx3box:auction` | 交易行 | 60 秒 |

- 进程内 LRU + TTL，最多 800 条；过期和超限会淘汰。
- 缓存 key 包含凭证指纹，换 Token / Ticket 不会读到旧凭证的数据。
- 「清理缓存」会同时释放 JX3BOX 的物品库内存索引。
- 清空缓存不会影响指令配置。

## 接口调试

`debug/request` 请求体：

```json
{
  "path": "/arena/schools",
  "auth": "auto",
  "params": { "mode": "33" }
}
```

`auth` 模式：

| 值 | 行为 |
| --- | --- |
| `auto` | 按接口目录的 `level` / `ticket` 自动附加 |
| `none` | 不附加任何凭证 |
| `token` | 强制附加 Token |
| `both` | 强制附加 Token + Ticket |

返回：

```json
{
  "ok": true,
  "path": "/arena/schools",
  "auth": "auto",
  "elapsed_ms": 120,
  "data": {},
  "preview": "{ ... }"
}
```

失败时返回 `ok: false`、`message`，HTTP 错误还会带 `upstream` 原始响应。调试调用不写缓存，但会写请求日志。

## 安全

- 后台路由依赖 AstrBot WebUI 的登录态，没有独立密码；不要把面板暴露到公网。
- 前端永远拿不到 Token / Ticket 明文。
- 请求日志只记录接口路径，不记录查询串；`http.py` 不会把 URL query 写进日志。
- 导出配置只包含掩码和指令配置。
- 推栏 Ticket 等同登录态，泄露后请在推栏重新登录。

## 常见问题

**后台一直转圈 / 加载失败**  
- 确认从插件卡片进入，而不是直接打开文件；
- 检查 AstrBot 控制台是否有 `register_web_api` 相关警告；
- 旧版 AstrBot 不支持可视化视图时，会降级到插件配置页。

**保存配置提示“AstrBot 配置保存失败”**  
- 检查 AstrBot `config.json` 是否只读、磁盘是否已满；
- 查看控制台日志中的 `SettingsError`。

**修改 Token 后仍显示旧数据**  
- 保存配置会自动清空 JX3API 缓存；
- 如仍有旧数据，点「清理缓存 → 全部清理」。

**指令开关保存后没生效**  
- 保存成功会清空冷却计时；
- 确认没有在插件配置页覆盖同名配置（指令开关只存在 `commands.json`）。

**调试页调用 403**  
- 该接口可能需要更高等级 Token 或推栏 Ticket；
- 切换到 `auth: both` 再试，并检查后台的 Ticket 检测结果。

