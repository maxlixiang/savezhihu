import os
import time
import re
import requests
import random
import sqlite3
from urllib.parse import quote
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from playwright.sync_api import sync_playwright

USER_ID = "li-xiang-57-76"
AUTHOR_NAME = "Juan"
DB_FILE = "zhihu_articles.db"

# 🌟 动态获取当前年份
current_year = time.strftime("%Y")
MAIN_SAVE_DIR = os.path.join("save_zhihu_activity", current_year)

if not os.path.exists(MAIN_SAVE_DIR):
    os.makedirs(MAIN_SAVE_DIR)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.zhihu.com/"
}

# --- 数据库初始化 ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS articles (
            title TEXT PRIMARY KEY,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def is_article_exists(title):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM articles WHERE title = ?", (title,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def save_article_to_db(title):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO articles (title) VALUES (?)", (title,))
    conn.commit()
    conn.close()

def clean_file_name(title):
    illegal_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|', '，', '。', '\n', '\r']
    for char in illegal_chars:
        title = title.replace(char, "")
    return title.strip()[:60]

def download_img_and_replace_md_link(md_content, article_title):
    img_sub_dir = f"{clean_file_name(article_title)}_图片"
    img_save_path = os.path.join(MAIN_SAVE_DIR, img_sub_dir)
    img_pattern = re.compile(r"!\[(.*?)\]\((https?://.*?)\)")
    all_img = img_pattern.findall(md_content)
    if not all_img: return md_content
    if not os.path.exists(img_save_path): os.makedirs(img_save_path)

    for img_desc, img_url in all_img:
        try:
            img_suffix = img_url.split(".")[-1].lower()
            if img_suffix not in ["jpg", "png", "gif", "webp", "jpeg"]: img_suffix = "jpg"
            img_name = f"{clean_file_name(img_desc)[:10]}_{int(time.time()*1000)}.{img_suffix}"
            img_file_path = os.path.join(img_save_path, img_name)

            if not os.path.exists(img_file_path):
                time.sleep(random.uniform(0.1, 0.4)) 
                img_response = requests.get(img_url, headers=headers, timeout=10)
                img_response.raise_for_status()
                with open(img_file_path, "wb") as f: f.write(img_response.content)

            safe_rel_path = quote(f"{img_sub_dir}/{img_name}")
            md_content = md_content.replace(img_url, safe_rel_path)
        except Exception: continue
    return md_content


