# 剑网3百宝箱 · 安装与注意事项

> 适用于 AstrBot 4.10+ · Python 3.10+
> 版本 1.4.7 · 2026-10-29

---

## 一、环境要求

| 项目 | 最低 | 推荐 |
| --- | --- | --- |
| AstrBot | 4.10 | 4.29+ |
| Python | 3.10 | 3.12 |
| 内存 | 1 GB | **2 GB 以上**（Chromium 吃内存） |
| 磁盘 | 200 MB | 500 MB |
| 系统 | Debian / Ubuntu / CentOS | Debian 12+ |

---

## 二、安装（插件不会自己装任何依赖 ⚠️）

> **重要**：本插件**没有**任何 `pip install` 自动安装代码。
> 所有依赖都必须由你手动安装，否则插件启动会报 `ModuleNotFoundError`。

### 第 1 步：上传插件

```bash
cd /AstrBot/data/plugins
unzip astrbot_plugin_jx3_portal_*.zip
ls astrbot_plugin_jx3_portal/    # 看到 main.py / metadata.yaml 就对了
```

### 第 2 步：安装 Python 依赖

```bash
# 进入 AstrBot 使用的 Python 环境（虚拟环境或系统 Python）
cd /AstrBot
pip install -r data/plugins/astrbot_plugin_jx3_portal/requirements.txt
```

依赖清单：
```
aiohttp>=3.10,<4                      HTTP 请求
jinja2>=3.1,<4                        HTML 模板
beautifulsoup4>=4.12,<5               HTML 解析
Pillow>=10,<13                        图片处理
playwright>=1.40,<2                   浏览器控制
aiosqlite>=0.20,<1                    SQLite 异步
opencc-python-reimplemented>=0.1.7     简繁转换
```

### 第 3 步：安装 Chromium（必须）

```bash
# Debian / Ubuntu
apt update && apt install -y chromium

# CentOS / RHEL
dnf install -y chromium

# 验证
which chromium     # 应该输出 /usr/bin/chromium
```

插件会依次查找这几个路径：
```
/usr/bin/chromium
/usr/bin/chromium-browser
/usr/bin/google-chrome
/usr/bin/google-chrome-stable
```

**找不到会直接抛 `RenderError: 服务器未安装 Chromium`** ⚠️
→ 所有需要出图的功能都会失败。

### 第 4 步：安装中文字体（必须）

```bash
apt install -y fonts-noto-cjk fonts-noto-color-emoji
fc-cache -fv

# 验证
fc-list :lang=zh | head -3    # 应该列出中文字体
```

**不装的话渲染出来的图片中文会是方块／乱码** ⚠️

### 一键安装脚本

```bash
#!/bin/bash
set -e
PLUGIN=/AstrBot/data/plugins/astrbot_plugin_jx3_portal

echo "=== 1/3 Python 依赖 ==="
pip install -r $PLUGIN/requirements.txt

echo "=== 2/3 Chromium ==="
apt update && apt install -y chromium

echo "=== 3/3 中文字体 ==="
apt install -y fonts-noto-cjk fonts-noto-color-emoji
fc-cache -fv

echo "=== 验证 ==="
python3 -c "import aiohttp,jinja2,bs4,PIL,playwright,aiosqlite,opencc; print('✅ Python 依赖 OK')"
which chromium && echo "✅ Chromium OK"
fc-list :lang=zh | head -1

echo "=== 完成 → 去 AstrBot 后台重载插件 ==="
```

---

## 三、必填配置

后台 → 插件 → 剑网3百宝箱 → **接口配置**

