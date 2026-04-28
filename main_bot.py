import os
import telebot
import schedule
import time
import threading
import subprocess # 🌟 新增：用于执行终端命令
from dotenv import load_dotenv
from zhihu_scraper import run_zhihu_scraper

load_dotenv()

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
LIMIT_PER_RUN = 20

if not TG_BOT_TOKEN or not TG_CHAT_ID:
    raise ValueError("❌ 环境变量中缺失 TG_BOT_TOKEN 或 TG_CHAT_ID！")

bot = telebot.TeleBot(TG_BOT_TOKEN)

def sync_to_github():
    """🌟 新增：自动提交并推送到 GitHub"""
    repo_path = "save_zhihu_activity"
    try:
        subprocess.run(["git", "config", "--global", "user.email", "bot@github.com"], check=True)
        subprocess.run(["git", "config", "--global", "user.name", "ZhihuBot"], check=True)
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
        
        status = subprocess.run(["git", "status", "--porcelain"], cwd=repo_path, capture_output=True, text=True)
        if status.stdout.strip(): # 有新文件才提交
            commit_msg = f"🤖 Auto sync {time.strftime('%Y-%m-%d %H:%M')}"
            subprocess.run(["git", "commit", "-m", commit_msg], cwd=repo_path, check=True)
            subprocess.run(["git", "push"], cwd=repo_path, check=True)
            return True
        return False
    except Exception as e:
        print(f"Git Sync 失败: {e}")
        return False

def execute_scrape_task(is_manual=False):
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
        elif "[报错]" in new_articles[0]:
            msg = f"❌ 抓取失败！\n原因：{new_articles[0]}"
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
            else:
                msg += "\n\n⚠️ 文件已保存，但同步 GitHub 失败，请检查容器日志。"
                
        bot.send_message(TG_CHAT_ID, msg)  # 🌟 核心修复：彻底删掉 parse_mode 参数！
    except Exception as e:
        bot.send_message(TG_CHAT_ID, f"⚠️ 抓取过程中发生崩溃：\n{str(e)}")

# ... [下面的命令监听和 schedule 逻辑保持不变] ...
# --- Telegram 命令监听 ---
@bot.message_handler(commands=['latest'])
def handle_latest(message):
    # 为避免阻塞机器人主线程，开一个新线程去跑爬虫
    threading.Thread(target=execute_scrape_task, args=(True,)).start()

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "你好！我是知乎动态监控机器人。\n发送 /latest 立即执行一次增量抓取。")

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
