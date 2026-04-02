import os
import json
import asyncio
from typing import List, Dict, Optional
from playwright.async_api import async_playwright, BrowserContext, Page, TimeoutError

# 目标博主主页 URL，可以通过环境变量或参数传入
TARGET_URL = os.environ.get("XHS_URL", "https://www.xiaohongshu.com/user/profile/600982ae0000000001000ee4")
# 数据输出路径
OUTPUT_PATH = "xhs-feed.json"
# 移动端 User Agent
USER_AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"

async def get_cookies() -> List[Dict]:
    """从环境变量中解析 COOKIE"""
    cookie_str = os.environ.get("XHS_COOKIE")
    if not cookie_str:
        print("警告：未配置 XHS_COOKIE 环境变量，可能会导致抓取失败或数据不全。")
        return []
    
    try:
        # 尝试直接解析 JSON 格式的 cookie
        return json.loads(cookie_str)
    except json.JSONDecodeError:
        # 如果不是 JSON，则按 key=value; 格式解析
        cookies = []
        for item in cookie_str.split(';'):
            if '=' in item:
                name, value = item.strip().split('=', 1)
                cookies.append({'name': name, 'value': value, 'domain': '.xiaohongshu.com', 'path': '/'})
        return cookies

async def extract_notes(page: Page) -> List[Dict]:
    """从页面中解析笔记信息"""
    notes = []
    # 使用多组选择器以增加兼容性
    note_selectors = [
        "section.note-item",   # 常见选择器
        ".note-item-wrapper",  # 备用选择器
        "div.feeds-container > div" # 兜底选择器
    ]

    elements = []
    for selector in note_selectors:
        elements = await page.query_selector_all(selector)
        if elements:
            print(f"成功匹配到笔记元素，使用选择器: {selector}")
            break
    
    if not elements:
        print("错误：无法在页面上找到任何笔记元素。请检查选择器是否已过时。")
        await page.screenshot(path="debug_screenshot.png")
        print("已保存当前页面截图到 debug_screenshot.png 以供调试。")
        return []

    for el in elements:
        try:
            # 提取笔记 ID 和链接
            link_element = await el.query_selector("a.cover.ld.mask") or await el.query_selector("a.note-cover")
            if not link_element: continue
            href = await link_element.get_attribute("href")
            if not href: continue
            note_id = href.split('/')[-1]
            note_url = f"https://www.xiaohongshu.com{href}"

            # 提取封面
            cover_element = await link_element.query_selector("img.cover.ld") or await link_element.query_selector("img.note-cover-image")
            cover = await cover_element.get_attribute("src") if cover_element else ""

            # 提取标题
            title_element = await el.query_selector("span.title") or await el.query_selector("div.note-title")
            title = await title_element.inner_text() if title_element else "（无标题）"

            # 提取发布时间 (发布时间可能不存在或格式多变，做容错处理)
            # 在实际场景中，发布时间通常需要进入笔记详情页才能精确获取，此处简化处理
            publish_time = "" 

            notes.append({
                "note_id": note_id,
                "title": title.strip(),
                "url": note_url,
                "cover": f"https:{cover}" if cover and cover.startswith("//") else cover,
                "publish_time": publish_time, # 详情页才有精确时间
            })
        except Exception as e:
            print(f"解析单个笔记时出错: {e}")
    
    return notes


async def main():
    print("开始抓取小红书博主笔记...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        cookies = await get_cookies()
        context: BrowserContext

        if cookies:
            print("检测到 Cookie，将使用 Cookie 进行抓取。")
            context = await browser.new_context(user_agent=USER_AGENT)
            await context.add_cookies(cookies)
        else:
            print("未检测到 Cookie，将以游客身份抓取。")
            context = await browser.new_context(user_agent=USER_AGENT)
        
        page = await context.new_page()

        try:
            print(f"正在访问目标页面: {TARGET_URL}")
            await page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)

            # 滚动页面以加载更多笔记
            for i in range(3): # 滚动3次
                await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                print(f"第 {i+1} 次滚动页面...")
                await asyncio.sleep(3) # 等待内容加载

            print("页面加载完成，开始解析笔记...")
            new_notes = await extract_notes(page)

            if not new_notes:
                print("未抓取到任何新笔记，程序退出。")
                await browser.close()
                return

            print(f"成功抓取到 {len(new_notes)} 篇笔记。")
            
            # --- 数据去重与合并 ---
            existing_notes = []
            if os.path.exists(OUTPUT_PATH):
                try:
                    with open(OUTPUT_PATH, 'r', encoding='utf-8') as f:
                        existing_notes = json.load(f)
                except (json.JSONDecodeError, FileNotFoundError):
                    print(f"警告：无法读取或解析现有的 {OUTPUT_PATH}，将创建新文件。")
            
            # 合并新旧数据并去重
            all_notes_dict = {note['note_id']: note for note in existing_notes}
            for note in new_notes:
                all_notes_dict[note['note_id']] = note
            
            # 按 note_id (通常与发布时间相关) 进行稳定倒序排序
            # 注意：小红书的 note_id 并不严格按时间递增，最可靠的排序还是详情页的发布时间
            sorted_notes = sorted(all_notes_dict.values(), key=lambda x: x['note_id'], reverse=True)

            print(f"合并与去重后，总共有 {len(sorted_notes)} 篇笔记。")

            # 写入 JSON 文件
            with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
                json.dump(sorted_notes, f, ensure_ascii=False, indent=4)
            
            print(f"数据已成功写入到 {OUTPUT_PATH}")

        except TimeoutError:
            print(f"错误：访问 {TARGET_URL} 超时。请检查网络或目标网站是否可用。")
            await page.screenshot(path="debug_timeout.png")
            print("已保存超时页面截图到 debug_timeout.png。")
            exit(1)
        except Exception as e:
            print(f"发生未知错误: {e}")
            await page.screenshot(path="debug_error.png")
            print("已保存错误页面截图到 debug_error.png。")
            exit(1)
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
