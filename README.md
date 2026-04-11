📦 Zhihu Activity Archiver (知乎动态自动化归档机器人)
这是一个基于 Playwright 和 Docker 构建的企业级自动化数据流水线工具。它可以全自动监控你的知乎个人动态（赞同、发布、想法），提取高质量的 Markdown 正文及第一页精选评论，并自动推送到指定的 GitHub 仓库进行永久归档。

同时，该服务集成了 Telegram 机器人，支持实时进度监控、手动触发以及每日定时增量抓取。

✨ 核心特性
🤖 深度防反爬：基于 Playwright 无头浏览器和 state.json 持久化凭证，模拟真实人类行为。

📡 API 降维拦截：独创的底层网络数据包拦截技术，无视前端 UI 遮挡与弹窗，精准提取评论区原生 JSON 数据并转化为 Markdown 引用排版。

🗄️ 数据库去重：内置 SQLite (zhihu_articles.db)，精准记录历史抓取轨迹，确保增量抓取绝不重复。

🖼️ 完美 Obsidian 兼容：自动下载网页图片到本地，并使用标准的相对路径和 URL 编码替换，完美适配 Obsidian 知识库展示。

☁️ 全自动 Git 闭环：抓取完成后，自动执行 git add/commit/push，将数据无缝同步至专属数据仓库。

📱 Telegram 监控终端：支持 /latest 命令实时触发，提供带有可视化进度条的动态运行报告。

🐳 现代化 Docker 部署：彻底隔离环境依赖，解决 Linux 时区与中文字体问题，支持断线自动重启（7x24小时守护）。

📂 目录结构
Plaintext
savezhihu/
├── zhihu_scraper.py      # 核心爬虫模块（含 DOM 解析与 API 拦截提取逻辑）
├── main_bot.py           # 主程序入口（Telegram 机器人调度与 Git 自动同步）
├── init_login.py         # 辅助脚本：用于在本地有图形界面的电脑上生成知乎登录凭证
├── Dockerfile            # Docker 镜像构建脚本（基于官方 Playwright 镜像优化）
├── requirements.txt      # Python 依赖清单
├── .gitignore            # Git 忽略配置（保护敏感文件）
├── .env                  # [需手动创建] 环境变量配置（TG 密钥等）
├── state.json            # [需手动生成] 知乎登录 Cookie 持久化状态
└── zhihu_articles.db     # [自动生成/需上传历史库] SQLite 去重数据库
🚀 极速部署指南 (VPS 环境)
1. 准备工作
在开始部署前，请确保你已经准备好以下信息与文件：

一台已安装 Docker 和 Git 的 Linux VPS。

GitHub PAT (Personal Access Token)：需开启 repo 权限。

Telegram Bot Token 和你的 Chat ID。

在本地电脑运行 init_login.py 生成的 state.json 文件。

（可选）包含你历史文章记录的 zhihu_articles.db 文件。

2. 克隆主程序仓库
登录你的 VPS，在 /root 目录下执行：

Bash
cd /root
git clone https://github.com/你的用户名/savezhihu.git
cd savezhihu
3. 配置敏感数据
通过 SFTP 等工具，将你的 state.json 和 zhihu_articles.db 上传至 /root/savezhihu 目录。
然后，在目录下新建 .env 文件，填入以下内容：

代码段
TG_BOT_TOKEN=你的Telegram_Bot_Token
TG_CHAT_ID=你的Telegram_Chat_ID
4. 挂载数据仓库
为了让容器能够自动推送 Markdown 文件，需使用包含 Token 的地址克隆你的目标数据仓库：

Bash
# 请替换 <你的PAT> 和 <你的用户名>
git clone https://<你的PAT>@github.com/<你的用户名>/save_zhihu_activity.git
5. 构建与运行 Docker 容器
Bash
# 1. 构建镜像 (包含 Playwright 内核、中文字区配置与 Git)
docker build -t zhihu-bot-image .

# 2. 启动守护容器
docker run -d --name zhihu_bot \
  --env-file .env \
  -e TZ="Asia/Shanghai" \
  -v "/root/savezhihu/save_zhihu_activity:/app/save_zhihu_activity" \
  -v "/root/savezhihu/zhihu_articles.db:/app/zhihu_articles.db" \
  --restart unless-stopped zhihu-bot-image
🎮 使用方法
部署成功后，打开你的 Telegram 找到对应的机器人：

手动触发：发送命令 /latest。机器人将立即唤醒爬虫，扫描最新动态，你可以在聊天窗口看到实时变动的进度条。

定时任务：程序内部已设定在每天北京时间 03:00 自动执行一次增量抓取和推送，无需任何人工干预。

🛠️ 常见维护
查看运行日志：

Bash
docker logs -f zhihu_bot
知乎 Cookie 过期怎么办？
通常几个月后知乎可能会要求重新登录。此时只需在本地重新运行 init_login.py，将生成的新 state.json 覆盖 VPS 上的旧文件，并执行 docker restart zhihu_bot 即可。

⚠️ 免责声明
本工具仅供个人学习与数据备份使用。请合理设置抓取频率（代码默认单次限制 20 篇），避免对知乎服务器造成过大压力。严禁用于任何商业或破坏性用途。