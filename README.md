# Zhihu Activity Archiver

知乎动态自动化归档机器人。它会抓取指定知乎主页的最新动态，提取正文、第一页评论和图片资源，保存为 Markdown，并自动同步到 GitHub 数据仓库。

项目同时内置 Telegram 机器人，支持手动触发、定时抓取、运行状态查看、统计查询和部署自检。

## 功能概览

- 抓取知乎个人主页动态，包括赞同、发布、发表等活动。
- 提取回答正文，并通过知乎评论 API 抓取第一页评论。
- 自动下载正文图片，保存到对应文章的 `_图片` 目录。
- 按 `YYYY/MM/` 结构归档 Markdown 文件。
- 使用 SQLite 记录已抓取文章，避免重复抓取。
- 抓取完成后自动 `git add/commit/push` 到归档仓库。
- 通过 Telegram 命令控制和查看运行状态。
- 支持 Docker Compose 部署，程序代码和归档数据分离。

## 目录结构

```text
savezhihu/
├── main_bot.py           # Telegram 机器人、定时任务、GitHub 同步
├── zhihu_scraper.py      # 知乎动态抓取、正文/评论/图片提取
├── init_login.py         # 本地生成知乎登录 state.json
├── docker-compose.yml    # Docker Compose 部署配置
├── Dockerfile            # Docker 镜像构建文件
├── requirements.txt      # Python 依赖
├── .env.example          # 环境变量模板
├── .dockerignore         # Docker 构建排除规则
├── DEPLOY.md             # 完整部署和迁移指南
└── README.md
```

推荐的 VPS 数据目录：

```text
/root/savezhihu/                         # 主程序
/root/zhihu_data/save_zhihu_activity/    # Markdown 归档 Git 仓库
/root/zhihu_data/zhihu_articles.db       # SQLite 去重数据库
```

归档仓库结构：

```text
save_zhihu_activity/
├── 2024/
│   ├── 06/
│   └── 07/
├── 2025/
└── 2026/
    └── 04/
```

## 快速部署

完整部署、迁移和恢复步骤请看 [DEPLOY.md](DEPLOY.md)。

最小流程：

```bash
cd /root
git clone https://github.com/maxlixiang/savezhihu.git savezhihu
cd /root/savezhihu
cp .env.example .env
```

准备数据目录：

```bash
mkdir -p /root/zhihu_data
cd /root/zhihu_data
git clone https://github.com/maxlixiang/save_zhihu_activity.git
```

放置必要文件：

```text
/root/savezhihu/.env
/root/savezhihu/state.json
/root/zhihu_data/zhihu_articles.db
```

启动服务：

```bash
cd /root/savezhihu
docker compose up -d --build
docker logs --tail 200 zhihu_bot
```

## 环境变量

从 `.env.example` 复制生成 `.env`：

```env
TG_BOT_TOKEN=
TG_CHAT_ID=
GITHUB_TOKEN=
GITHUB_REPOSITORY=maxlixiang/save_zhihu_activity
ARCHIVE_ROOT_DIR=/app/save_zhihu_activity
GITHUB_REPO_PATH=/app/save_zhihu_activity
ZH_DB_FILE=/app/zhihu_articles.db
```

说明：

- `TG_BOT_TOKEN`：Telegram Bot Token。
- `TG_CHAT_ID`：接收通知的 Telegram Chat ID。
- `GITHUB_TOKEN`：有归档仓库写权限的 GitHub PAT。
- `GITHUB_REPOSITORY`：归档仓库名，默认 `maxlixiang/save_zhihu_activity`。
- `ARCHIVE_ROOT_DIR`：容器内 Markdown 归档路径。
- `GITHUB_REPO_PATH`：容器内执行 Git 同步的仓库路径。
- `ZH_DB_FILE`：容器内 SQLite 数据库路径。

不要提交真实 `.env`、`state.json` 或 `zhihu_articles.db`。

## Telegram 命令

```text
/latest
```

立即执行一次增量抓取。抓取成功后会保存 Markdown，并推送到 GitHub。

```text
/status
```

查看容器运行时间、最近一次抓取时间、最近抓取结果、数据仓库路径、Git 状态和数据库大小。

```text
/stats
/stats 2026-01
/stats 2026
```

查看抓取统计：

- `/stats`：默认统计当月每天抓取数。
- `/stats YYYY-MM`：统计指定月份每天抓取数。
- `/stats YYYY`：统计指定年份每月抓取数。

```text
/check
```

执行配置自检，检查 `state.json`、归档目录、Git 仓库、数据库路径和 GitHub token 配置。

```text
/help
```

查看完整命令说明。

## 本地调试

只测试第一条动态的正文和评论，不写数据库、不保存 Markdown、不推 GitHub：

```bash
python zhihu_scraper.py --debug-comments
```

正常抓取指定数量的新动态：

```bash
python zhihu_scraper.py --limit 5
```

## 维护命令

查看日志：

```bash
docker logs -f zhihu_bot
```

重建容器：

```bash
cd /root/savezhihu
docker compose up -d --build
```

检查容器内挂载：

```bash
docker exec -it zhihu_bot env | grep -E "ARCHIVE_ROOT_DIR|GITHUB_REPO_PATH|ZH_DB_FILE"
docker exec -it zhihu_bot git -C /app/save_zhihu_activity status --short --branch
docker exec -it zhihu_bot test -f /app/state.json && echo "state.json OK"
```

VPS 磁盘紧张时清理 Docker 构建缓存：

```bash
docker builder prune -f
docker system df
```

## 已知限制

当前 SQLite 去重键由“动态时间 + 标题”生成。对于回答动态，标题通常是问题标题，所以同一个问题下的不同回答一般会因为动态时间不同而被识别为不同文章。

极小概率情况下，如果同一个问题下的不同回答在主页动态里显示为同一分钟，且标题完全相同，可能被误判为已抓取。后续如果遇到类似漏抓，可将去重键升级为优先使用 `answer_id`。

## 迁移重点

迁移到新 VPS 时，重点备份：

```text
/root/savezhihu/.env
/root/savezhihu/state.json
/root/zhihu_data/zhihu_articles.db
```

Markdown 归档可以从 GitHub 重新 clone：

```bash
git clone https://github.com/maxlixiang/save_zhihu_activity.git /root/zhihu_data/save_zhihu_activity
```

更完整的迁移步骤见 [DEPLOY.md](DEPLOY.md)。

## 免责声明

本工具仅供个人学习与数据备份使用。请合理设置抓取频率，避免对知乎服务器造成过大压力。严禁用于商业用途或破坏性用途。
