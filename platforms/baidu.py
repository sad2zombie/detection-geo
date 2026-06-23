# -*- coding: utf-8 -*-
"""百度平台搜索模块（搜索无需登录，异步版本）"""

import asyncio
import random
from urllib.parse import quote
from typing import Any

from config import BAIDU_PROFILE
from platforms.base import BasePlatform, SearchResult, UserResult
from core.browser_manager import get_browser_manager


class BaiduPlatform(BasePlatform):
    platform_key = "baidu"
    platform_name = "百度"
    profile_dir = str(BAIDU_PROFILE)

    def __init__(self):
        self._bm = get_browser_manager()
        self._ctx: Any = None
        self._page: Any = None

    async def _ensure_browser(self, headless: bool | None = None) -> None:
        """确保浏览器已启动且可用"""
        if self._ctx is None or not self._bm.is_alive() or (headless is not None and headless != self._bm._headless):
            self._ctx, self._page = await self._bm.ensure_page(str(BAIDU_PROFILE), headless=headless)
        elif self._page is None:
            if not self._ctx.pages:
                self._page = await self._ctx.new_page()
            else:
                self._page = self._ctx.pages[0]

    async def close(self) -> None:
        """关闭浏览器，释放引用计数"""
        self._ctx = None
        self._page = None
        try:
            await self._bm.release()
        except Exception:
            pass

    async def check_login_status(self) -> dict:
        """百度搜索不需要登录"""
        return {"isLoggedIn": True, "note": "百度搜索无需登录"}

    async def login(self) -> bool:
        """百度搜索不需要登录"""
        return True

    async def _inject_save_button(self) -> None:
        """百度平台不需要注入按钮"""
        pass

    async def _goto_with_retry(self, url: str, retries: int = 2, timeout: int = 30000) -> bool:
        """导航到 URL，失败时重试（重置浏览器上下文）"""
        for attempt in range(retries + 1):
            try:
                await self._page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                return True
            except Exception as goto_err:
                err_str = str(goto_err)
                print(f"    [导航] 第 {attempt + 1} 次失败 ({url[:60]}...): {err_str[:120]}", flush=True)
                if attempt < retries:
                    self._ctx = None
                    self._page = None
                    try:
                        await self._bm.shutdown()
                    except Exception:
                        pass
                    self._bm._closed = False
                    self._bm._ctx = None
                    await self._ensure_browser()
                    print(f"    [导航] 重置浏览器完成，准备重试…", flush=True)
                else:
                    print(f"    [导航] 重试耗尽，放弃", flush=True)
                    return False
        return False

    async def search(self, keyword: str) -> SearchResult:
        # 测试阶段用有头，方便观察浏览器行为
        await self._ensure_browser(headless=False)
        keyword = keyword
        base_url = f"https://www.baidu.com/s?wd={quote(keyword)}"

        try:
            all_results = []
            pn = 0

            while len(all_results) < 100:
                search_url = f"{base_url}&pn={pn}" if pn > 0 else base_url
                if not await self._goto_with_retry(search_url):
                    break
                await asyncio.sleep(4 if pn == 0 else random.uniform(2, 3))

                page_results = await self._page.evaluate("""() => {
                    const items = [];
                    const containers = document.querySelectorAll('.c-container');
                    containers.forEach(function(c) {
                        const titleEl = c.querySelector('h3 a');
                        if (!titleEl) return;
                        const title = titleEl.textContent.trim();
                        const link = titleEl.href || '';
                        const abstractEl = c.querySelector('[class*="abstract"], [class*="content"], .c-abstract');
                        const abstract = abstractEl ? abstractEl.textContent.trim().substring(0, 200) : '';
                        items.push({
                            name: title,
                            profile_url: link,
                            description: abstract,
                        });
                    });
                    return items;
                }""")

                if not page_results:
                    break

                remaining = 100 - len(all_results)
                all_results.extend(page_results[:remaining])
                if len(all_results) >= 100:
                    break

                pn += 10

            return {
                "brand": keyword,
                "platform": "baidu",
                "platform_name": "百度",
                "search_url": base_url,
                "total_found": len(all_results),
                "users": all_results,
                "error": "",
            }
        except Exception as e:
            return {
                "brand": keyword,
                "platform": "baidu",
                "platform_name": "百度",
                "search_url": base_url,
                "total_found": 0,
                "users": [],
                "error": str(e),
            }
