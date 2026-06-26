# -*- coding: utf-8 -*-
"""淘宝平台搜索模块（店铺搜索，登录版本）"""

import asyncio
from urllib.parse import quote
from typing import Any

from config import TAOBAO_PROFILE
from platforms.base import BasePlatform, SearchResult, UserResult
from core.browser_manager import get_browser_manager


class TaobaoPlatform(BasePlatform):
    platform_key = "taobao"
    platform_name = "淘宝"
    profile_dir = str(TAOBAO_PROFILE)

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
                str(TAOBAO_PROFILE), headless=headless
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
            btn.textContent = '[SAVE] Save Login';
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
        """检查淘宝是否已登录。

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
        与抖音登录流程完全一致。
        """
        await self._ensure_browser(headless=False)

        await self._page.goto("https://www.taobao.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        await self._inject_save_button()

        print("    [Taobao Login] Browser opened, finish login on Taobao and click [SAVE] in top-right corner", flush=True)

        max_wait = 600
        elapsed = 0
        eval_fail_streak = 0
        while elapsed < max_wait:
            await asyncio.sleep(2)
            elapsed += 2
            # 守卫 1：用户手动关掉了浏览器/页面（profile 已落盘，这里直接退出，不要再傻等）
            if self._page is None or self._page.is_closed() or not self._bm.is_alive():
                print("    [淘宝登录] 检测到浏览器/页面已关闭，结束等待", flush=True)
                await self.close()
                return False
            try:
                saved = await self._page.evaluate("() => window.__cloak_saved || false")
                if saved:
                    await asyncio.sleep(1)
                    print("    [淘宝登录] Cookie已保存！关闭浏览器…", flush=True)
                    await self.close()
                    return True
                eval_fail_streak = 0
            except Exception as eval_err:
                eval_fail_streak += 1
                # 守卫 2：连续 2 次 evaluate 失败（典型场景：浏览器被关、ctx 死掉），立即退出
                if eval_fail_streak >= 2:
                    print(f"    [淘宝登录] 浏览器无响应（连续失败 {eval_fail_streak} 次）: {str(eval_err)[:80]}", flush=True)
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
                print(f"    [淘宝导航] 第 {attempt + 1} 次失败 ({url[:60]}...): {err_str[:120]}", flush=True)
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
                    print(f"    [淘宝导航] 新建 page 完成，准备重试…", flush=True)
                else:
                    print(f"    [淘宝导航] 重试耗尽，放弃", flush=True)
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
                    "platform": "taobao",
                    "platform_name": "淘宝",
                    "search_url": "",
                    "total_found": 0,
                    "users": [],
                    "error": str(e),
                }
            if result.get("total_found", 0) > 0:
                if attempt > 0:
                    print(f"    [淘宝搜索] 第 {attempt + 1} 次尝试成功，获得 {result.get('total_found', 0)} 条数据", flush=True)
                return result
            print(f"    [淘宝搜索] 第 {attempt + 1} 次结果为空（{result.get('error', '未知')[:60]}），", flush=True, end="")
            if attempt < 2:
                print("重试…", flush=True)
                try:
                    await self._bm.shutdown()
                except Exception:
                    pass
                # 清空旧引用，避免 _ensure_browser 误判旧 ctx 还活着
                self._ctx = None
                self._page = None
                await self._ensure_browser(headless=False)
            else:
                print("重试耗尽，返回空结果", flush=True)
        return {
            "brand": keyword,
            "platform": "taobao",
            "platform_name": "淘宝",
            "search_url": "",
            "total_found": 0,
            "users": [],
            "error": "重试3次后仍无结果",
        }

    async def _do_search(self, keyword: str) -> SearchResult:
        await self._ensure_browser(headless=False)
        search_url = f"https://s.taobao.com/search?q={quote(keyword)}&type=shop"

        print(f"    [淘宝搜索] 正在搜索: {keyword}", flush=True)

        try:
            if not await self._goto_with_retry(search_url):
                return {
                    "brand": keyword,
                    "platform": "taobao",
                    "platform_name": "淘宝",
                    "search_url": search_url,
                    "total_found": 0,
                    "users": [],
                    "error": "导航淘宝搜索页失败",
                }

            await asyncio.sleep(4)
            print(f"    [淘宝搜索] URL 跳转完成，等待渲染", flush=True)

            # 点击「店铺」tab 切换视图（data-spm="tabbar" 是稳定属性）
            try:
                shop_tab = self._page.locator('div[data-spm="tabbar"] >> text=店铺')
                if await shop_tab.count() > 0:
                    await shop_tab.first.click()
                    await asyncio.sleep(3)
                    print(f"    [淘宝搜索] 已点击「店铺」tab，等待列表渲染", flush=True)
                else:
                    print(f"    [淘宝搜索] 未找到「店铺」tab，跳过点击", flush=True)
            except Exception as tab_err:
                print(f"    [淘宝搜索] 点击「店铺」tab 失败（忽略）: {tab_err}", flush=True)

            # 滚动加载更多店铺，确保凑够 15 个
            try:
                for scroll_round in range(10):
                    await self._page.evaluate("window.scrollBy(0, 600)")
                    await asyncio.sleep(1)
                    current_count = await self._page.evaluate(
                        "document.querySelectorAll('[class*=\"shopCard--\"]').length"
                    )
                    print(f"    [淘宝搜索] 滚动第 {scroll_round + 1} 次，当前店铺数: {current_count}", flush=True)
                    if current_count >= 15:
                        print(f"    [淘宝搜索] 已加载 {current_count} 个店铺，满足条件，停止滚动", flush=True)
                        break
            except Exception as scroll_err:
                print(f"    [淘宝搜索] 滚动加载失败（忽略）: {scroll_err}", flush=True)

            # 提取店铺列表 DOM（店铺 tab 视图）
            # DOM 结构：<a><div class="shopCard--*"><div class="shopInfoPanel--*"><div class="shopHeader--*">
            #   <div class="shopProfile--*"><div class="shopName--*">店铺名</div>
            #   <div class="fansCount--*">3762万粉丝</div>
            shops_data = await self._page.evaluate("""() => {
                const results = [];
                const seen = new Set();

                // 店铺卡片容器：shopCard 前缀（hash 部分可能变化）
                const cards = document.querySelectorAll('[class*="shopCard--"]');

                for (const card of cards) {
                    // 店铺名称
                    const nameEl = card.querySelector('[class*="shopName--"]');
                    if (!nameEl) continue;
                    const shopName = nameEl.textContent.trim();

                    // 店铺链接：从父级 <a> 获取
                    let shopUrl = '';
                    let parentLink = card.closest('a');
                    if (parentLink) {
                        const href = parentLink.href || parentLink.getAttribute('href') || '';
                        if (href && !href.startsWith('javascript') && href.includes('.taobao.com')) {
                            shopUrl = href.split('?')[0];
                        }
                    }
                    if (!shopUrl || seen.has(shopUrl)) continue;
                    seen.add(shopUrl);

                    // 粉丝数
                    const fansEl = card.querySelector('[class*="fansCount--"]');
                    const followers = fansEl ? fansEl.textContent.trim().replace(/粉丝$/, '') : '';

                    // 淘宝认证：「官方旗舰店」为淘宝认证，其余为未认证
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

            print(f"    [淘宝搜索] 提取到 {len(shops_data)} 个店铺卡片数据", flush=True)

            for idx, shop in enumerate(shops_data[:15]):
                print(f"    [淘宝搜索] 店铺 {idx + 1}: {shop.get('name', '')} | 粉丝：{shop.get('follower_count', '')}", flush=True)

            return {
                "brand": keyword,
                "platform": "taobao",
                "platform_name": "淘宝",
                "search_url": search_url,
                "total_found": len(shops_data),
                "users": shops_data[:15],
                "error": "",
            }

        except Exception as e:
            return {
                "brand": keyword,
                "platform": "taobao",
                "platform_name": "淘宝",
                "search_url": search_url,
                "total_found": 0,
                "users": [],
                "error": str(e),
            }
