# -*- coding: utf-8 -*-
"""百度平台搜索模块（仅 _do_search 核心逻辑）"""

import asyncio
import random
from urllib.parse import quote

from config import BAIDU_PROFILE
from platforms.base import BasePlatform, SearchResult
from platforms import register_platform


@register_platform
class BaiduPlatform(BasePlatform):
    platform_key = "baidu"
    platform_name = "百度"
    profile_dir = str(BAIDU_PROFILE)

    # 百度无登录态，搜索入口就在 base.search，_do_search 不需要登录守卫

    async def check_login_status(self) -> dict:
        """百度搜索不需要登录。"""
        return {"platform": self.platform_key, "platform_name": self.platform_name, "isLoggedIn": True, "note": "百度搜索无需登录"}

    async def login(self) -> bool:
        """百度搜索不需要登录。"""
        return True

    async def _do_search(self, keyword: str) -> SearchResult:
        await self._ensure_browser(headless=False)
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
                "platform": self.platform_key,
                "platform_name": self.platform_name,
                "search_url": base_url,
                "total_found": len(all_results),
                "users": all_results,
                "error": "",
            }
        except Exception as e:
            return self._err_result(keyword, base_url, str(e))

    def _err_result(self, keyword: str, search_url: str, error: str) -> SearchResult:
        return {
            "brand": keyword,
            "platform": self.platform_key,
            "platform_name": self.platform_name,
            "search_url": search_url,
            "total_found": 0,
            "users": [],
            "error": error,
        }