def run_zhihu_scraper(limit=20, progress_callback=None): 
    init_db()
    newly_scraped_titles = []
    collected_count = 0

    print("\n🚀 [Scraper] 正在启动无头浏览器...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) 
        
        if not os.path.exists("state.json"):
            print("❌ 找不到 state.json，请先运行 init_login.py 并将文件放入同目录！")
            return ["[报错] 缺失 state.json 登录凭证"]
            
        context = browser.new_context(
            viewport={'width': 1366, 'height': 768},
            storage_state="state.json",
            timezone_id="Asia/Shanghai" 
        )
        page = context.new_page()

        print(f"👉 [Scraper] 带着登录状态访问主页...")
        try:
            page.goto(f"https://www.zhihu.com/people/{USER_ID}/activities", wait_until="domcontentloaded")
        except:
            time.sleep(3) 
            page.goto(f"https://www.zhihu.com/people/{USER_ID}/activities", wait_until="domcontentloaded")

        time.sleep(4)
        consecutive_exists_count = 0 

        while collected_count < limit:
            items = page.locator('.List-item')
            current_count = items.count()
            found_new_in_this_loop = False

            for i in range(current_count):
                if collected_count >= limit: break
                item = items.nth(i)

                try:
                    meta_el = item.locator('.ActivityItem-meta')
                    if meta_el.count() == 0: continue
                    meta_text = meta_el.inner_text(timeout=500).strip()
                    action_text_el = item.locator('.ActivityItem-metaTitle')
                    action_text = action_text_el.inner_text().strip() if action_text_el.count() > 0 else meta_text
                except: continue

                if not any(kw in action_text for kw in ["赞同", "发布", "发表"]): continue

                try:
                    time_match = re.search(r"(\d{4}-\d{2}-\d{2})\s(\d{2}:\d{2})", meta_text)
                    if time_match:
                        time_str = f"[{time_match.group(1)}_{time_match.group(2).replace(':', '-')}]"
                    else:
                        time_str = f"[{int(time.time())}]"
                except: time_str = f"[{int(time.time())}]"

                is_pin = "想法" in action_text
                if is_pin:
                    try:
                        author_el = item.locator('.AuthorInfo-name').first
                        author_name = author_el.inner_text().strip().split('\n')[0].strip() if author_el.count() > 0 else "未知作者"
                        if not author_name: author_name = "未知作者"
                    except: author_name = "未知作者"
                    title = f"{author_name}_想法"
                else:
                    try:
                        title_el = item.locator('.ContentItem-title')
                        title = title_el.inner_text().strip() if title_el.count() > 0 else "无标题内容"
                    except: title = "无标题内容"

                clean_title_str = clean_file_name(f"{time_str} {title}")

                if is_article_exists(clean_title_str):
                    consecutive_exists_count += 1
                    if consecutive_exists_count > 10:
                        print("🛑 [Scraper] 连续遇到 10 篇老文章，增量抓取完成，提前结束！")
                        browser.close()
                        return newly_scraped_titles
                    continue
                else:
                    consecutive_exists_count = 0 
                    found_new_in_this_loop = True

                print(f"\n[Scraper] 正在处理新动态：{clean_title_str}")
                
                if progress_callback:
                    progress_callback(collected_count + 1, limit, clean_title_str)

                item.scroll_into_view_if_needed()
                time.sleep(random.uniform(0.5, 1.2))

                # === 展开正文 ===
                expand_btn = item.locator('button:has-text("阅读全文"), button:has-text("展开全文"), a:has-text("阅读全文")')
                if expand_btn.count() > 0:
                    try:
                        expand_btn.first.click(force=True)
                        time.sleep(random.uniform(1.5, 2.5)) 
                    except: pass

                # 提取正文 Markdown
                try:
                    content_box = item.locator('.RichContent-inner, .RichText').first
                    raw_md = "\n".join([line for line in md(content_box.inner_html(), heading_style="ATX").split("\n") if line.strip()])
                except Exception as e:
                    raw_md = f"【⚠️ 正文提取失败】{str(e)[:40]}"

                # ==========================================
                # 🌟 新增核心功能：自动展开并抓取评论区
                # ==========================================
                comments_md_text = ""
                try:
                    # 寻找“评论”按钮
                    comment_btn = item.locator('button:has-text("评论")').first
                    if comment_btn.count() > 0:
                        print("   💬 发现评论区，正在尝试展开...")
                        comment_btn.click(force=True)
                        time.sleep(random.uniform(2.0, 3.5)) # 给网络一点时间加载评论

                        # 定位所有的评论容器（知乎评论类名通常是 CommentItemV2 或 CommentItem）
                        comment_items = item.locator('.CommentItemV2, .CommentItem')
                        cmt_count = comment_items.count()
                        
                        if cmt_count > 0:
                            comments_md_text += "\n\n---\n### 💬 精选评论 (第一页)\n\n"
                            for c_idx in range(cmt_count):
                                cmt_node = comment_items.nth(c_idx)
                                try:
                                    # 提取评论作者
                                    c_author_node = cmt_node.locator('.UserLink-link, .CommentItemV2-metaAuthor').first
                                    c_author = c_author_node.inner_text().strip() if c_author_node.count() > 0 else "匿名用户"
                                    
                                    # 提取评论内容
                                    c_content_node = cmt_node.locator('.RichText, .CommentContent').first
                                    c_content = c_content_node.inner_text().strip() if c_content_node.count() > 0 else ""
                                    
                                    if c_content:
                                        # 替换换行符，确保 Markdown 引用块排版不乱
                                        c_content = c_content.replace('\n', '\n> ')
                                        comments_md_text += f"> **{c_author}**：{c_content}\n>\n"
                                except Exception:
                                    continue
                            print(f"   ✅ 成功提取 {cmt_count} 条评论！")
                except Exception as e:
                    print(f"   ⚠️ 提取评论失败: {str(e)[:40]}")
                # ==========================================

                # 处理图片
                final_md = download_img_and_replace_md_link(raw_md, clean_title_str)
                
                # 拼接正文和评论
                final_md += comments_md_text

                # 保存文件
                md_file_path = os.path.join(MAIN_SAVE_DIR, f"{clean_title_str}.md")
                with open(md_file_path, "w", encoding="utf-8") as f:
                    f.write(f"# {title}\n\n---\n\n{final_md}")  

                save_article_to_db(clean_title_str)
                newly_scraped_titles.append(clean_title_str)
                collected_count += 1

            if not found_new_in_this_loop:
                print("⏬ [Scraper] 向下滚动加载...")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(random.uniform(2.5, 4.0))

        browser.close()
    return newly_scraped_titles

if __name__ == "__main__":
    print(run_zhihu_scraper(limit=5))