import os
import time
import re
import requests
import random
import sqlite3
import builtins
import html
import argparse
import sys
from urllib.parse import quote
from playwright.sync_api import sync_playwright

try:
    from markdownify import markdownify as md
except ModuleNotFoundError:
    md = None

# 🌟 强制刷新所有 print 输出，防止 Docker 吞弃日志
def print(*args, **kwargs):
    kwargs['flush'] = True
    try:
        builtins.print(*args, **kwargs)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_args = [
            str(arg).encode(encoding, errors="replace").decode(encoding)
            for arg in args
        ]
        builtins.print(*safe_args, **kwargs)

USER_ID = "li-xiang-57-76"
AUTHOR_NAME = "Juan"
DB_FILE = os.getenv("ZH_DB_FILE", "zhihu_articles.db")

ARCHIVE_ROOT_DIR = os.getenv("ARCHIVE_ROOT_DIR", "save_zhihu_activity")

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

def get_save_dir_from_time_str(time_str: str) -> str:
    match = re.match(r"\[(\d{4})-(\d{2})-\d{2}_\d{2}-\d{2}\]", time_str)
    if match:
        year, month = match.groups()
    else:
        year, month = time.strftime("%Y"), time.strftime("%m")

    save_dir = os.path.join(ARCHIVE_ROOT_DIR, year, month)
    os.makedirs(save_dir, exist_ok=True)
    return save_dir

# 🌟 完全采用你验证过的纯净正则清洗方案
def clean_html_text(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()

def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()

def extract_answer_id_from_item(item):
    hrefs = item.evaluate(
        """
        (node) => Array.from(node.querySelectorAll('a[href]'))
            .map((el) => el.href || el.getAttribute('href') || '')
            .filter(Boolean)
        """
    )

    for href in hrefs:
        match = re.search(r"/question/\d+/answer/(\d+)", href)
        if match:
            answer_id = match.group(1)
            print(f"   ✅ 成功从链接提取 answer_id: {answer_id}")
            return answer_id

    zop_answer_id = item.evaluate(
        """
        (node) => {
            const contentItem = node.querySelector('.ContentItem');
            if (!contentItem) return null;
            const zopStr = contentItem.getAttribute('data-zop');
            if (!zopStr) return null;
            try {
                const zop = JSON.parse(zopStr);
                const type = String(zop.type || '').toLowerCase();
                if (type === 'answer') {
                    return String(zop.itemId || zop.item_id || zop.id || '');
                }
            } catch (e) {}
            return null;
        }
        """
    )
    if zop_answer_id:
        print(f"   ✅ 成功从 data-zop 提取 answer_id: {zop_answer_id}")
        return zop_answer_id

    print(f"   ⏭️ 当前动态未找到回答链接，扫描到链接数: {len(hrefs)}")
    return None

def fetch_first_page_comments_via_api(page, answer_id, limit=15):
    api_url = (
        f"https://www.zhihu.com/api/v4/answers/{answer_id}/root_comments"
        f"?limit={limit}&offset=0&order=normal&status=open"
    )

    response = page.context.request.get(
        api_url,
        headers={
            "accept": "application/json, text/plain, */*",
            "x-requested-with": "fetch",
            "referer": page.url,
        },
    )
    if not response.ok:
        response_text = response.text()[:200]
        raise RuntimeError(f"评论 API 请求失败: HTTP {response.status}, body={response_text}")

    payload = response.json()
    data = payload.get("data")
    if not isinstance(data, list):
        raise RuntimeError(f"评论 API 返回结构异常: keys={list(payload.keys())}")

    comments = []
    for item in data:
        author_info = item.get("author") or {}
        member_info = author_info.get("member") or {}
        author_name = (
            member_info.get("name")
            or author_info.get("name")
            or item.get("author_name")
            or "匿名用户"
        )

        raw_content = item.get("content") or item.get("comment") or item.get("text") or ""
        clean_content = clean_html_text(str(raw_content))
        if clean_content and "已删除" not in clean_content:
            comments.append(
                {
                    "author": normalize_text(str(author_name)),
                    "content": clean_content,
                }
            )

    print(f"   ✅ 评论 API 成功，原始数量 {len(data)}，有效数量 {len(comments)}")
    return comments

def format_comments_markdown(comments):
    if not comments:
        return ""

    lines = ["", "", "---", "### 💬 精选评论 (第一页)", ""]
    for comment in comments:
        content = comment["content"].replace("\n", "\n> ")
        lines.append(f"> **{comment['author']}**：{content}")
        lines.append(">")
    return "\n".join(lines)

def extract_debug_card_text(item):
    data = item.evaluate(
        """
        (node) => {
            const cloned = node.cloneNode(true);
            const removeSelectors = [
                '.ContentItem-actions',
                'footer',
                '.Comments-container',
                '.CommentListV2',
                '[class*="CommentList"]',
                'textarea',
                'input',
                '.CommentEditorV2',
                '.Comments-footer',
            ];
            for (const selector of removeSelectors) {
                cloned.querySelectorAll(selector).forEach((el) => el.remove());
            }

            const pick = (selectors) => {
                for (const selector of selectors) {
                    const element = cloned.querySelector(selector);
                    if (!element) continue;
                    const text = (element.innerText || element.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (text) return text;
                }
                return '';
            };

            return {
                title: pick([
                    'h2 a',
                    'h2',
                    '.ContentItem-title a',
                    '.ContentItem-title',
                    'a[href*="/question/"][href*="/answer/"]',
                ]),
                author: pick([
                    '.AuthorInfo-name',
                    '.AuthorInfo .UserLink-link',
                    '.ContentItem-meta .UserLink-link',
                    '.UserLink-link',
                    'meta[itemprop="name"]',
                    'a[href*="/people/"]',
                ]),
                content: pick([
                    '.RichText.ztext',
                    '.RichContent-inner',
                    '[itemprop="text"]',
                    '.RichText',
                ]),
            };
        }
        """
    )
    return {
        "title": normalize_text(data.get("title", "")) or "未提取到标题",
        "author": normalize_text(data.get("author", "")) or "未提取到作者",
        "content": normalize_text(data.get("content", "")) or "未提取到正文",
    }

def print_debug_full_report(card_text, answer_id, comments):
    print("\n========== Debug 完整抓取结果 ==========")
    print(f"\n标题：{card_text['title']}")
    print(f"作者：{card_text['author']}")
    print(f"answer_id：{answer_id}")
    print("\n## 正文\n")
    print(card_text["content"])
    print("\n## 评论\n")
    if not comments:
        print("未提取到有效评论")
        return

    for index, comment in enumerate(comments, start=1):
        content = normalize_text(comment["content"])
        print(f"### 评论 {index}")
        print(f"作者：{comment['author']}")
        print(content)
        print("")

def print_debug_comment_report(comments):
    if not comments:
        print("   ⚠️ 评论 API 调用成功，但没有返回有效评论。")
        return

    print(f"\n🧪 Debug 评论结果：共 {len(comments)} 条\n")
    for index, comment in enumerate(comments, start=1):
        content = normalize_text(comment["content"])
        print(f"{index}. {comment['author']}：{content[:240]}")

def run_debug_comments():
    print("\n🧪 [Debug] 只测试第一条动态评论，不写数据库、不保存文件、不推 GitHub。")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        if not os.path.exists("state.json"):
            print("❌ 找不到 state.json 凭证！")
            return 1

        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            storage_state="state.json",
            timezone_id="Asia/Shanghai",
        )
        page = context.new_page()

        try:
            profile_url = f"https://www.zhihu.com/people/{USER_ID}/activities"
            print(f"👉 [Debug] 访问知乎主页: {profile_url}")
            page.goto(profile_url, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)

            items = page.locator(".List-item")
            item_count = items.count()
            print(f"👉 [Debug] 当前页面动态卡片数: {item_count}")
            if item_count == 0:
                print("❌ 没有找到 .List-item，可能登录态失效或页面结构变化。")
                return 1

            item = items.first
            try:
                meta_text = item.locator(".ActivityItem-meta").inner_text(timeout=1000).strip()
                print(f"👉 [Debug] 第一条动态 meta: {normalize_text(meta_text)}")
            except Exception:
                print("⚠️ 未能读取第一条动态 meta，继续尝试提取 answer_id。")

            try:
                expand_btn = item.locator('button:has-text("阅读全文"), button:has-text("展开全文")')
                if expand_btn.count() > 0:
                    expand_btn.first.evaluate("node => node.click()")
                    page.wait_for_timeout(1500)
                    print("👉 [Debug] 已尝试展开第一条动态全文。")
            except Exception as e:
                print(f"⚠️ 展开全文失败，继续读取当前可见正文: {str(e)[:120]}")

            card_text = extract_debug_card_text(item)
            answer_id = extract_answer_id_from_item(item)
            if not answer_id:
                print("❌ 第一条动态不是回答，或没有提取到 answer_id。")
                return 1

            print(f"📡 [Debug] 请求评论 API，answer_id={answer_id}")
            comments = fetch_first_page_comments_via_api(page, answer_id, limit=15)
            print_debug_full_report(card_text, answer_id, comments)
            return 0
        except Exception as e:
            print(f"❌ [Debug] 评论测试失败: {str(e)[:500]}")
            return 1
        finally:
            context.close()
            browser.close()

