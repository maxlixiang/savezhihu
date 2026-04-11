import os
import time
import re
import requests
import random
import sqlite3
import builtins
from urllib.parse import quote
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from playwright.sync_api import sync_playwright

# 🌟 终极 Debug 技巧：强制刷新所有 print 输出，防止 Docker 吞弃日志
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

def clean_file_name(title):
    illegal_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|', '，', '。', '\n', '\r']
    for char in illegal_chars: title = title.replace(char, "")
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

                # === 展开正文 ===
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
                # 🌟 终极物理点击 + 视觉过滤提取法
                # ==========================================
                comments_md_text = ""
                try:
                    print("   💬 尝试定位【可视的】评论区按钮...")
                    # 1. 使用原生 Playwright 定位器，严格过滤出【肉眼可见】的评论按钮！(避开隐藏的移动端组件陷阱)
                    comment_btn = item.locator('button, [role="button"], a').filter(
                        has_text=re.compile(r"\d+\s*条评论|添加评论")
                    ).filter(visible=True).first

                    if comment_btn.count() > 0:
                        btn_text = comment_btn.inner_text().strip()
                        print(f"   💬 已找到按钮 [{btn_text}]，执行物理点击...")
                        comment_btn.click(force=True)
                        
                        print("   💬 等待评论数据呈现...")
                        try:
                            # 智能等待评论框出现，包含"CommentItem"的元素，或者"还没有评论"的空状态
                            page.wait_for_selector('div[class*="CommentItem"], div:has-text("还没有评论")', timeout=6000)
                            print("   💬 评论DOM已就绪，开始底层提取...")
                        except:
                            print("   ⚠️ 智能等待超时，尝试强行提取当前可见文本...")
                        
                        # 稍微给 0.5 秒让知乎的过渡动画彻底渲染完成
                        time.sleep(0.5)

                        # 2. 用 JS 榨取底层呈现的数据
                        extracted_comments = page.evaluate("""() => {
                            let cmts = [];
                            let nodes = document.querySelectorAll('div[class*="CommentItem"]');
                            nodes.forEach(node => {
                                let author = "匿名用户";
                                let authorEl = node.querySelector('a[class*="UserLink"], div[class*="Author"]');
                                if(authorEl) author = authorEl.innerText.split('\\n')[0].trim();

                                let content = "";
                                let contentEl = node.querySelector('div[class*="CommentContent"], div[class*="RichText"]');
                                if(contentEl) content = contentEl.innerText.trim();

                                if(content && !content.includes('已删除')) {
                                    cmts.push({author: author, content: content});
                                }
                            });
                            return cmts;
                        }""")

                        cmt_count = len(extracted_comments)
                        if cmt_count > 0:
                            comments_md_text += "\n\n---\n### 💬 精选评论 (第一页)\n\n"
                            limit_cmts = min(cmt_count, 15) # 最多拿15条
                            for c in extracted_comments[:limit_cmts]:
                                text_lines = c['content'].replace('\n', '\n> ')
                                comments_md_text += f"> **{c['author']}**：{text_lines}\n>\n"
                            print(f"   🎉 成功提取 {limit_cmts} 条评论！")
                        else:
                            print("   ⚠️ 提取结果为空（可能是0评论，或被知乎安全盾拦截）。")

                        # 3. 物理关闭评论区
                        try:
                            close_btn = page.locator('button[aria-label="关闭"], button:has-text("收起评论")').filter(visible=True).first
                            if close_btn.count() > 0:
                                close_btn.click(force=True)
                                time.sleep(0.5)
                        except: pass
                    else:
                        print("   💬 当前卡片没有找到【可见】的评论按钮。")
                except Exception as e:
                    print(f"   ⚠️ 提取评论发生异常: {str(e)[:60]}")
                # ==========================================

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