# 角色在线查询

JX3API 没有“角色是否在线”接口；名片里的 `showActive` 只表示名片是否在展示，不是游戏在线。插件按参考插件的约定接入第三方在线服务。

## 配置

| 配置键 | 说明 |
| --- | --- |
| `online_api_url` | 第三方服务地址；只填域名会自动拼 `/role_online`，也可以填完整接口地址 |
| `online_api_token` | 第三方服务自己的令牌，**不是 JX3API Token** |

后台「接口配置 → 角色在线」还提供测试区服 / 角色输入框和「测试在线查询」按钮。

## 请求流程

1. 调 JX3API `/role/detail`（需要 JX3API Token）获取：
   - `zoneName` / `serverName`
   - `roleName`
   - `roleId`
   - `globalId`
2. 请求第三方接口：

```http
GET {online_api_url}/role_online
    ?zone=电信区
    &server=梦江南
    &name=张三
    &role_id=123456
    &global_role_id=...
    &token=<online_api_token>
```

如果 `online_api_url` 已经包含路径（例如 `https://example.com/api/role_online`），不会再追加 `/role_online`。

## 响应约定

```json
{
  "code": 0,
  "data": [
    {
      "gameLogin": true
    }
  ]
}
```

`parse_online()` 只接受：

- `code` 为 `0` / `200` / `"0"` / `"200"`；
- `data` 是仅含一个对象的数组；
- `gameLogin` 是 `true/false`、`0/1` 或 `"true"/"false"/"1"/"0"`。

其他情况返回“未取得有效在线状态”，不会猜测在线 / 离线。

## 指令

```text
在线 梦江南 张三
角色在线 梦江南 张三
查在线 张三          # 使用后台默认区服
```

输出：

```text
🌐 [梦江南·张三] 当前在线
来源：第三方在线服务（非 JX3API 名片状态）
```

## 错误

| 错误 | 原因 |
| --- | --- |
| 尚未配置角色在线查询地址 | `online_api_url` 为空 |
| 尚未配置在线查询令牌 | `online_api_token` 为空 |
| 查询角色信息失败 | JX3API Token 失效 / 角色不存在 |
| 在线服务连接失败 | 第三方地址不可达 / TLS / 超时 |
| 在线服务返回 HTTP 401 | 第三方令牌错误 |
| 没有返回可识别的在线状态 | 响应缺少 `gameLogin` 或 `code` 异常 |

## 相关文件

- `jx3portal/online.py`
- `jx3portal/commands.py` 的 `_cmd_online`
- `jx3portal/admin.py` 的 `online_test`
- 参考协议：Inkar-Suki 项目的 `/role_online`