def download_img_and_replace_md_link(md_content, article_title, save_dir):
    img_sub_dir = f"{clean_file_name(article_title)}_图片"
    img_save_path = os.path.join(save_dir, img_sub_dir)
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
    if md is None:
        raise RuntimeError("缺少依赖 markdownify。请先运行: pip install -r requirements.txt")

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
                save_dir = get_save_dir_from_time_str(time_str)

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
                # 🌟 核心重构：融合成功脚本的提取逻辑
                # ==========================================
                comments_md_text = ""
                try:
                    # 与 testzhihu 的成功脚本保持同一条链路：先从链接提取 answer_id，再请求评论 API。
                    target_id = extract_answer_id_from_item(item)
                    if target_id:
                        print(f"   📡 识别为“回答”，提取到 ID [{target_id}]，发起 API 请求...")
                        comments = fetch_first_page_comments_via_api(page, target_id, limit=15)
                        comments_md_text = format_comments_markdown(comments)
                        if not comments_md_text:
                            print("   ⚠️ 接口调用成功，但没有可保存的有效评论。")
                    else:
                        print("   ⏭️ 当前动态非“回答”，跳过评论提取。")
                        
                except Exception as e:
                    print(f"   ⚠️ 评论提取发生异常: {str(e)[:300]}")
                # ==========================================

                # 拼接并下载图片
                final_md = download_img_and_replace_md_link(raw_md, clean_title_str, save_dir)
                final_md += comments_md_text

                md_file_path = os.path.join(save_dir, f"{clean_title_str}.md")
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
    parser = argparse.ArgumentParser(description="知乎动态归档爬虫")
    parser.add_argument(
        "--debug-comments",
        action="store_true",
        help="只测试第一条动态评论，不写数据库、不保存文件、不推 GitHub",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="正常抓取模式下最多处理的新动态数量，默认 5",
    )
    args = parser.parse_args()

    if args.debug_comments:
        raise SystemExit(run_debug_comments())

    print(run_zhihu_scraper(limit=args.limit))
