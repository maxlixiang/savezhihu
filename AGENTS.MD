# 项目理解与维护笔记

## 项目定位

这是一个“知乎动态自动归档”服务。核心目标是抓取指定知乎用户主页的最新动态，把正文、首屏评论和正文图片保存为 Markdown 归档，并在抓取完成后自动提交、推送到独立的 GitHub 归档仓库。

项目同时内置 Telegram Bot，用 Telegram 命令触发抓取、查看运行状态、查看统计和执行配置自检。生产环境推荐用 Docker Compose 部署，程序代码仓库与归档数据仓库分开挂载。

## 核心文件

- `main_bot.py`：服务入口。负责加载环境变量、启动 Telegram Bot、注册命令、定时任务、运行前自检、调用爬虫、提交并推送归档仓库。
- `zhihu_scraper.py`：知乎抓取核心。负责用 Playwright 加载知乎登录态、扫描活动列表、提取正文、提取回答 ID、调用评论 API、下载图片、写 Markdown、写 SQLite 去重记录。
- `init_login.py`：本地生成知乎登录态。会打开有界面 Chromium，等待手动登录 60 秒，然后把 Playwright storage state 保存到 `state.json`。
- `docker-compose.yml`：生产部署编排。把归档 Git 仓库、SQLite 数据库和只读 `state.json` 挂载进容器。
- `Dockerfile`：基于 Playwright Python 镜像构建，安装 Git、tzdata、Python 依赖和 Chromium。
- `.env.example`：环境变量模板。
- `DEPLOY.md`：详细部署、迁移、验证和维护说明。

## 运行架构

推荐生产路径如下：

```text
/root/savezhihu/                         # 主程序仓库
/root/zhihu_data/save_zhihu_activity/    # Markdown 归档 Git 仓库
/root/zhihu_data/zhihu_articles.db       # SQLite 去重数据库
```

容器内路径如下：

```text
/app/save_zhihu_activity                 # 归档仓库挂载点
/app/zhihu_articles.db                   # 去重数据库挂载点
/app/state.json                          # 知乎登录态，只读挂载
```

`main_bot.py` 启动后会先执行 `validate_runtime_environment()`，检查：

- `state.json` 是否存在。
- `ARCHIVE_ROOT_DIR` 是否存在。
- `GITHUB_REPO_PATH` 是否是 Git 仓库。
- `ZH_DB_FILE` 所在目录或数据库文件是否可写。
- Git origin 和 `GITHUB_TOKEN` 配置是否可能影响 push。

自检通过后启动 Telegram 轮询，并在后台线程里注册每天 03:00 的定时抓取任务。

## 关键环境变量

- `TG_BOT_TOKEN`：Telegram Bot token，缺失会直接启动失败。
- `TG_CHAT_ID`：接收通知和状态消息的 Telegram chat id，缺失会直接启动失败。
- `GITHUB_TOKEN`：有归档仓库写权限的 GitHub token。存在时 push 使用临时 token URL，不写入 `.git/config`。
- `GITHUB_REPOSITORY`：归档仓库名，默认 `maxlixiang/save_zhihu_activity`。
- `ARCHIVE_ROOT_DIR`：Markdown 归档根目录，容器内通常是 `/app/save_zhihu_activity`。
- `GITHUB_REPO_PATH`：执行 `git add/commit/push` 的仓库路径，通常与 `ARCHIVE_ROOT_DIR` 相同。
- `ZH_DB_FILE`：SQLite 去重数据库路径，容器内通常是 `/app/zhihu_articles.db`。

敏感和运行态文件不要提交：`.env`、`state.json`、`zhihu_articles.db`。

## 抓取流程

`run_zhihu_scraper(limit=20, progress_callback=None)` 是主要入口：

1. 初始化 SQLite 表 `articles(title TEXT PRIMARY KEY, scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)`。
2. 用 Playwright Chromium headless 模式加载 `state.json`。
3. 访问 `https://www.zhihu.com/people/li-xiang-57-76/activities`。
4. 遍历页面上的 `.List-item` 动态卡片。
5. 只处理活动文本里包含“赞同”“发布”“发表”的动态。
6. 从动态 meta 文本里解析时间，生成形如 `[YYYY-MM-DD_HH-MM]` 的文件名前缀。
7. 普通回答使用 `.ContentItem-title` 作为标题；想法类动态使用作者名加“想法”。
8. 用 `clean_file_name()` 清理文件名，并以清理后的完整标题作为 SQLite 去重主键。
9. 若连续遇到 10 条以上已存在记录，则认为增量抓取结束。
10. 展开“阅读全文”或“展开全文”，用 `markdownify` 把正文 HTML 转为 Markdown。
11. 尝试从链接或 `data-zop` 中提取 `answer_id`。
12. 如果能识别回答 ID，就请求知乎评论 API 的第一页 root comments，最多 15 条。
13. 下载正文 Markdown 里的远程图片到同名子目录，并把图片链接替换为相对路径。
14. 写入 `ARCHIVE_ROOT_DIR/YYYY/MM/[时间] 标题.md`。
15. 把标题写入 SQLite，返回本轮新增标题列表。