| 配置项 | 必填 | 说明 |
| --- | --- | --- |
| `jx3api_token` | ✅ | JX3API 令牌（[jx3api.com](https://www.jx3api.com) 申请） |
| `jx3api_ticket` | 建议 | 推栏 Ticket（名片 / 资历 / 名剑类需要） |
| `doubao_api_key` | 按需 | 豆包 Key（`生图` / `名片生图` 需要） |
| `online_api_url` | 按需 | 角色在线服务地址 |
| `online_api_token` | 按需 | 角色在线服务令牌 |
| `default_server` | 建议 | 默认区服（不写区服时用） |

---

## 四、⚠️ 注意事项（务必看完）

### 4.1 依赖相关

- ❌ **插件不会自动装依赖** —— 必须手动 `pip install -r requirements.txt`
- ❌ **必须装 Chromium** —— 没有它所有出图功能都挂
- ❌ **必须装中文字体** —— 否则图片中文变方块
- ⚠️ **升级 AstrBot 后可能要重装依赖** —— 虚拟环境会被重建

### 4.2 内存相关

- ⚠️ **Chromium 很吃内存** —— 建议 2 GB 以上
- ⚠️ **1 GB 机器**：把 `image_render_quality` 的 `device_scale_factor` 调到 `0.8`
- ⚠️ **同时渲染多张图会 OOM** —— 插件已限制并发，但不要连续狂刷
- 💡 渲染进程空闲时 Chromium 会自动关闭释放内存（闲置 300 秒）

### 4.3 数据与备份

- 📁 **`plugin_data/` 目录必须备份**：
  ```
  /AstrBot/data/plugin_data/astrbot_plugin_jx3_portal/
    ├── server_binding.json   会话区服绑定
    ├── role_binding.json     用户角色绑定
    ├── bilei.json            避雷记录
    ├── team.json             团队数据
    ├── card_styles.json      名片生图模板
    ├── paid_state.json       付费授权
    └── card_ai_error.log     名片生图错误日志
  ```
- ⚠️ **升级/重装插件前先备份 `plugin_data/`** —— 旧包覆盖不会删它，但删插件目录会
- ⚠️ **别把备份目录放进 `plugins/`** —— AstrBot 会当成第二个插件加载

### 4.4 平台相关

- ✅ **按钮菜单只支持 QQ 官方机器人**（`qq_official` / `qq_official_webhook`）
  → 其他平台自动回退文字菜单
- ⚠️ **QQ 群拿不到群主/管理员列表** —— 团队指令的权限判断依赖：
  1. AstrBot 管理员
  2. 插件配置的「团队管理员 QQ 列表」
  3. 平台返回的角色
- ⚠️ **群聊必须 @ 机器人**（QQ 官方机制）

### 4.5 接口与额度

- ⚠️ **JX3API 有每日/每小时限额** —— 建议把 `jx3api_cache_ttl` 调到 600 秒以上
- ⚠️ **角色未收录** —— 部分角色没进 JX3API 数据库时，资历/名片会返回「未收录」
  → 需要在游戏**世界频道说过话**才会被收录
- ⚠️ **推栏 Ticket 会过期** —— 过期后名片/资历类功能失效，需重新抓包
- ⚠️ **JX3BOX 是公开接口** —— 不需要账号，但可能需要代理

### 4.6 文件占位符

`名片生图` 的提示词支持 3 个占位符，生成前会自动替换：

| 占位符 | 替换成 |
| --- | --- |
| `{force}` | 门派名（如：纯阳、刀宗） |
| `{body}` | 体型（成男 / 成女 / 正太 / 萝莉） |
| `{name}` | 角色名 |

⚠️ 如果模板用了 `{force}` 但查不到门派 → 会提示「换个模板试试」

### 4.7 常见坑

| 现象 | 原因 | 解决 |
| --- | --- | --- |
| 插件加载失败 | 缺 `__init__.py` 或依赖没装 | 看日志 `ModuleNotFoundError` |
| 所有图都不出 | 没装 Chromium | `apt install chromium` |
| 图里中文是方块 | 没装中文字体 | `apt install fonts-noto-cjk` |
| 后台页面空白 | 浏览器缓存旧 JS | Ctrl+F5 强制刷新 |
| 按钮不出现 | 不是 QQ 官方机器人 | 检查 `support_platforms` |
| 名片生图报错 | 看 `card_ai_error.log` | 里面有完整堆栈 |
| 团队指令没权限 | 拿不到群主信息 | 后台填「团队管理员 QQ 列表」 |

---

## 五、文件结构说明

```
astrbot_plugin_jx3_portal/
├── main.py                    插件入口（监听消息、注册后台 API、分发指令）
├── metadata.yaml              插件元信息（名称/版本/支持平台）
├── _conf_schema.json          AstrBot 插件配置项定义
├── requirements.txt           Python 依赖清单
├── README.md                  项目说明
├── CHANGELOG.md               更新日志
├── LICENSE
├── logo.png
│
├── jx3portal/                 ★ 核心代码包
│   ├── commands.py            指令注册 + 分发 + 所有指令实现（最大文件）
│   ├── card_styles.py         名片生图模板库（16 个默认 + 增删改）
│   ├── buttons.py             QQ 原生按钮（Button / MenuReply / keyboard）
│   ├── admin.py               后台 API 控制器（9 个页面的接口）
│   ├── settings.py            配置读写与校验
│   ├── jx3api.py              JX3API 客户端（鉴权 / 缓存 / 重试）
│   ├── jx3box.py              JX3BOX 魔盒客户端
│   ├── online.py              角色在线查询
│   ├── tuilan.py              推栏 Ticket 管理
│   ├── doubao.py              豆包生图
│   ├── render.py              HTML → 图片渲染
│   ├── render_worker.py       渲染子进程（被 local_render 拉起）
│   ├── local_render.py        本地渲染服务管理（检查 Chromium）
│   ├── event_push.py          事件推送（WebSocket）
│   ├── paid.py                付费授权 / 激活码
│   ├── cache.py               TTL 缓存
│   ├── telemetry.py           请求日志与统计
│   ├── format.py              文本格式化
│   └── game/                  ★ 游戏数据子包
│       ├── data.py            数据服务（最大，91 KB）
│       ├── service.py         服务组装
│       ├── bindings.py        区服/角色绑定
│       ├── team.py            ★ 团队数据层
│       ├── team_manager.py    ★ 团队管理（权限/开团/报名）
│       ├── team_rules.py      团队报名限制
│       ├── bilei_data.py      ★ 避雷数据
│       ├── tarot.py           ★ 塔罗牌
│       ├── daily_tarot.py     今日塔罗
│       ├── fortune.py         运势 / 恋爱书
│       ├── horoscope.py       星座运势
│       ├── birth_chart.py     八字
│       ├── market*.py         物价历史/走势/设计
│       ├── equipment.py       装备
│       ├── kungfu_alias.py    心法别名
│       └── sqlite.py          异步 SQLite
│
├── templates/                 ★ 聊天输出模板（发给用户看的图）
│   ├── pages/                 69 个 HTML（每条指令对应一页）
│   │   ├── hangqing.html      物价
│   │   ├── online_stats.html  在线统计
│   │   ├── shapan.html        沙盘
│   │   └── ...
│   ├── layouts/base.html      公共布局
│   ├── styles/                公共 CSS（base / components / ink / tokens）
│   ├── sect/                  56 个门派图标
│   ├── serendipity/           129 个奇遇图标
│   ├── img/                   阵营 / 沙盘图标（99 个）
│   └── assets/
│       ├── ink/               水墨字体（8.5 MB）
│       └── tarot/             塔罗牌图（21 MB，可选）
│
├── views/dashboard/           ★ 后台管理页（9 个标签页）
│   ├── index.html             后台页面结构
│   ├── app.js                 前端逻辑（2019 行）
│   ├── style.css              样式
│   └── assets/                后台用图标
│
├── data/                      ★ 静态数据（随插件分发）
│   ├── endpoints.json         83 个 JX3API 接口目录
│   ├── game_commands.json     游戏指令数据
│   ├── kungfu.json            心法数据
│   ├── server_aliases.json    区服别名
│   ├── servers.json           区服列表
│   ├── tarot/cards.json       塔罗牌数据
│   └── fortune/               运程数据
│
├── docs/                      ★ 文档
│   ├── INSTALL.md             ← 本文件
│   ├── ADMIN.md               后台使用说明
│   ├── JX3API.md              JX3API 接口说明
│   ├── JX3BOX.md              JX3BOX 说明
│   ├── EVENT_PUSH.md          事件推送说明
│   ├── ONLINE.md              在线查询说明
│   ├── TUILAN.md              推栏说明
│   ├── DOUBAO.md              豆包生图说明
│   ├── DEVELOPMENT.md         开发说明
│   └── screenshots/           后台截图（2.6 MB）
│
└── tests/                     单元测试（不影响运行）

运行时数据（不在插件目录，需单独备份）：
/AstrBot/data/plugin_data/astrbot_plugin_jx3_portal/
```

---

## 六、验证安装是否成功

```bash
# 1. Python 依赖
python3 -c "import aiohttp, jinja2, bs4, PIL, playwright, aiosqlite; print('OK')"

# 2. Chromium
which chromium

# 3. 中文字体
fc-list :lang=zh | head -1

# 4. 插件能否导入
cd /AstrBot && python3 -c "
import sys; sys.path.insert(0, 'data/plugins')
from astrbot_plugin_jx3_portal.jx3portal.commands import COMMAND_MAP
print('指令数:', len(COMMAND_MAP))
"
```

**AstrBot 后台 → 插件 → 剑网3百宝箱 → 重载**
→ 日志出现「剑网3百宝箱已加载」就成功 ✅

---

## 七、升级说明

```bash
# 1. 备份运行时数据 ⚠️
cp -r /AstrBot/data/plugin_data/astrbot_plugin_jx3_portal ~/jx3portal_backup

# 2. 备份旧插件（可选）
mv /AstrBot/data/plugins/astrbot_plugin_jx3_portal /tmp/jx3portal_old

# 3. 解压新包
cd /AstrBot/data/plugins && unzip 新包.zip

# 4. 重装依赖（可能新增依赖）
pip install -r astrbot_plugin_jx3_portal/requirements.txt

# 5. 后台重载插件
```

⚠️ **不要直接覆盖** —— 先把旧目录移走，避免残留文件冲突。

---

## 八、卸载

```bash
# 1. 先备份运行时数据
cp -r /AstrBot/data/plugin_data/astrbot_plugin_jx3_portal ~/jx3portal_backup

# 2. 删除插件目录
rm -rf /AstrBot/data/plugins/astrbot_plugin_jx3_portal

# 3. （可选）删除运行时数据
rm -rf /AstrBot/data/plugin_data/astrbot_plugin_jx3_portal

# 4. 后台重载
```
