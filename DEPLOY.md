# Deployment Guide

This service keeps application code and archive data separate:

```text
/root/savezhihu/                         # app repository
/root/zhihu_data/save_zhihu_activity/    # archive Git repository
/root/zhihu_data/zhihu_articles.db       # de-duplication database
```

## 1. Prepare The VPS

Install Docker, Docker Compose, and Git.

```bash
docker --version
docker compose version
git --version
```

## 2. Clone The App

```bash
cd /root
git clone https://github.com/maxlixiang/savezhihu.git savezhihu
cd /root/savezhihu
```

If the app repository URL is different, clone that repository instead.

## 3. Prepare Secrets

Create `/root/savezhihu/.env` from `.env.example`:

```bash
cp .env.example .env
nano .env
```

Required values:

```env
TG_BOT_TOKEN=
TG_CHAT_ID=
GITHUB_TOKEN=
GITHUB_REPOSITORY=maxlixiang/save_zhihu_activity
ARCHIVE_ROOT_DIR=/app/save_zhihu_activity
GITHUB_REPO_PATH=/app/save_zhihu_activity
ZH_DB_FILE=/app/zhihu_articles.db
```

Do not commit `.env`.

## 4. Add Zhihu Login State

Copy a valid `state.json` to:

```text
/root/savezhihu/state.json
```

If it expires, regenerate it locally with `init_login.py`, upload the new file, then restart the container.

## 5. Prepare Archive Data

Create the data root:

```bash
mkdir -p /root/zhihu_data
```

Clone the archive repository:

```bash
cd /root/zhihu_data
git clone https://github.com/maxlixiang/save_zhihu_activity.git
```

If you want the host repository itself to contain credentials, set its remote manually. The bot can also push with `GITHUB_TOKEN` without writing the token into `.git/config`.

Check the archive repository:

```bash
git -C /root/zhihu_data/save_zhihu_activity status
git -C /root/zhihu_data/save_zhihu_activity remote -v
ls -la /root/zhihu_data/save_zhihu_activity
```

Place or restore the de-duplication database:

```bash
# If restoring from backup:
cp /path/to/zhihu_articles.db /root/zhihu_data/zhihu_articles.db

# If starting fresh:
touch /root/zhihu_data/zhihu_articles.db
```

## 6. Start The Service

```bash
cd /root/savezhihu
docker compose up -d --build
```

Check startup logs:

```bash
docker logs --tail 200 zhihu_bot
```

The log should include:

```text
启动前自检通过
Telegram 机器人守护进程已启动
```

## 7. Verify Container Paths

```bash
docker exec -it zhihu_bot env | grep -E "ARCHIVE_ROOT_DIR|GITHUB_REPO_PATH|ZH_DB_FILE"
docker exec -it zhihu_bot ls -la /app/save_zhihu_activity
docker exec -it zhihu_bot git -C /app/save_zhihu_activity status --short --branch
docker exec -it zhihu_bot test -f /app/state.json && echo "state.json OK"
```

Expected environment:

```text
ARCHIVE_ROOT_DIR=/app/save_zhihu_activity
GITHUB_REPO_PATH=/app/save_zhihu_activity
ZH_DB_FILE=/app/zhihu_articles.db
```

## 8. Test The Bot

In Telegram, send:

```text
/latest
```

If there is a new activity, the bot should:

1. Fetch the activity body and comments.
2. Save Markdown under `YYYY/MM/`.
3. Commit and push to GitHub.

Check the archive on the host:

```bash
git -C /root/zhihu_data/save_zhihu_activity status --short --branch
find /root/zhihu_data/save_zhihu_activity/2026 -maxdepth 2 -type f | tail
```

Check runtime status:

```text
/status
```

The bot replies with container uptime, last scrape time, archive path, Git cleanliness, and database size.

## 9. Common Operations

View logs:

```bash
docker logs -f zhihu_bot
```

Restart:

```bash
cd /root/savezhihu
docker compose restart
```

Rebuild after code changes:

```bash
cd /root/savezhihu
docker compose up -d --build
```

Clean Docker build cache if the VPS disk is tight:

```bash
docker builder prune -f
docker system df
```

## 10. Migration Checklist

Back up or copy these files before moving to a new VPS:

```text
/root/savezhihu/.env
/root/savezhihu/state.json
/root/zhihu_data/zhihu_articles.db
```

The Markdown archive can be restored by cloning:

```bash
git clone https://github.com/maxlixiang/save_zhihu_activity.git /root/zhihu_data/save_zhihu_activity
```

After restoring files, run:

```bash
cd /root/savezhihu
docker compose up -d --build
docker logs --tail 200 zhihu_bot
```

---

# 中文部署指南

本服务建议把程序代码和归档数据分开存放：

