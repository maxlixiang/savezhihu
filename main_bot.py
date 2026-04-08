import telebot
import schedule
import time
import threading
from zhihu_scraper import run_zhihu_scraper

# ====================== 【配置区】 ======================
TG_BOT_TOKEN = "你的_TELEGRAM_BOT_TOKEN"
TG_CHAT_ID = "你的_CHAT_ID"
LIMIT_PER_RUN = 20
# =======================================================

bot = telebot.TeleBot(TG_BOT_TOKEN)

def execute_scrape_task(is_manual=False):
    """执行抓取任务并发送 TG 报告"""
    trigger_type = "手动触发 (/latest)" if is_manual else "凌晨定时增量"
    bot.send_message(TG_CHAT_ID, f"🔄 开始执行知乎抓取任务 ({trigger_type})... 请稍候。")
    
    try:
        new_articles = run_zhihu_scraper(limit=LIMIT_PER_RUN)
        
        if not new_articles:
            msg = f"✅ 抓取完成 ({trigger_type})！\n目前主页没有发现新的动态。"
        elif "[报错]" in new_articles[0]:
            msg = f"❌ 抓取失败！\n原因：{new_articles[0]}"
        else:
            msg = f"🎉 抓取成功 ({trigger_type})！新增了 {len(new_articles)} 篇内容：\n\n"
            for idx, title in enumerate(new_articles, 1):
                msg += f"{idx}. {title}\n"
        
        bot.send_message(TG_CHAT_ID, msg)
    except Exception as e:
        bot.send_message(TG_CHAT_ID, f"⚠️ 抓取过程中发生崩溃：\n{str(e)}")

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