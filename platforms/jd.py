# -*- coding: utf-8 -*-
"""京东平台搜索模块（仅 _do_search 核心逻辑）"""

import asyncio
from urllib.parse import quote

from config import JD_PROFILE
from platforms.base import BasePlatform, SearchResult
from platforms import register_platform


MAX_SHOPS = 10


@register_platform
class JdPlatform(BasePlatform):
    platform_key = "jd"
    platform_name = "京东"
    profile_dir = str(JD_PROFILE)
    home_url = "https://www.jd.com"
    save_btn_color = "linear-gradient(135deg,#ff6b6b,#ee5a24)"

    async def _do_search(self, keyword: str) -> SearchResult:
        await self._ensure_browser(headless=False)
        search_url = f"https://search.jd.com/Search?enc=utf-8&keyword={quote(keyword)}&shop=1"

        print(f"    [{self.platform_name}搜索] 正在搜索: {keyword}", flush=True)

        try:
            if not await self._goto_with_retry(search_url):
                return self._err_result(keyword, search_url, "导航京东搜索页失败")

            await asyncio.sleep(4)
            print(f"    [{self.platform_name}搜索] 页面加载完成，等待渲染", flush=True)

            # 点击「店铺」tab
            try:
                shop_tab = self._page.locator('[class*="_top-bar-left-tab-item_"]:has-text("店铺")').first
                if await shop_tab.count() > 0:
                    await shop_tab.click()
                    await asyncio.sleep(3)
                    print(f"    [{self.platform_name}搜索] 已点击「店铺」tab，等待列表渲染", flush=True)
            except Exception as tab_err:
                print(f"    [{self.platform_name}搜索] 点击「店铺」tab 失败（忽略）: {tab_err}", flush=True)

            extract_dom = """() => {
                const results = [];
                const seen = new Set();

                let cards = document.querySelectorAll('[class*="_shopItem_"], [class*="shopItemList"]');

                if (cards.length === 0) {
                    const allLinks = document.querySelectorAll('a[href*="mall.jd.com"], a[href*="shop.jd.com"]');
                    const parents = new Set();
                    for (const link of allLinks) {
                        let parent = link.closest('[class*="shopItem"]') || link.parentElement;
                        if (parent) parents.add(parent);
                    }
                    cards = Array.from(parents);
                }

                for (const card of cards) {
                    let shopName = '';
                    let shopUrl = '';

                    const titleSpan = card.querySelector('[class*="_title_"] span, [class*="_title_"]');
                    if (titleSpan) shopName = titleSpan.textContent.trim();

                    if (!shopName) {
                        const logoImg = card.querySelector('a[class*="_logo_"] img, [class*="_logo_"] img');
                        if (logoImg) {
                            shopName = logoImg.getAttribute('title') || '';
                            shopName = shopName.replace(/^【|】$/g, '');
                        }
                    }

                    if (!shopName) {
                        const em = card.querySelector('em');
                        if (em) shopName = em.textContent.trim();
                    }

                    if (!shopName || shopName.length < 2) continue;

                    const logoLink = card.querySelector('a[class*="_logo_"], [class*="_logo_"] a');
                    if (logoLink) {
                        const href = logoLink.href || logoLink.getAttribute('href') || '';
                        if (href) {
                            shopUrl = href.split('?')[0];
                            if (!shopUrl.startsWith('http')) shopUrl = 'https://www.jd.com' + shopUrl;
                        }
                    }

                    if (!shopUrl || seen.has(shopUrl)) continue;
                    seen.add(shopUrl);

                    let verify_type = '未认证';
                    if (shopName.includes('自营')) verify_type = '京东自营';
                    else if (shopName.includes('官方旗舰店')) verify_type = '京东认证';

                    let shop_tag = '';
                    const tagEl = card.querySelector('[class*="_il_"] span, [class*="_il_"]');
                    if (tagEl) shop_tag = tagEl.textContent.trim();

                    results.push({
                        name: shopName,
                        profile_url: shopUrl,
                        follower_count: '',
                        verify_type: verify_type,
                        shop_tag: shop_tag,
                        platform: 'jd',
                    });
                }
                return results;
            }"""

            all_shops = []
            seen_urls = set()
            max_pages = 10
            prev_page_sig = None
            for page_no in range(1, max_pages + 1):
                if page_no > 1:
                    try:
                        next_btn = self._page.locator('[class*="_pagination_next_"]').first
                        if await next_btn.count() == 0:
                            print(f"    [{self.platform_name}搜索] 未找到「下一页」按钮，停止翻页", flush=True)
                            break

                        btn_class = await next_btn.get_attribute('class') or ''
                        if 'true' in btn_class.split() or btn_class.endswith(' true'):
                            print(f"    [{self.platform_name}搜索] 「下一页」按钮已禁用，停止翻页", flush=True)
                            break

                        await next_btn.click()
                        await asyncio.sleep(3)
                        print(f"    [{self.platform_name}搜索] 已点击「下一页」，当前第 {page_no} 页", flush=True)
                    except Exception as nav_err:
                        print(f"    [{self.platform_name}搜索] 翻页异常: {nav_err}", flush=True)
                        break
                else:
                    await asyncio.sleep(2)

                try:
                    page_shops = await self._page.evaluate(extract_dom)
                except Exception as extract_err:
                    print(f"    [{self.platform_name}搜索] 第 {page_no} 页提取 DOM 失败: {extract_err}", flush=True)
                    break

                print(f"    [{self.platform_name}搜索] 第 {page_no} 页提取到 {len(page_shops)} 个店铺", flush=True)

                current_sig = "|".join(sorted(s.get('profile_url', '') for s in page_shops))
                if prev_page_sig is not None and current_sig == prev_page_sig:
                    print(f"    [{self.platform_name}搜索] 第 {page_no} 页数据与上一页相同，停止翻页", flush=True)
                    break
                prev_page_sig = current_sig

                if not page_shops:
                    print(f"    [{self.platform_name}搜索] 第 {page_no} 页无数据，停止翻页", flush=True)
                    break

                for shop in page_shops:
                    url = shop.get('profile_url', '')
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_shops.append(shop)
                        if len(all_shops) >= MAX_SHOPS:
                            break

                if len(all_shops) >= MAX_SHOPS:
                    print(f"    [{self.platform_name}搜索] 已累计 {MAX_SHOPS} 个店铺，停止翻页", flush=True)
                    break

            shops_data = all_shops
            print(f"    [{self.platform_name}搜索] 累计提取到 {len(shops_data)} 个店铺", flush=True)

            for idx, shop in enumerate(shops_data[:MAX_SHOPS]):
                print(f"    [{self.platform_name}搜索] 店铺 {idx + 1}: {shop.get('name', '')} | 认证：{shop.get('verify_type', '')}", flush=True)

            return {
                "brand": keyword,
                "platform": self.platform_key,
                "platform_name": self.platform_name,
                "search_url": search_url,
                "total_found": len(shops_data),
                "users": shops_data[:MAX_SHOPS],
                "error": "",
            }

        except Exception as e:
            return self._err_result(keyword, search_url, str(e))