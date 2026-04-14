# Pixiv to Bilibili Bot

自动从 Pixiv 抓取热门同人作品，经 AI 内容审核与文案生成后，以图文动态和视频动态的形式发布到 Bilibili。

## 功能特性

- **Pixiv 热门作品抓取** — 按自定义标签（原神、崩坏：星穹铁道、鸣潮等）搜索热门插画
- **NSFW 过滤** — 基于 OpenNSFW2 模型自动检测并过滤不适宜内容
- **AI 内容审核与文案生成** — 调用通义千问 VL 模型进行画技评估，并生成适合 B 站风格的标题和文案
- **视频自动生成** — 将图片合成带缩放/平移动效和游戏 OST 背景音乐的视频
- **Bilibili 自动发布** — 支持图文动态和视频动态，扫码登录后自动发布
- **定时调度** — 基于 APScheduler 实现每日定时运行
- **去重机制** — 记录已发布作品 ID，避免重复发布

## 工作流程

```
Pixiv 标签搜索 → 下载图片 → NSFW 过滤 → AI 审核+文案 → 发布到 Bilibili
                                    ↓
                              视频生成（可选）
                                    ↓
                         视频动态发布（可选）
```

## 项目结构

```
├── main.py                 # 主入口，单次运行
├── scheduler.py            # 定时调度入口
├── config/
│   ├── settings.py         # Pydantic 配置定义
│   ├── .env.example        # 环境变量模板
│   └── .env                # 环境变量（需自行创建）
├── core/
│   ├── pixiv_client.py     # Pixiv API 客户端
│   ├── bilibili_client.py  # Bilibili API 客户端
│   ├── safety_checker.py   # NSFW 检测
│   ├── content_checker.py  # AI 内容审核与文案生成
│   ├── video_generator.py  # 视频生成
│   └── bgm_provider.py     # 背景音乐获取
├── utils/
│   ├── image_utils.py      # 图片下载、格式转换、压缩
│   └── logger.py           # 日志配置
└── storage/                # 运行时数据（图片、视频、凭证等）
```

## 安装

### 前置要求

- Python 3.9+
- FFmpeg（视频生成依赖）

### 步骤

```bash
# 1. 克隆仓库
git clone https://github.com/your-username/pixiv-to-bilibili.git
cd pixiv-to-bilibili

# 2. 创建虚拟环境
python -m venv venv
# 或使用 conda
conda create -n pixiv-bot python=3.9
conda activate pixiv-bot

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp config/.env.example config/.env
# 编辑 config/.env，填入你的配置
```

## 配置

复制 `config/.env.example` 为 `config/.env`，填写以下必要配置：

### 必填项

| 变量 | 说明 |
|------|------|
| `PIXIV_REFRESH_TOKEN` | Pixiv Refresh Token，用于 API 认证 |
| `DASHSCOPE_API_KEY` | 阿里云 DashScope API Key，用于 AI 审核和文案生成 |

### Pixiv Refresh Token 获取

1. 登录 [Pixiv](https://www.pixiv.net/)
2. 使用浏览器开发者工具或第三方工具获取 Refresh Token
3. 填入 `PIXIV_REFRESH_TOKEN`

### 可选配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PROXY` | `http://127.0.0.1:7890` | 代理地址，访问 Pixiv 需要，留空则不走代理 |
| `PIXIV_HOT_TAGS` | `原神,崩壊：スターレイル,...` | 搜索标签，逗号分隔 |
| `PIXIV_TAG_SEARCH_LIMIT` | `10` | 每个标签获取的作品数 |
| `NSFW_THRESHOLD` | `0.7` | NSFW 检测阈值，越高越严格 |
| `DAILY_IMAGE_DYNAMICS` | `8` | 每日图文动态数量 |
| `DAILY_VIDEO_DYNAMICS` | `3` | 每日视频动态数量 |
| `PUBLISH_DELAY_MIN` | `60` | 发布间隔（秒） |
| `SCHEDULE_CRON_HOUR` | `9` | 定时运行 - 小时 |
| `SCHEDULE_CRON_MINUTE` | `0` | 定时运行 - 分钟 |

完整配置项见 `config/.env.example`。

## 使用

### 单次运行

```bash
python main.py
```

首次运行时会弹出 Bilibili 二维码，使用 B 站 App 扫码登录。登录凭证会保存到本地，后续无需重复登录。

### 定时运行

```bash
python scheduler.py
```

默认每天 9:00 自动运行，时间可通过环境变量 `SCHEDULE_CRON_HOUR` / `SCHEDULE_CRON_MINUTE` 配置。

## 技术栈

- **PixivPy3** — Pixiv API 交互
- **bilibili-api-python** — Bilibili API 交互
- **OpenNSFW2** — NSFW 内容检测
- **MoviePy + FFmpeg** — 视频生成
- **Pillow** — 图片处理
- **通义千问 VL** (DashScope) — AI 内容审核与文案生成
- **APScheduler** — 任务调度
- **Pydantic Settings** — 配置管理

## 注意事项

- 本工具仅供学习和研究使用，请遵守 Pixiv 和 Bilibili 的相关使用条款
- 发布他人作品时请注意版权，建议标注原作者信息
- 本工具默认包含 NSFW 过滤，但仍需使用者自行把关内容合规性
- 请合理设置发布频率，避免触发平台风控

## License

MIT
