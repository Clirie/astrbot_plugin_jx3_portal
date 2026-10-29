# 豆包生图

插件接入火山方舟（豆包）的 OpenAI 兼容图片生成接口：

```http
POST {doubao_base_url}/images/generations
Authorization: Bearer {doubao_api_key}
Content-Type: application/json
```

## 配置

| 配置键 | 默认值 | 说明 |
| --- | --- | --- |
| `doubao_api_key` | 空 | 火山方舟 API Key |
| `doubao_base_url` | `https://ark.cn-beijing.volces.com/api/v3` | 方舟 API 地址 |
| `doubao_model` | `doubao-seedream-5-0-flash-260915` | 图片模型 ID |
| `doubao_size` | `1024x1024` | 尺寸，支持 `2K` / `1024x1536` 等 |
| `doubao_watermark` | `false` | 是否加水印 |
| `doubao_timeout` | `180` | 生成超时（秒） |

在 [火山方舟控制台](https://console.volcengine.com/ark) 创建 Key，并开通对应的图片模型。后台「接口配置 → 豆包生图」提供「测试 Key」按钮（调用 `/models`）。

## 指令

```text
生图 剑网3 水墨 花间 成女
图生图 https://example.com/ref.png 改成水墨国风
绘图 赛博朋克 七秀
垫图 https://example.com/ref.png 塔罗牌风格
```

- `生图`：文生图。
- `图生图`：第一个参数是参考图 URL，后面是提示词；URL 必须 `http://` 或 `https://`。
- 生成结果保存到插件的 `aigen/` 目录，并通过 AstrBot 图片消息发送。
- 图片生成耗时通常 10~30 秒；指令冷却默认 20 秒。

## 请求体

```json
{
  "model": "doubao-seedream-5-0-flash-260915",
  "prompt": "剑网3 水墨 花间 成女",
  "size": "1024x1024",
  "response_format": "url",
  "watermark": false,
  "image": "https://example.com/ref.png"
}
```

`image` 只在图生图时出现。插件优先使用响应里的 `data[0].url`，下载后保存；如果返回 `b64_json` 则直接解码保存。

## 错误处理

| 状态 / 错误码 | 提示 |
| --- | --- |
| 401 / `AuthenticationError` | API Key 不对或过期 |
| 403 / `PermissionDenied` | 模型未开通或没有权限 |
| 429 / `RateLimit` | 请求过于频繁 |
| `ModelNotFound` | 模型 ID 不存在，检查 `doubao_model` |
| 超时 | 调大 `doubao_timeout`，或稍后再试 |

`/models` 探活返回 404 时，插件会提示“接口可达，但 /models 不可用；请用一次生图验证 Key 和模型”，因为部分方舟部署不开放模型列表。

## 成本与安全

- 生图按方舟计费，请在控制台设置额度；插件默认把 `生图` / `图生图` 标记为付费指令，配合付费授权限制使用。
- API Key 只保存在 AstrBot 配置中，后台只显示掩码。
- 生成图片保存在插件数据目录，不会上传到其他服务（除了方舟接口本身）。

## 相关文件

- `jx3portal/doubao.py`
- `jx3portal/commands.py` 的 `_cmd_image` / `_cmd_image_edit`
- `jx3portal/http.py` 的 `request_bytes`（下载生成图）
