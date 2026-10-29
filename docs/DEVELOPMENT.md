# 开发与测试

## 执行路径

```text
QQ 消息
  → main.py：识别主指令、别名和“剑三 子指令”
  → CommandService.run：开关、权限、付费条件、冷却、总超时
  → _cmd_*：解析参数并调用数据服务
  → JX3API / JX3BOX / 在线接口：HTTP 连接复用、数据缓存
  → format.py 文字，或 render.py + templates/ 图片
  → main.py：发送结果
```

`main.py` 不编写业务 API 参数。`COMMANDS` 是唯一指令目录，启动时生成名字到 key 的映射，再直接调用 `CommandService.run`。没有逐指令的转发包装层。

## 代码职责

| 文件 | 职责 |
| --- | --- |
| main.py | AstrBot 生命周期、监听器、后台路由 |
| commands.py | 指令定义、配置条件、权限、参数、功能流程 |
| jx3api.py / jx3box.py | 数据源访问和响应适配 |
| http.py / cache.py | 共享 HTTP 连接、请求总时限、并发请求合并、过期缓存 |
| format.py | 面向用户的文字格式 |
| render.py / templates/ | 页面数据、HTML 模板和图片缓存 |
| local_render.py / render_worker.py | 独立本机渲染进程；不修改外部渲染端点 |
| articles.py | 正文清理、新闻摘要、代表图与分页 |
| event_push.py | 订阅、推送连接、新闻后台任务、投递 |
| settings.py / aliases.py / storage.py | 配置校验、区服别名、原子文件写入 |
| paid.py | 授权与激活码的同一份状态 |
| online.py / tuilan.py / doubao.py | 条件服务的实际协议 |
| admin.py / views/dashboard/ | 后台操作与页面 |
| telemetry.py | 有界运行统计；不记录普通聊天正文 |

## 增加一个指令

在 `commands.py` 的 `COMMANDS` 中增加条目：

```python
CommandSpec("my_feature", "我的功能", ("别名",), "我的功能 参数", "功能说明", "分类", cooldown=3, requires=("token",))
```

在 `CommandService` 增加实现：

```python
async def _cmd_my_feature(self, args, event):
    name = self._require(args, "请提供名称")
    data = await self.api.request("/my/endpoint", {"name": name})
    return fmt.my_formatter(data)
```

目录生成注册、帮助和后台配置，不需要再改监听器或增加转发方法。新增功能应验证参数缺失、真实返回结构和失败回复。用户文字应给自然说明，内部异常记录在后台。

图片返回 `ImageReply(path)`，分页返回 `ImageReply(path, tuple(other_paths))`。图片应在本机预览，检查文字尺寸、裁切和空数据。只有 HTML 模板没有命令和数据适配，不算功能完成。

## 等待和资源管理

普通命令从参数处理到结果最多 35 秒；单次 HTTP 请求的预算包括连接、排队、响应体和重试。不会因为重试而重新获得完整超时。付费生图 POST 不自动重试。

插件关闭时取消新闻配图及待执行的重连任务，然后关闭缓存任务、HTTP 连接和自己启动的渲染进程。已有外部渲染进程不由百宝箱关闭。

缓存键包含查询数据、凭据指纹或模板版本；同一个查询在执行期间可共用请求，返回值深拷贝，调用者修改不会污染缓存。

## 配置和授权存储

原子写入成功以后再替换内存状态；AstrBot 配置写入失败则还原内存。用户设置保存失败时，不可以返回成功。

授权和激活码存于 `paid_state.json`，消费激活码与延长授权同时提交。旧文件只用于首次兼容读取，启动本身不会覆盖它们。若已用新版修改授权，再回滚至 1.1.1，需要先把 `paid_state.json` 的 `groups` 和 `codes` 分别导出为旧文件格式。

## 测试与发布

```bash
python -m pytest -q tests
python -m compileall -q .
```

回归测试覆盖路由、权限、缓存并发与取消、超时、数据适配、原子保存失败、授权重启一致性、订阅继承和新闻退订。外部付费生图使用模拟响应，不在测试里扣费。

发布前对比线上哈希；备份变更文件和删除清单；只部署百宝箱；重启后检查初始化、渲染健康和实际查询。不要导出完整群聊日志，也不要向真实群发送测试消息。
