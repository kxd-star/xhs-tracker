import os
import json
import asyncio
from playwright.async_api import async_playwright, TimeoutError

TARGET_URL = "https://www.xiaohongshu.com/user/profile/600982ae0000000001000ee4" # 换成您要抓的主页
OUTPUT_PATH = "xhs-feed.json"

async def main():
    cookie_str = os.environ.get("XHS_COOKIE", "")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        # 塞入您的通行证
        if cookie_str:
            cookies = []
            for item in cookie_str.split(';'):
                if '=' in item:
                    name, value = item.strip().split('=', 1)
                    cookies.append({
                        "name": name, "value": value,
                        "domain": ".xiaohongshu.com", "path": "/"
                    })
            await context.add_cookies(cookies)
            print("✅ 成功装载您的专属通行证 (Cookie)！")

        page = await context.new_page()
        print(f"🚀 正在空降目标主页：{TARGET_URL}")
        
        try:
            # 访问页面并耐心等待它加载完毕（等网络安静下来）
            await page.goto(TARGET_URL, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(5) # 强行多等5秒，防止它转圈圈
            
            # 暴力往下滚3次，逼它把笔记刷出来
            for i in range(3):
                await page.evaluate("window.scrollBy(0, 1000)")
                await asyncio.sleep(2)
                print(f"往下滚了 {i+1} 圈...")
            
            # 使用最新的“放大镜”找笔记（找所有的 a 标签里带 href 包含 /explore/ 的）
            print("🔍 掏出放大镜开始找笔记...")
            note_elements = await page.locator("a[href*='/explore/']").all()
            
            if not note_elements:
                print("❌ 完犊子，放大镜找了一圈，一条笔记都没看见。")
                await page.screenshot(path="debug_screenshot.png")
                print("📸 案发现场照片已拍下，请查收 debug_screenshot.png")
                return
                
            notes = []
            for el in note_elements[:10]: # 只拿最新的 10 条
                url = "https://www.xiaohongshu.com" + await el.get_attribute("href")
                # 尝试找标题，找不到就拉倒
                title_el = await el.locator("span").first
                title = await title_el.text_content() if title_el else "无标题笔记"
                
                notes.append({
                    "title": title.strip(),
                    "url": url
                })
                
            print(f"🎉 卧槽！抓到了 {len(notes)} 条新鲜出炉的笔记！")
            
            # 把战利品存进 json
            with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
                json.dump({"status": "success", "notes": notes}, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            print(f"💥 抓取过程中翻车了：{e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
