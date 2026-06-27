# -*- coding: utf-8 -*-
"""淘宝平台搜索模块（仅 _do_search 核心逻辑）"""

import asyncio
from urllib.parse import quote

from config import TAOBAO_PROFILE
from platforms.base import BasePlatform, SearchResult
from platforms import register_platform


@register_platform
class TaobaoPlatform(BasePlatform):
    platform_key = "taobao"
    platform_name = "淘宝"
    profile_dir = str(TAOBAO_PROFILE)
    home_url = "https://www.taobao.com"
    save_btn_color = "linear-gradient(135deg,#ff6b6b,#ee5a24)"

    async def _do_search(self, keyword: str) -> SearchResult:
        await self._ensure_browser(headless=False)
        search_url = f"https://s.taobao.com/search?q={quote(keyword)}&type=shop"

        print(f"    [{self.platform_name}搜索] 正在搜索: {keyword}", flush=True)

        try:
            if not await self._goto_with_retry(search_url):
                return self._err_result(keyword, search_url, "导航淘宝搜索页失败")

            await asyncio.sleep(4)
            print(f"    [{self.platform_name}搜索] URL 跳转完成，等待渲染", flush=True)

            # 点击「店铺」tab 切换视图
            try:
                shop_tab = self._page.locator('div[data-spm="tabbar"] >> text=店铺')
                if await shop_tab.count() > 0:
                    await shop_tab.first.click()
                    await asyncio.sleep(3)
                    print(f"    [{self.platform_name}搜索] 已点击「店铺」tab，等待列表渲染", flush=True)
                else:
                    print(f"    [{self.platform_name}搜索] 未找到「店铺」tab，跳过点击", flush=True)
            except Exception as tab_err:
                print(f"    [{self.platform_name}搜索] 点击「店铺」tab 失败（忽略）: {tab_err}", flush=True)

            # 滚动加载更多店铺
            try:
                for scroll_round in range(10):
                    await self._page.evaluate("window.scrollBy(0, 600)")
                    await asyncio.sleep(1)
                    current_count = await self._page.evaluate(
                        "document.querySelectorAll('[class*=\"shopCard--\"]').length"
                    )
                    print(f"    [{self.platform_name}搜索] 滚动第 {scroll_round + 1} 次，当前店铺数: {current_count}", flush=True)
                    if current_count >= 15:
                        print(f"    [{self.platform_name}搜索] 已加载 {current_count} 个店铺，满足条件，停止滚动", flush=True)
                        break
            except Exception as scroll_err:
                print(f"    [{self.platform_name}搜索] 滚动加载失败（忽略）: {scroll_err}", flush=True)

            shops_data = await self._page.evaluate("""() => {
                const results = [];
                const seen = new Set();

                const cards = document.querySelectorAll('[class*="shopCard--"]');

                for (const card of cards) {
                    const nameEl = card.querySelector('[class*="shopName--"]');
                    if (!nameEl) continue;
                    const shopName = nameEl.textContent.trim();

                    let shopUrl = '';
                    const parentLink = card.closest('a');
                    if (parentLink) {
                        const href = parentLink.href || parentLink.getAttribute('href') || '';
                        if (href && !href.startsWith('javascript') && href.includes('.taobao.com')) {
                            shopUrl = href.split('?')[0];
                        }
                    }
                    if (!shopUrl || seen.has(shopUrl)) continue;
                    seen.add(shopUrl);

                    const fansEl = card.querySelector('[class*="fansCount--"]');
                    const followers = fansEl ? fansEl.textContent.trim().replace(/粉丝$/, '') : '';
                    const verify_type = shopName.includes('官方旗舰店') ? '淘宝认证' : '未认证';

                    results.push({
                        name: shopName,
                        profile_url: shopUrl,
                        follower_count: followers,
                        verify_type: verify_type,
                        platform: 'taobao',
                    });
                }
                return results;
            }""")

            print(f"    [{self.platform_name}搜索] 提取到 {len(shops_data)} 个店铺卡片数据", flush=True)

            for idx, shop in enumerate(shops_data[:15]):
                print(f"    [{self.platform_name}搜索] 店铺 {idx + 1}: {shop.get('name', '')} | 粉丝：{shop.get('follower_count', '')}", flush=True)

            return {
                "brand": keyword,
                "platform": self.platform_key,
                "platform_name": self.platform_name,
                "search_url": search_url,
                "total_found": len(shops_data),
                "users": shops_data[:15],
                "error": "",
            }

        except Exception as e:
            return self._err_result(keyword, search_url, str(e))