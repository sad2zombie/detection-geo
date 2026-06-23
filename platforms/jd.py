# -*- coding: utf-8 -*-
"""京东平台搜索模块（店铺搜索，登录版本）"""

import asyncio
from urllib.parse import quote
from typing import Any

from config import JD_PROFILE
from platforms.base import BasePlatform, SearchResult, UserResult
from core.browser_manager import get_browser_manager

MAX_SHOPS = 30


class JdPlatform(BasePlatform):
    platform_key = "jd"
    platform_name = "京东"
    profile_dir = str(JD_PROFILE)

    def __init__(self):
        self._bm = get_browser_manager()
        self._ctx: Any = None
        self._page: Any = None

    async def _ensure_browser(self, headless: bool | None = None) -> None:
        """确保浏览器已启动且可用"""
        browser_ok = False
        if self._ctx is not None:
            try:
                _ = self._ctx.pages
                browser_ok = True
            except Exception:
                browser_ok = False

        need_relaunch = (
            self._ctx is None
            or not browser_ok
            or (headless is not None and self._bm._headless != headless)
        )

        if need_relaunch:
            self._ctx, self._page = await self._bm.ensure_page(
                str(JD_PROFILE), headless=headless
            )
        elif self._page is None:
            if not self._ctx.pages:
                self._page = await self._ctx.new_page()
            else:
                self._page = self._ctx.pages[0]

    async def close(self) -> None:
        self._ctx = None
        self._page = None
        try:
            await self._bm.release()
        except Exception:
            pass
        try:
            await self._bm.shutdown()
        except Exception:
            pass

    async def _inject_save_button(self) -> None:
        await self._page.evaluate("""() => {
            if (document.getElementById('__cloak_save_btn')) return;
            var btn = document.createElement('div');
            btn.id = '__cloak_save_btn';
            btn.textContent = '💾 保存登录';
            btn.style.cssText = 'position:fixed;top:20px;right:20px;z-index:99999;'
                + 'padding:14px 24px;background:linear-gradient(135deg,#ff6b6b,#ee5a24);'
                + 'color:#fff;border-radius:10px;cursor:pointer;font-size:16px;'
                + 'font-weight:bold;box-shadow:0 4px 20px rgba(0,0,0,0.4);'
                + 'transition:transform 0.15s;user-select:none;';
            btn.onmouseover = function(){ this.style.transform='scale(1.05)'; };
            btn.onmouseout = function(){ this.style.transform='scale(1)'; };
            btn.onclick = function(){
                this.textContent = '✅ 已保存!';
                this.style.background = 'linear-gradient(135deg,#34d399,#10b981)';
                window.__cloak_saved = true;
            };
            document.body.appendChild(btn);
            window.__cloak_saved = false;
        }""")

    # ---------- 登录状态检测（轻量：只查 profile 目录是否存在）----------
    async def check_login_status(self) -> dict:
        """检查京东是否已登录。

        约定：profile 目录存在即视为已登录（不再做任何 HTTP/页面验证）。
        """
        from pathlib import Path
        logged = bool(self.profile_dir) and Path(self.profile_dir).exists()
        return {
            "platform": self.platform_key,
            "isLoggedIn": logged,
            "note": "已登录" if logged else f"profile 目录不存在（请先登录）: {self.profile_dir}",
        }

    # ---------- 手动登录 ----------
    async def login(self) -> bool:
        """
        打开有头浏览器，等待用户手动登录后点击保存按钮。
        """
        await self._ensure_browser(headless=False)

        await self._page.goto("https://www.jd.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        await self._inject_save_button()

        print("    [京东登录] 浏览器已打开，请在京东完成登录后点击右上角「💾 保存登录」按钮", flush=True)

        max_wait = 600
        elapsed = 0
        eval_fail_streak = 0
        while elapsed < max_wait:
            await asyncio.sleep(2)
            elapsed += 2
            # 守卫 1：用户手动关掉了浏览器/页面（profile 已落盘，这里直接退出，不要再傻等）
            if self._page is None or self._page.is_closed() or not self._bm.is_alive():
                print("    [京东登录] 检测到浏览器/页面已关闭，结束等待", flush=True)
                await self.close()
                return False
            try:
                saved = await self._page.evaluate("() => window.__cloak_saved || false")
                if saved:
                    await asyncio.sleep(1)
                    print("    [京东登录] Cookie已保存！关闭浏览器…", flush=True)
                    await self.close()
                    return True
                eval_fail_streak = 0
            except Exception as eval_err:
                eval_fail_streak += 1
                # 守卫 2：连续 2 次 evaluate 失败（典型场景：浏览器被关、ctx 死掉），立即退出
                if eval_fail_streak >= 2:
                    print(f"    [京东登录] 浏览器无响应（连续失败 {eval_fail_streak} 次）: {str(eval_err)[:80]}", flush=True)
                    await self.close()
                    return False
                try:
                    await asyncio.sleep(2)
                    await self._inject_save_button()
                except Exception:
                    pass
        await self.close()
        return False

    # ---------- 店铺搜索 ----------
    async def _goto_with_retry(self, url: str, retries: int = 2, timeout: int = 30000) -> bool:
        for attempt in range(retries + 1):
            try:
                await self._page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                return True
            except Exception as goto_err:
                err_str = str(goto_err)
                print(f"    [京东导航] 第 {attempt + 1} 次失败 ({url[:60]}...): {err_str[:120]}", flush=True)
                if attempt < retries:
                    page_ok = False
                    if self._ctx is not None and self._bm.is_alive():
                        try:
                            _ = self._ctx.pages
                            self._page = await self._ctx.new_page()
                            page_ok = True
                        except Exception:
                            page_ok = False
                    if not page_ok:
                        await self._bm.shutdown()
                        await self._ensure_browser()
                    print(f"    [京东导航] 新建 page 完成，准备重试…", flush=True)
                else:
                    print(f"    [京东导航] 重试耗尽，放弃", flush=True)
                    return False
        return False

    async def search(self, keyword: str) -> SearchResult:
        """搜索入口：结果为空则最多重试3次"""
        for attempt in range(3):
            try:
                result = await self._do_search(keyword)
            except Exception as e:
                result = {
                    "brand": keyword,
                    "platform": "jd",
                    "platform_name": "京东",
                    "search_url": "",
                    "total_found": 0,
                    "users": [],
                    "error": str(e),
                }
            if result.get("total_found", 0) > 0:
                if attempt > 0:
                    print(f"    [京东搜索] 第 {attempt + 1} 次尝试成功，获得 {result.get('total_found', 0)} 条数据", flush=True)
                return result
            print(f"    [京东搜索] 第 {attempt + 1} 次结果为空（{result.get('error', '未知')[:60]}），", flush=True, end="")
            if attempt < 2:
                print("重试…", flush=True)
                try:
                    await self._bm.shutdown()
                except Exception:
                    pass
                await self._ensure_browser(headless=False)
            else:
                print("重试耗尽，返回空结果", flush=True)
        return {
            "brand": keyword,
            "platform": "jd",
            "platform_name": "京东",
            "search_url": "",
            "total_found": 0,
            "users": [],
            "error": "重试3次后仍无结果",
        }

    async def _do_search(self, keyword: str) -> SearchResult:
        await self._ensure_browser(headless=False)
        search_url = f"https://search.jd.com/Search?enc=utf-8&keyword={quote(keyword)}&shop=1"

        print(f"    [京东搜索] 正在搜索: {keyword}", flush=True)

        try:
            if not await self._goto_with_retry(search_url):
                return {
                    "brand": keyword,
                    "platform": "jd",
                    "platform_name": "京东",
                    "search_url": search_url,
                    "total_found": 0,
                    "users": [],
                    "error": "导航京东搜索页失败",
                }

            await asyncio.sleep(4)
            print(f"    [京东搜索] 页面加载完成，等待渲染", flush=True)

            # 点击「店铺」tab
            try:
                shop_tab = self._page.locator('[class*="_top-bar-left-tab-item_"]:has-text("店铺")').first
                if await shop_tab.count() > 0:
                    await shop_tab.click()
                    await asyncio.sleep(3)
                    print(f"    [京东搜索] 已点击「店铺」tab，等待列表渲染", flush=True)
            except Exception as tab_err:
                print(f"    [京东搜索] 点击「店铺」tab 失败（忽略）: {tab_err}", flush=True)

            # 提取店铺列表 DOM
            extract_dom = """() => {
                const results = [];
                const seen = new Set();

                // 京东店铺卡片容器：class 包含 _shopItem_ 或 shopItemList
                let cards = document.querySelectorAll('[class*="_shopItem_"], [class*="shopItemList"]');

                // 备选：找所有含 mall.jd.com 店铺链接的父容器
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

                    // 店铺名称：优先找 class 包含 _title_ 里的 <span>
                    const titleSpan = card.querySelector('[class*="_title_"] span, [class*="_title_"]');
                    if (titleSpan) {
                        shopName = titleSpan.textContent.trim();
                    }

                    // 备选：从 logo 链接的 img title 属性获取
                    if (!shopName) {
                        const logoImg = card.querySelector('a[class*="_logo_"] img, [class*="_logo_"] img');
                        if (logoImg) {
                            shopName = logoImg.getAttribute('title') || '';
                            // 去掉【】
                            shopName = shopName.replace(/^【|】$/g, '');
                        }
                    }

                    // 备选：从 <em> 标签
                    if (!shopName) {
                        const em = card.querySelector('em');
                        if (em) shopName = em.textContent.trim();
                    }

                    if (!shopName || shopName.length < 2) continue;

                    // 店铺链接：从 logo <a> 标签的 href 获取
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

                    // 认证类型判断（从店铺名称判断）
                    let verify_type = '未认证';
                    if (shopName.includes('自营')) {
                        verify_type = '京东自营';
                    } else if (shopName.includes('官方旗舰店')) {
                        verify_type = '京东认证';
                    }

                    // 店铺标签：class 包含 _il_ 的 <span> 文字标签
                    let shop_tag = '';
                    const tagEl = card.querySelector('[class*="_il_"] span, [class*="_il_"]');
                    if (tagEl) {
                        shop_tag = tagEl.textContent.trim();
                    }

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

            # 翻页加载：点击「下一页」按钮（pvid 由京东在 URL 中维护）
            all_shops = []
            seen_urls = set()
            max_pages = 10
            prev_page_sig = None
            for page_no in range(1, max_pages + 1):
                if page_no > 1:
                    try:
                        # 找「下一页」按钮：class 包含 _pagination_next_ 的 <div>
                        next_btn = self._page.locator('[class*="_pagination_next_"]').first
                        if await next_btn.count() == 0:
                            print(f"    [京东搜索] 未找到「下一页」按钮，停止翻页", flush=True)
                            break

                        btn_class = await next_btn.get_attribute('class') or ''
                        if 'true' in btn_class.split() or btn_class.endswith(' true'):
                            print(f"    [京东搜索] 「下一页」按钮已禁用，停止翻页", flush=True)
                            break

                        await next_btn.click()
                        await asyncio.sleep(3)
                        print(f"    [京东搜索] 已点击「下一页」，当前第 {page_no} 页", flush=True)
                    except Exception as nav_err:
                        print(f"    [京东搜索] 翻页异常: {nav_err}", flush=True)
                        break
                else:
                    await asyncio.sleep(2)

                try:
                    page_shops = await self._page.evaluate(extract_dom)
                except Exception as extract_err:
                    print(f"    [京东搜索] 第 {page_no} 页提取 DOM 失败: {extract_err}", flush=True)
                    break

                print(f"    [京东搜索] 第 {page_no} 页提取到 {len(page_shops)} 个店铺", flush=True)

                # 页面卡住检测：如果当前页店铺签名与上一页完全相同，说明页面没变化，停止翻页
                current_sig = "|".join(sorted(s.get('profile_url', '') for s in page_shops))
                if prev_page_sig is not None and current_sig == prev_page_sig:
                    print(f"    [京东搜索] 第 {page_no} 页数据与上一页相同，停止翻页", flush=True)
                    break
                prev_page_sig = current_sig

                if not page_shops:
                    print(f"    [京东搜索] 第 {page_no} 页无数据，停止翻页", flush=True)
                    break

                # 去重累加
                for shop in page_shops:
                    url = shop.get('profile_url', '')
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_shops.append(shop)
                        if len(all_shops) >= MAX_SHOPS:
                            break

                if len(all_shops) >= MAX_SHOPS:
                    print(f"    [京东搜索] 已累计 {MAX_SHOPS} 个店铺，停止翻页", flush=True)
                    break

            shops_data = all_shops
            print(f"    [京东搜索] 累计提取到 {len(shops_data)} 个店铺", flush=True)

            for idx, shop in enumerate(shops_data[:MAX_SHOPS]):
                print(f"    [京东搜索] 店铺 {idx + 1}: {shop.get('name', '')} | 认证：{shop.get('verify_type', '')}", flush=True)

            return {
                "brand": keyword,
                "platform": "jd",
                "platform_name": "京东",
                "search_url": search_url,
                "total_found": len(shops_data),
                "users": shops_data[:MAX_SHOPS],
                "error": "",
            }

        except Exception as e:
            return {
                "brand": keyword,
                "platform": "jd",
                "platform_name": "京东",
                "search_url": search_url,
                "total_found": 0,
                "users": [],
                "error": str(e),
            }
