# 推栏 Ticket 说明

## 它是什么

推栏是剑网3官方 App。登录推栏后，App 会携带一个 `ticket` 作为登录态；JX3API 在部分“推栏数据”接口上要求把这个 `ticket` 一并传过去。

**推栏 Ticket 不是 JX3API Token。** 两者是不同的凭证：

| 凭证 | 作用 | 在哪里配置 |
| --- | --- | --- |
| JX3API Token | JX3API 站点访问令牌，决定 LV.1 / LV.2 权限 | 后台「接口配置 → JX3API Token」 |
| 推栏 Ticket | 推栏 App 登录态，供 JX3API 转发查询推栏数据 | 后台「接口配置 → 推栏 Ticket」 |

只填 Token 时，普通角色 / 金价 / 沙盘等接口可用；名剑、名片预设、门派、资历等接口会返回 403 或“ticket 无效”。

## 哪些接口需要 Ticket

以 `data/endpoints.json` 的 `ticket=true` 为准，当前包括：

| 接口 | 功能 |
| --- | --- |
| `/arena/awesome` | 名剑排行 |
| `/arena/recent` | 名剑战绩 |
| `/arena/schools` | 名剑统计 |
| `/school/matrix` | 阵眼效果 |
| `/school/search` | 配装搜索 |
| `/school/seniority` | 资历榜单 |
| `/school/skills` | 技能信息 |
| `/school/talent` | 奇穴信息 |
| `/card/preset` | 名片预设 |
| `/tuilan/achievement` | 资历分布 |

这些接口同时要求 Token（LV.1 或 LV.2）。后台调试页会显示 `L1`/`L2` 和 `T` 标记。

## 获取方法

1. 手机安装「推栏」App，登录剑网3账号。
2. 用抓包工具（Reqable、Stream、Charles 等）抓取推栏 App 的 HTTPS 请求。需要安装并信任抓包工具的证书。
3. 在已登录请求的 **Cookie 请求头** 或 **URL 查询参数** 中找到 `ticket=...`。
4. 复制 `ticket=` 后面的值；也可以直接复制整段 Cookie 或包含 `ticket=` 的 URL。
5. 粘贴到后台「接口配置 → 推栏 Ticket」，保存后点「检测 Ticket」。

> Ticket 一般较长（几十到几百字符），会过期。重新登录推栏后旧 Ticket 可能立即失效。

## 支持的粘贴格式

`normalize_ticket()`（`jx3portal/tuilan.py`）会自动处理：

| 粘贴内容 | 解析结果 |
| --- | --- |
| `abc123` | `abc123` |
| `ticket=abc123` | `abc123` |
| `ticket=abc123&device=pc` | `abc123` |
| `Cookie: uid=1; ticket=abc123; foo=bar` | `abc123` |
| `https://example.com/path?ticket=abc123&x=1` | `abc123` |
| 带 `%xx` 转义的 ticket | **保持原值，不做 URL 解码** |

JX3API 需要的是推栏客户端发出的原始 ticket 值；插件不再对 `%2B`、`%2F` 等做解码，避免把有效 Ticket 改坏。直接粘贴 Cookie / 请求里的原值即可，不要额外加引号。

## 检测方式

后台「检测 Ticket」和聊天指令 `推栏 检测` 都会调用 `JX3APIClient.probe_ticket()`：

1. 先调用 `/trade/demon?limit=1`（LV.1，仅 Token），确认 Token 有效；
2. 再调用 `/school/matrix?name=万花`（LV.1 + ticket），确认推栏 Ticket 有效。

两步都通过才会显示“Token 与推栏 Ticket 均有效”。这样不会把 Token 失效误报成 Ticket 失效。

聊天指令：

```text
推栏            # 查看是否配置、上次检测结果
推栏 检测       # 实际调用接口验证
推栏 帮助       # 查看抓包教程
```

## 过期与常见错误

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| HTTP 403 / `ticket expired` | Ticket 过期或被推栏注销 | 重新抓包，更新 Ticket |
| HTTP 403 / `level too low` | JX3API Token 等级不足 | 升级 Token 等级 |
| HTTP 401 | Token 无效 / 未填 | 检查 Token，点「测试 Token」 |
| 提示“该功能需要推栏 Ticket” | 本地未配置 Ticket | 后台填写并保存 |
| 检测通过但某接口仍失败 | 该接口还需要更高 Token 等级 | 查看接口的 `L2` 标记 |

## 安全建议

- Ticket 等同于推栏登录态，泄露后他人可以读取你的推栏数据。不要发到群里、日志或截图里。
- 后台只显示 `****abcd` 掩码；导出配置也不会包含 Ticket。
- 插件日志只记录接口路径，不记录查询串，因此不会把 Ticket 写进日志。
- 如果怀疑泄露：在推栏 App 退出登录 / 重新登录，使旧 Ticket 失效，然后更新后台配置。
- 不要把 AstrBot WebUI 直接暴露在公网；后台权限完全依赖 AstrBot 登录态。

## 为什么插件不直接请求推栏

推栏没有公开 API，私有接口的签名、设备信息、加密方式会变化。JX3API 已经维护了这层适配，插件只负责保存 Ticket 并在需要时传给 JX3API。这样推栏改版时通常只需更新 JX3API，不需要改插件。

## 相关文件

- `jx3portal/tuilan.py`：归一化、掩码、检测、教程文本
- `jx3portal/jx3api.py`：`request(..., auth="both")` 自动注入 Token + Ticket
- `jx3portal/commands.py`：`_cmd_ticket`
- `data/endpoints.json`：每个接口的 `ticket` 标记