归档文件目录由动态时间决定，格式是 `YYYY/MM/`。如果无法解析时间，则退回当前系统年月。

## Telegram 命令

- `/latest`：新线程执行一次增量抓取，成功后自动 Git 同步。
- `/status`：返回运行时间、最近抓取时间、最近结果、归档路径、Git 状态和数据库大小。
- `/stats`：统计当月每天的归档数量。
- `/stats YYYY-MM`：统计指定月份每天的归档数量。
- `/stats YYYY`：统计指定年份每月的归档数量。
- `/check`：执行配置自检，并通过 Telegram 返回结果。
- `/start`、`/help`：返回命令说明。

定时任务由 `schedule` 管理，每天 03:00 执行一次，等价于自动触发增量抓取。

## GitHub 同步逻辑

`sync_to_github()` 在抓取新增内容后执行：

1. 设置全局 Git 用户：`bot@github.com` / `ZhihuBot`。
2. 在 `GITHUB_REPO_PATH` 下执行 `git add .`。
3. 如果 `git status --porcelain` 有变更，则 commit。
4. commit message 使用 `Auto sync YYYY-MM-DD HH:MM`。
5. 如果配置了 `GITHUB_TOKEN`，使用 `https://x-access-token:<token>@github.com/<repo>.git` 推送到 `HEAD:main`。
6. 如果没有 token，则直接执行 `git push`。

注意：同步目标默认假设归档仓库主分支是 `main`。

## 数据和去重

去重数据库只有一张 `articles` 表，当前主键是清理后的文件名，也就是“动态时间 + 标题”。这能避免重复抓取主页上已经归档的动态。

已知边界：

- 如果同一问题下不同回答在主页显示为同一分钟，且标题完全一致，理论上可能被误判为已抓取。
- 代码里已经能提取 `answer_id`，未来如果需要更稳，可以把去重键升级为优先使用 `answer_id`，无法获取时再退回“时间 + 标题”。
- 评论只抓第一页 root comments，不递归楼中楼。
- 页面选择器依赖知乎当前 DOM 结构，知乎改版时最可能先影响 `.List-item`、`.ActivityItem-meta`、`.ContentItem-title`、`.RichContent-inner`、`.RichText` 等选择器。

## 本地调试

安装依赖：

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

生成知乎登录态：

```bash
python init_login.py
```

只调试第一条动态的回答正文和评论，不写数据库、不保存 Markdown、不推送 GitHub：

```bash
python zhihu_scraper.py --debug-comments
```

正常抓取指定数量的新动态：

```bash
python zhihu_scraper.py --limit 5
```

启动完整 Telegram 服务：

```bash
python main_bot.py
```

## 部署和维护

生产启动：

```bash
docker compose up -d --build
docker logs --tail 200 zhihu_bot
```

常用检查：

```bash
docker exec -it zhihu_bot env | grep -E "ARCHIVE_ROOT_DIR|GITHUB_REPO_PATH|ZH_DB_FILE"
docker exec -it zhihu_bot git -C /app/save_zhihu_activity status --short --branch
docker exec -it zhihu_bot test -f /app/state.json && echo "state.json OK"
```

迁移到新 VPS 时重点备份：

```text
/root/savezhihu/.env
/root/savezhihu/state.json
/root/zhihu_data/zhihu_articles.db
```

Markdown 归档数据可以从 GitHub 重新 clone。

## 开发注意事项

- 这个项目没有测试套件，修改爬虫逻辑后至少运行 `python zhihu_scraper.py --debug-comments` 做冒烟验证。
- `main_bot.py` 导入时会执行启动前自检并初始化 Telegram Bot；单元级调用其中函数时要注意环境变量和挂载路径。
- `zhihu_scraper.py` 覆盖了内置 `print()`，强制 flush，并处理部分编码错误，这是为了 Docker 日志实时输出。
- 抓取逻辑会真实访问知乎，依赖有效 `state.json`，也依赖网络和知乎风控状态。
- 图片下载失败会被忽略并继续处理正文，不会中断整篇文章归档。
- Git 同步失败不会回滚已保存的 Markdown 和数据库记录，Telegram 会提示“文件已保存但同步失败”。
- 当前仓库根目录可能包含真实运行数据文件，改代码时不要误提交 `.env`、`state.json` 或 `zhihu_articles.db`。
