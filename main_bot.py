import os
import re
import telebot
import schedule
import time
import threading
import subprocess # 🌟 新增：用于执行终端命令
from urllib.parse import quote
from dotenv import load_dotenv
from zhihu_scraper import run_zhihu_scraper

load_dotenv()

START_TIME = time.time()
LAST_SCRAPE_AT = None
LAST_SCRAPE_RESULT = "尚未执行抓取"

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "maxlixiang/save_zhihu_activity")
ARCHIVE_ROOT_DIR = os.getenv("ARCHIVE_ROOT_DIR", "save_zhihu_activity")
GITHUB_REPO_PATH = os.getenv("GITHUB_REPO_PATH", ARCHIVE_ROOT_DIR)
ZH_DB_FILE = os.getenv("ZH_DB_FILE", "zhihu_articles.db")
LIMIT_PER_RUN = 20
DATE_PREFIX_RE = re.compile(r"^\[(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})_\d{2}-\d{2}\]")

if not TG_BOT_TOKEN or not TG_CHAT_ID:
    raise ValueError("❌ 环境变量中缺失 TG_BOT_TOKEN 或 TG_CHAT_ID！")

def mask_secret(value):
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"

def run_git_check(repo_path, args):
    return subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=False,
    )

def format_duration(seconds):
    seconds = max(0, int(seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}天")
    if hours:
        parts.append(f"{hours}小时")
    if minutes:
        parts.append(f"{minutes}分钟")
    if not parts:
        parts.append(f"{seconds}秒")
    return "".join(parts)

def format_file_size(path):
    if not os.path.exists(path):
        return "不存在"

    size = os.path.getsize(path)
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024

def get_git_status_summary(repo_path):
    if not os.path.isdir(repo_path):
        return "目录不存在"
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        return "不是 Git 仓库"

    status = run_git_check(repo_path, ["status", "--porcelain"])
    if status.returncode != 0:
        return f"检查失败: {(status.stderr or status.stdout).strip()[:160]}"

    lines = [line for line in status.stdout.splitlines() if line.strip()]
    if not lines:
        return "干净"
    return f"有 {len(lines)} 项未同步变更"

def build_status_report():
    uptime = format_duration(time.time() - START_TIME)
    last_scrape = LAST_SCRAPE_AT or "尚未执行"
    git_status = get_git_status_summary(GITHUB_REPO_PATH)
    db_size = format_file_size(ZH_DB_FILE)

    return (
        "📊 运行状态\n\n"
        f"容器运行时间：{uptime}\n"
        f"最近一次抓取：{last_scrape}\n"
        f"最近抓取结果：{LAST_SCRAPE_RESULT}\n"
        f"数据仓库路径：{GITHUB_REPO_PATH}\n"
        f"Git 状态：{git_status}\n"
        f"数据库路径：{ZH_DB_FILE}\n"
        f"数据库大小：{db_size}"
    )

def collect_runtime_diagnostics():
    errors = []
    warnings = []
    details = [
        f"ARCHIVE_ROOT_DIR={ARCHIVE_ROOT_DIR}",
        f"GITHUB_REPO_PATH={GITHUB_REPO_PATH}",
        f"ZH_DB_FILE={ZH_DB_FILE}",
        f"GITHUB_REPOSITORY={GITHUB_REPOSITORY}",
        f"GITHUB_TOKEN={mask_secret(GITHUB_TOKEN) if GITHUB_TOKEN else '[未设置]'}",
    ]

    if not os.path.exists("state.json"):
        errors.append("缺少 state.json，知乎登录态不可用。")

    if not os.path.isdir(ARCHIVE_ROOT_DIR):
        errors.append(f"归档目录不存在或不是目录: {ARCHIVE_ROOT_DIR}")

    if not os.path.isdir(GITHUB_REPO_PATH):
        errors.append(f"Git 推送目录不存在或不是目录: {GITHUB_REPO_PATH}")
    elif not os.path.isdir(os.path.join(GITHUB_REPO_PATH, ".git")):
        errors.append(f"Git 推送目录不是 Git 仓库: {GITHUB_REPO_PATH}")
    else:
        status = run_git_check(GITHUB_REPO_PATH, ["status", "--porcelain"])
        if status.returncode != 0:
            errors.append(f"git status 失败: {(status.stderr or status.stdout).strip()}")

        remote = run_git_check(GITHUB_REPO_PATH, ["remote", "get-url", "origin"])
        if remote.returncode != 0:
            errors.append(f"无法读取 Git origin remote: {(remote.stderr or remote.stdout).strip()}")
        else:
            remote_url = remote.stdout.strip()
            details.append(f"Git origin={remote_url.split('@github.com/')[-1] if '@github.com/' in remote_url else remote_url}")
            if not GITHUB_TOKEN and remote_url.startswith("https://github.com/"):
                warnings.append("未设置 GITHUB_TOKEN，且 origin 是普通 HTTPS URL；容器内 git push 可能无法认证。")

    db_parent = os.path.dirname(os.path.abspath(ZH_DB_FILE)) or "."
    if not os.path.isdir(db_parent):
        errors.append(f"数据库目录不存在: {db_parent}")
    elif os.path.exists(ZH_DB_FILE) and not os.access(ZH_DB_FILE, os.W_OK):
        errors.append(f"数据库文件不可写: {ZH_DB_FILE}")
    elif not os.path.exists(ZH_DB_FILE) and not os.access(db_parent, os.W_OK):
        errors.append(f"数据库目录不可写，无法创建数据库: {db_parent}")

    return errors, warnings, details

def validate_runtime_environment():
    """启动前自检，提前暴露迁移和挂载问题。"""
    print("🔎 启动前自检开始...")
    errors, warnings, details = collect_runtime_diagnostics()

    for detail in details:
        print(f"   {detail}")

    for warning in warnings:
        print(f"⚠️ 自检警告: {warning}")

    if errors:
        for error in errors:
            print(f"❌ 自检失败: {error}")
        raise RuntimeError("启动前自检失败，请先修复上面的配置或挂载问题。")

    print("✅ 启动前自检通过。")

def build_check_report():
    errors, warnings, details = collect_runtime_diagnostics()
    lines = ["🧪 配置自检", ""]
    lines.extend(details)
    lines.append("")

    if warnings:
        lines.append("警告：")
        lines.extend(f"- {warning}" for warning in warnings)
        lines.append("")

    if errors:
        lines.append("结果：失败")
        lines.extend(f"- {error}" for error in errors)
    else:
        lines.append("结果：通过")

    return "\n".join(lines)

def iter_archive_markdown_files():
    if not os.path.isdir(ARCHIVE_ROOT_DIR):
        return

    for root, _, files in os.walk(ARCHIVE_ROOT_DIR):
        if f"{os.sep}.git{os.sep}" in f"{root}{os.sep}":
            continue
        for filename in files:
            if filename.endswith(".md"):
                yield os.path.join(root, filename)

def parse_article_date(path):
    match = DATE_PREFIX_RE.match(os.path.basename(path))
    if not match:
        return None
    return match.group("year"), match.group("month"), match.group("day")

def text_bar(value, max_value, width=12):
    if max_value <= 0 or value <= 0:
        return ""
    filled = max(1, round((value / max_value) * width))
    return "█" * filled

def build_stats_report(arg_text=""):
    arg_text = (arg_text or "").strip()
    now = time.localtime()

    if not arg_text:
        mode = "month"
        target_year = f"{now.tm_year:04d}"
        target_month = f"{now.tm_mon:02d}"
        title = f"{target_year}-{target_month} 抓取统计"
    elif re.fullmatch(r"\d{4}-\d{2}", arg_text):
        mode = "month"
        target_year, target_month = arg_text.split("-")
        title = f"{target_year}-{target_month} 抓取统计"
    elif re.fullmatch(r"\d{4}", arg_text):
        mode = "year"
        target_year = arg_text
        target_month = None
        title = f"{target_year} 抓取统计"
    else:
        return "用法：/stats 或 /stats YYYY-MM 或 /stats YYYY"

    buckets = {}
    total = 0
    with_comments = 0
    with_images = 0

    for path in iter_archive_markdown_files() or []:
        parsed = parse_article_date(path)
        if not parsed:
            continue

        year, month, day = parsed
        if year != target_year:
            continue
        if mode == "month" and month != target_month:
            continue

        bucket = day if mode == "month" else month
        buckets[bucket] = buckets.get(bucket, 0) + 1
        total += 1

        try:
            with open(path, "r", encoding="utf-8") as file:
                content = file.read()
            if "精选评论" in content:
                with_comments += 1
        except Exception:
            pass

        image_dir = os.path.splitext(path)[0] + "_图片"
        if os.path.isdir(image_dir):
            with_images += 1

    if not total:
        return f"{title}\n\n没有找到匹配的文章。"

    max_count = max(buckets.values())
    lines = [
        f"📈 {title}",
        "",
        f"总文章数：{total}",
        f"含评论文章数：{with_comments}",
        f"含图片目录文章数：{with_images}",
        "",
    ]

    unit_suffix = "日" if mode == "month" else "月"
    for key in sorted(buckets):
        count = buckets[key]
        lines.append(f"{key}{unit_suffix} | {text_bar(count, max_count)} {count}")

    return "\n".join(lines)

def build_help_text():
    return (
        "🤖 知乎动态监控机器人命令\n\n"
        "/latest - 立即执行一次增量抓取，并同步到 GitHub\n"
        "/status - 查看运行状态、最近抓取、Git 状态和数据库大小\n"
        "/stats - 统计当月每天抓取文章数\n"
        "/stats YYYY-MM - 统计指定月份每天抓取文章数\n"
        "/stats YYYY - 统计指定年份每月抓取文章数\n"
        "/check - 执行配置自检，检查挂载、Git 仓库、数据库和 token\n"
        "/help - 显示这份命令说明"
    )

validate_runtime_environment()

bot = telebot.TeleBot(TG_BOT_TOKEN)

def sync_to_github():
    """🌟 新增：自动提交并推送到 GitHub"""
    repo_path = GITHUB_REPO_PATH
    try:
        subprocess.run(["git", "config", "--global", "user.email", "bot@github.com"], check=True)
        subprocess.run(["git", "config", "--global", "user.name", "ZhihuBot"], check=True)
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
        
        status = subprocess.run(["git", "status", "--porcelain"], cwd=repo_path, capture_output=True, text=True)
        if status.stdout.strip(): # 有新文件才提交
            commit_msg = f"🤖 Auto sync {time.strftime('%Y-%m-%d %H:%M')}"
            subprocess.run(["git", "commit", "-m", commit_msg], cwd=repo_path, check=True)
            if GITHUB_TOKEN:
                safe_token = quote(GITHUB_TOKEN, safe="")
                push_url = f"https://x-access-token:{safe_token}@github.com/{GITHUB_REPOSITORY}.git"
                subprocess.run(["git", "push", push_url, "HEAD:main"], cwd=repo_path, check=True)
            else:
                subprocess.run(["git", "push"], cwd=repo_path, check=True)
            return True
        return False
    except Exception as e:
        print(f"Git Sync 失败: {e}")
        return False

def execute_scrape_task(is_manual=False):
    global LAST_SCRAPE_AT, LAST_SCRAPE_RESULT

    trigger_type = "手动触发 (/latest)" if is_manual else "凌晨定时增量"
    status_msg = bot.send_message(TG_CHAT_ID, f"🔄 启动知乎爬虫 ({trigger_type})...\n\n⏳ 正在打开浏览器加载主页...")
    msg_id = status_msg.message_id
    last_text = ""

    def progress_cb(current, total, current_title):
        nonlocal last_text
        percent = int((current / total) * 10)
        bar = "█" * percent + "░" * (10 - percent)  
        text = f"🔄 抓取中 ({trigger_type})...\n\n📊 进度: [{bar}] {current}/{total}\n📝 正在提取: {current_title}"
        if text != last_text:
            try:
                bot.edit_message_text(text, chat_id=TG_CHAT_ID, message_id=msg_id)
                last_text = text
            except Exception: pass 

    try:
        new_articles = run_zhihu_scraper(limit=LIMIT_PER_RUN, progress_callback=progress_cb)
        
        try: bot.delete_message(TG_CHAT_ID, msg_id)
        except: pass
        
        if not new_articles:
            msg = f"✅ 抓取完成 ({trigger_type})！\n目前主页没有发现新的动态。"
            LAST_SCRAPE_RESULT = "成功，无新动态"
        elif "[报错]" in new_articles[0]:
            msg = f"❌ 抓取失败！\n原因：{new_articles[0]}"
            LAST_SCRAPE_RESULT = f"失败: {new_articles[0]}"
        else:
            msg = f"🎉 抓取成功 ({trigger_type})！新增了 {len(new_articles)} 篇内容：\n\n"
            for idx, title in enumerate(new_articles, 1):
                msg += f"{idx}. {title}\n"
            
            # 🌟 核心：抓取完成后，触发同步 GitHub
            bot.send_message(TG_CHAT_ID, "🔄 正在将新增文章自动推送到 GitHub...")
            is_pushed = sync_to_github()
            if is_pushed:
                # 顺手把这里的 ** 删掉，纯文本下它会直接显示出来
                msg += "\n\n✅ 已成功同步到 GitHub 仓库！" 
                LAST_SCRAPE_RESULT = f"成功，新增 {len(new_articles)} 篇，已同步 GitHub"
            else:
                msg += "\n\n⚠️ 文件已保存，但同步 GitHub 失败，请检查容器日志。"
                LAST_SCRAPE_RESULT = f"成功，新增 {len(new_articles)} 篇，GitHub 同步失败"
                
        LAST_SCRAPE_AT = time.strftime("%Y-%m-%d %H:%M:%S")
        bot.send_message(TG_CHAT_ID, msg)  # 🌟 核心修复：彻底删掉 parse_mode 参数！
    except Exception as e:
        LAST_SCRAPE_AT = time.strftime("%Y-%m-%d %H:%M:%S")
        LAST_SCRAPE_RESULT = f"崩溃: {str(e)[:120]}"
        bot.send_message(TG_CHAT_ID, f"⚠️ 抓取过程中发生崩溃：\n{str(e)}")

# ... [下面的命令监听和 schedule 逻辑保持不变] ...
# --- Telegram 命令监听 ---
@bot.message_handler(commands=['latest'])
def handle_latest(message):
    # 为避免阻塞机器人主线程，开一个新线程去跑爬虫
    threading.Thread(target=execute_scrape_task, args=(True,)).start()

@bot.message_handler(commands=['status'])
def handle_status(message):
    bot.reply_to(message, build_status_report())

@bot.message_handler(commands=['stats'])
def handle_stats(message):
    arg_text = message.text.partition(" ")[2]
    bot.reply_to(message, build_stats_report(arg_text))

@bot.message_handler(commands=['check'])
def handle_check(message):
    bot.reply_to(message, build_check_report())

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, build_help_text())

# --- 定时任务调度 ---
def daily_job():
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 触发凌晨定时任务")
    execute_scrape_task(is_manual=False)

def scheduler_loop():
    # 每天凌晨 3:00 执行
    schedule.every().day.at("03:00").do(daily_job)
    while True:
        schedule.run_pending()
        time.sleep(10)

if __name__ == "__main__":
    print("🤖 Telegram 机器人守护进程已启动...")
    print("⏳ 定时任务已加载 (每天 03:00)")
    
    # 启动后台定时任务线程
    threading.Thread(target=scheduler_loop, daemon=True).start()
    
    # 启动 Telegram 消息轮询
    bot.infinity_polling()