```text
/root/savezhihu/                         # 主程序仓库
/root/zhihu_data/save_zhihu_activity/    # 知乎归档数据仓库
/root/zhihu_data/zhihu_articles.db       # SQLite 去重数据库
```

## 1. 准备 VPS 环境

确认 VPS 已安装 Docker、Docker Compose 和 Git：

```bash
docker --version
docker compose version
git --version
```

## 2. 克隆主程序

```bash
cd /root
git clone https://github.com/maxlixiang/savezhihu.git savezhihu
cd /root/savezhihu
```

如果主程序仓库地址不同，请替换成实际地址。

## 3. 配置敏感信息

从 `.env.example` 创建 `.env`：

```bash
cp .env.example .env
nano .env
```

需要填写：

```env
TG_BOT_TOKEN=
TG_CHAT_ID=
GITHUB_TOKEN=
GITHUB_REPOSITORY=maxlixiang/save_zhihu_activity
ARCHIVE_ROOT_DIR=/app/save_zhihu_activity
GITHUB_REPO_PATH=/app/save_zhihu_activity
ZH_DB_FILE=/app/zhihu_articles.db
```

不要把 `.env` 提交到 Git。

## 4. 放置知乎登录状态

把有效的 `state.json` 上传到：

```text
/root/savezhihu/state.json
```

如果知乎登录态过期，在本地重新运行 `init_login.py` 生成新的 `state.json`，上传覆盖后重启容器。

## 5. 准备归档数据目录

创建数据根目录：

```bash
mkdir -p /root/zhihu_data
```

克隆归档数据仓库：

```bash
cd /root/zhihu_data
git clone https://github.com/maxlixiang/save_zhihu_activity.git
```

程序会通过 `.env` 里的 `GITHUB_TOKEN` 临时拼接 push URL，不会把 token 写入 `.git/config`。

检查归档仓库：

```bash
git -C /root/zhihu_data/save_zhihu_activity status
git -C /root/zhihu_data/save_zhihu_activity remote -v
ls -la /root/zhihu_data/save_zhihu_activity
```

恢复或创建去重数据库：

```bash
# 如果有备份：
cp /path/to/zhihu_articles.db /root/zhihu_data/zhihu_articles.db

# 如果从零开始：
touch /root/zhihu_data/zhihu_articles.db
```

## 6. 启动服务

```bash
cd /root/savezhihu
docker compose up -d --build
```

查看启动日志：

```bash
docker logs --tail 200 zhihu_bot
```

日志中应看到：

```text
启动前自检通过
Telegram 机器人守护进程已启动
```

## 7. 验证容器挂载和环境变量

```bash
docker exec -it zhihu_bot env | grep -E "ARCHIVE_ROOT_DIR|GITHUB_REPO_PATH|ZH_DB_FILE"
docker exec -it zhihu_bot ls -la /app/save_zhihu_activity
docker exec -it zhihu_bot git -C /app/save_zhihu_activity status --short --branch
docker exec -it zhihu_bot test -f /app/state.json && echo "state.json OK"
```

期望看到：

```text
ARCHIVE_ROOT_DIR=/app/save_zhihu_activity
GITHUB_REPO_PATH=/app/save_zhihu_activity
ZH_DB_FILE=/app/zhihu_articles.db
```

## 8. 测试 Telegram 机器人

在 Telegram 里发送：

```text
/latest
```

如果有新动态，程序会：

1. 抓取正文和评论。
2. 保存 Markdown 到 `YYYY/MM/` 目录。
3. 自动 commit 并 push 到 GitHub。

在 VPS 上检查归档仓库：

```bash
git -C /root/zhihu_data/save_zhihu_activity status --short --branch
find /root/zhihu_data/save_zhihu_activity/2026 -maxdepth 2 -type f | tail
```

查看运行状态：

```text
/status
```

机器人会返回容器运行时间、最近一次抓取时间、数据仓库路径、Git 状态和数据库大小。

## 9. 常用维护命令

查看日志：

```bash
docker logs -f zhihu_bot
```

重启服务：

```bash
cd /root/savezhihu
docker compose restart
```

代码更新后重新构建：

```bash
cd /root/savezhihu
docker compose up -d --build
```

如果 VPS 磁盘空间紧张，清理 Docker 构建缓存：

```bash
docker builder prune -f
docker system df
```

## 10. 迁移到新 VPS 时需要备份的文件

迁移前重点备份：

```text
/root/savezhihu/.env
/root/savezhihu/state.json
/root/zhihu_data/zhihu_articles.db
```

Markdown 归档可以通过 GitHub 重新 clone：

```bash
git clone https://github.com/maxlixiang/save_zhihu_activity.git /root/zhihu_data/save_zhihu_activity
```

恢复后执行：

```bash
cd /root/savezhihu
docker compose up -d --build
docker logs --tail 200 zhihu_bot
```
