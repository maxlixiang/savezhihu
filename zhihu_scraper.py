import os
import time
import re
import requests
import random
import sqlite3
import builtins
import html
from urllib.parse import quote
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from playwright.sync_api import sync_playwright

# 🌟 强制刷新所有 print 输出，防止 Docker 吞弃日志
def print(*args, **kwargs):
    kwargs['flush'] = True
    builtins.print(*args, **kwargs)

USER_ID = "li-xiang-57-76"
AUTHOR_NAME = "Juan"
DB_FILE = "zhihu_articles.db"

current_year = time.strftime("%Y")
MAIN_SAVE_DIR = os.path.join("save_zhihu_activity", current_year)

if not os.path.exists(MAIN_SAVE_DIR):
    os.makedirs(MAIN_SAVE_DIR)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.zhihu.com/"
}

# --- 数据库操作 ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS articles (title TEXT PRIMARY KEY, scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
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

# --- 文本与图片处理 ---
def clean_file_name(title):
    illegal_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|', '，', '。', '\n', '\r']
    for char in illegal_chars: title = title.replace(char, "")
    return title.strip()[:60]

def clean_html_text(value: str) -> str:
    """清洗评论区的 HTML 标签"""
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    text = BeautifulSoup(text, "html.parser").get_text(separator="")
    return html.unescape(text).strip()

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
        except: continue
    return md_content


def run_zhihu_scraper(limit=20, progress_callback=None): 
    init_db()
    newly_scraped_titles = []
    collected_count = 0

    print("\n🚀 [Scraper] 正在启动无头浏览器...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) 
        if not os.path.exists("state.json"):
            print("❌ 找不到 state.json 凭证！")
            return ["[报错] 缺失 state.json 登录凭证"]
            
        context = browser.new_context(
            viewport={'width': 1366, 'height': 768},
            storage_state="state.json",
            timezone_id="Asia/Shanghai" 
        )
        page = context.new_page()

        print("👉 [Scraper] 访问知乎主页...")
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

                # 提取时间和标题
                try:
                    time_match = re.search(r"(\d{4}-\d{2}-\d{2})\s(\d{2}:\d{2})", meta_text)
                    time_str = f"[{time_match.group(1)}_{time_match.group(2).replace(':', '-')}]" if time_match else f"[{int(time.time())}]"
                except: time_str = f"[{int(time.time())}]"

                is_pin = "想法" in action_text
                if is_pin:
                    try:
                        author_el = item.locator('.AuthorInfo-name').first
                        author_name = author_el.inner_text().strip().split('\n')[0].strip() if author_el.count() > 0 else "未知作者"
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
                        print("🛑 [Scraper] 连续遇到老文章，增量抓取结束。")
                        browser.close()
                        return newly_scraped_titles
                    continue
                
                consecutive_exists_count = 0 
                found_new_in_this_loop = True

                print(f"\n[Scraper] 处理新动态：{clean_title_str}")
                if progress_callback: progress_callback(collected_count + 1, limit, clean_title_str)

                item.scroll_into_view_if_needed()
                time.sleep(random.uniform(0.5, 1.2))

                # === 提取正文 Markdown ===
                expand_btn = item.locator('button:has-text("阅读全文"), button:has-text("展开全文")')
                if expand_btn.count() > 0:
                    try:
                        expand_btn.first.evaluate("node => node.click()")
                        time.sleep(random.uniform(1.5, 2.5)) 
                    except: pass

                try:
                    content_box = item.locator('.RichContent-inner, .RichText').first
                    raw_md = "\n".join([line for line in md(content_box.inner_html(), heading_style="ATX").split("\n") if line.strip()])
                except Exception as e:
                    raw_md = f"【⚠️ 正文提取失败】{str(e)[:40]}"

                # ==========================================
                # 🌟 核心重构（收窄范围）：仅针对“回答”请求 API
                # ==========================================
                comments_md_text = ""
                try:
                    # 1. 解析卡片中的所有链接，专门寻找“回答”的 ID
                    hrefs = item.evaluate("""(node) => Array.from(node.querySelectorAll('a[href]')).map(el => el.href || '')""")
                    
                    target_id = None
                    
                    for href in hrefs:
                        # 仅匹配回答 (Answer)
                        ans_match = re.search(r"/question/\d+/answer/(\d+)", href)
                        if ans_match:
                            target_id = ans_match.group(1)
                            break
                    
                    # 2. 如果成功提取到回答 ID，向知乎官方发起 API 请求
                    if target_id:
                        print(f"   📡 识别为“回答”，提取到 ID [{target_id}]，发起评论 API 请求...")
                        
                        api_url = f"https://www.zhihu.com/api/v4/answers/{target_id}/root_comments?limit=15&offset=0&order=normal&status=open"
                        
                        # 巧妙利用 Playwright 携带当前 Cookie 状态直接发请求
                        api_response = page.context.request.get(
                            api_url,
                            headers={
                                "accept": "application/json",
                                "x-requested-with": "fetch",
                                "referer": page.url,
                            }
                        )
                        
                        if api_response.ok:
                            data = api_response.json().get("data", [])
                            if data:
                                comments_md_text += "\n\n---\n### 💬 精选评论 (第一页)\n\n"
                                added_count = 0
                                
                                for c in data:
                                    # 提取作者
                                    author_info = c.get("author") or {}
                                    member_info = author_info.get("member") or {}
                                    author_name = member_info.get("name") or author_info.get("name") or "匿名用户"
                                    
                                    # 提取评论内容并用正则清洗 HTML 标签
                                    raw_content = c.get("content") or c.get("comment") or c.get("text") or ""
                                    clean_content = clean_html_text(str(raw_content))
                                    
                                    if clean_content and "已删除" not in clean_content:
                                        # 转化为 Markdown 引用语法
                                        clean_content = clean_content.replace('\n', '\n> ')
                                        comments_md_text += f"> **{author_name}**：{clean_content}\n>\n"
                                        added_count += 1
                                        
                                print(f"   🎉 完美解析了 {added_count} 条评论！")
                            else:
                                print("   ⚠️ 接口调用成功，但该回答目前 0 评论。")
                        else:
                            print(f"   ❌ API 请求被拒: HTTP {api_response.status}")
                    else:
                        print("   ⏭️ 当前动态非“回答”（可能是文章或想法），按设定跳过评论提取。")
                        
                except Exception as e:
                    print(f"   ⚠️ 评论提取发生异常: {str(e)[:60]}")
                # ==========================================

                # 拼接并下载图片
                final_md = download_img_and_replace_md_link(raw_md, clean_title_str)
                final_md += comments_md_text

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