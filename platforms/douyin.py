# -*- coding: utf-8 -*-
"""抖音平台搜索模块（异步版本）"""

import asyncio
from urllib.parse import quote
from typing import Any

from config import DOUYIN_PROFILE, VERIFICATION_LABELS
from platforms.base import BasePlatform, SearchResult, UserResult
from core.browser_manager import get_browser_manager


class DouyinPlatform(BasePlatform):
    platform_key = "douyin"
    platform_name = "抖音"
    profile_dir = str(DOUYIN_PROFILE)

    def __init__(self):
        self._bm = get_browser_manager()
        self._ctx: Any = None
        self._page: Any = None

    async def _ensure_browser(self, headless: bool | None = None) -> None:
        """确保浏览器已启动且可用

        Args:
            headless: 是否无头。None 沿用默认；登录场景传 False 让用户能看见浏览器。
        """
        # 防御性重置：如果上次检测中途出错（page.goto ERR_ABORTED / ctx 已死），
        # self._ctx 可能指向一个半死不活的 context。先彻底 shutdown bm，让 ensure_page 重新启动。
        if self._ctx is not None and not self._bm.is_alive():
            self._ctx = None
            self._page = None
            try:
                await self._bm.shutdown()
            except Exception:
                pass

        if self._ctx is None or not self._bm.is_alive() or (headless is not None and headless != self._bm._headless):
            self._ctx, self._page = await self._bm.ensure_page(str(DOUYIN_PROFILE), headless=headless)
        elif self._page is None:
            if not self._ctx.pages:
                self._page = await self._ctx.new_page()
            else:
                self._page = self._ctx.pages[0]

    async def close(self) -> None:
        """关闭浏览器，释放引用计数

        关键修复：close() 调用 bm.release() 减引用计数，但只有 refcount 归零时 bm 才会真关。
        检测场景下每次都希望"用完就关"，所以这里在 refcount<=1 时直接 shutdown 兜底，
        避免下一次 ensure_page 拿到一个半死不活的 ctx。
        """
        self._ctx = None
        self._page = None
        try:
            await self._bm.release()
        except Exception:
            pass
        # 兜底：检测场景下没人持有 ctx 了，强制让 bm 释放资源
        try:
            await self._bm.shutdown()
        except Exception:
            pass
        # 重置 bm 的 _closed 标志，让下次 ensure_page 干净启动
        self._bm._closed = False
        self._bm._ctx = None

    # ---------- 登录状态检测（轻量：只查 profile 目录是否存在）----------
    async def check_login_status(self) -> dict:
        """检查抖音是否已登录。

        约定：profile 目录存在即视为已登录（不再做任何 HTTP/页面验证）。
        搜索时如果 cookie 真正失效，再走 ``login()`` 重新登录。
        """
        from pathlib import Path
        logged = bool(self.profile_dir) and Path(self.profile_dir).exists()
        return {
            "platform": self.platform_key,
            "isLoggedIn": logged,
            "note": "已登录" if logged else f"profile 目录不存在（请先登录）: {self.profile_dir}",
        }

    async def _inject_save_button(self) -> None:
        """注入悬浮保存按钮到当前页面"""
        await self._page.evaluate("""() => {
            if (document.getElementById('__cloak_save_btn')) return;
            var btn = document.createElement('div');
            btn.id = '__cloak_save_btn';
            btn.textContent = '💾 保存登录';
            btn.style.cssText = 'position:fixed;top:20px;right:20px;z-index:99999;'
                + 'padding:14px 24px;background:linear-gradient(135deg,#4f8ff7,#764ba2);'
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

    async def login(self) -> bool:
        """打开浏览器，注入悬浮保存按钮，用户登录后点击保存即可

        强制有头模式（headless=False），让用户能看见浏览器并完成手动登录。
        登录完成（用户点保存）→ 关闭浏览器 → 释放 browser 引用。
        """
        # 登录场景必须用有头，否则用户看不到浏览器、点不了保存按钮
        await self._ensure_browser(headless=False)

        await self._page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        await self._inject_save_button()

        print("    [登录] 浏览器已打开，请在抖音完成登录后点击右上角「💾 保存登录」按钮", flush=True)

        max_wait = 600
        elapsed = 0
        eval_fail_streak = 0
        while elapsed < max_wait:
            await asyncio.sleep(2)
            elapsed += 2
            # 守卫 1：用户手动关掉了浏览器/页面（profile 已落盘，这里直接退出，不要再傻等）
            if self._page is None or self._page.is_closed() or not self._bm.is_alive():
                print("    [登录] 检测到浏览器/页面已关闭，结束等待", flush=True)
                await self.close()
                return False
            try:
                saved = await self._page.evaluate("() => window.__cloak_saved || false")
                if saved:
                    await asyncio.sleep(1)
                    print("    [登录] Cookie已保存！关闭浏览器…", flush=True)
                    await self.close()
                    return True
                eval_fail_streak = 0
            except Exception as eval_err:
                eval_fail_streak += 1
                # 守卫 2：连续 2 次 evaluate 失败（典型场景：浏览器被关、ctx 死掉），立即退出
                if eval_fail_streak >= 2:
                    print(f"    [登录] 浏览器无响应（连续失败 {eval_fail_streak} 次）: {str(eval_err)[:80]}", flush=True)
                    await self.close()
                    return False
                try:
                    await asyncio.sleep(2)
                    await self._inject_save_button()
                except Exception:
                    pass
        # 超时也关闭浏览器，避免长时间占用资源
        await self.close()
        return False

    async def _check_login_by_page(self) -> bool:
        """通过页面元素检测登录态（辅助方法，供 search 使用）

        简化版：profile 目录存在即视为已登录，不在搜索流程中再做任何 HTTP/页面验证。
        真实登录态判定由 search 时浏览器自己处理（没登录就会跳登录页/显示空结果）。
        """
        from pathlib import Path
        return bool(self.profile_dir) and Path(self.profile_dir).exists()

    # ---------- 通用：带重试的导航 ----------
    async def _goto_with_retry(self, url: str, retries: int = 2, timeout: int = 30000) -> bool:
        """导航到 URL，失败时重试（重置浏览器上下文）。

        Returns:
            True 表示成功，False 表示最终失败（已打印错误）。
        """
        for attempt in range(retries + 1):
            try:
                await self._page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                return True
            except Exception as goto_err:
                err_str = str(goto_err)
                print(f"    [导航] 第 {attempt + 1} 次失败 ({url[:60]}...): {err_str[:120]}", flush=True)
                if attempt < retries:
                    # 强制重置上下文，重新启动浏览器
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

    # ---------- 搜索 ----------
    async def search(self, keyword: str) -> SearchResult:
        # 测试阶段用有头，方便观察浏览器行为
        await self._ensure_browser(headless=False)
        search_url = f"https://www.douyin.com/search/{quote(keyword)}?type=user"

        try:
            # 确保已登录
            # 复用已有浏览器页面检测登录态（不额外启 headless 浏览器）
            status = await self._check_login_by_page()
            print(f"    [搜索] 登录态检测: {'已登录' if status else '未登录'}", flush=True)

            # 去搜索页
            if not await self._goto_with_retry(search_url):
                return {
                    "brand": keyword,
                    "platform": "douyin",
                    "platform_name": "抖音",
                    "search_url": search_url,
                    "total_found": 0,
                    "users": [],
                    "error": "导航抖音搜索页失败",
                }
            await asyncio.sleep(6)

            # 关闭弹窗
            try:
                await self._page.evaluate("""() => {
                    ['.dy-account-close', '[class*="login"] [class*="close"]',
                     '[class*="modal"] [class*="close"]', '[class*="dialog"] [class*="close"]',
                     '.login-mask-close'].forEach(function(sel) {
                        document.querySelectorAll(sel).forEach(function(el) { el.click(); });
                    });
                    document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}));
                }""")
            except Exception:
                pass
            await asyncio.sleep(2)

            # 滚动加载，凑够30条即停止
            for _ in range(3):
                await self._page.evaluate("window.scrollBy(0, 800)")
                await asyncio.sleep(1.5)
                # 检查是否已达30条
                current_count = await self._page.evaluate("""() => {
                    return document.querySelectorAll('a[href*="/user/"]').length;
                }""")
                if current_count >= 30:
                    break

            # 提取数据
            users_data = await self._page.evaluate("""() => {
                const results = [];
                const userLinks = document.querySelectorAll('a[href*="/user/"]');
                const seen = new Set();

                for (const link of userLinks) {
                    const href = link.href;
                    if (!href || !href.includes('/user/') || seen.has(href)) continue;
                    if (href.includes('/user/self')) continue;
                    seen.add(href);

                    const card = link;
                    const cardText = card.textContent.trim();

                    const nameEl = card.querySelector('p');
                    let name = nameEl ? nameEl.textContent.trim() : '';
                    if (!name || name.length > 50) {
                        const splitMarkers = ['认证徽章', '关注', '抖音号:', '私密账号'];
                        let shortest = cardText;
                        for (const marker of splitMarkers) {
                            const idx = cardText.indexOf(marker);
                            if (idx > 0) {
                                const candidate = cardText.substring(0, idx).trim();
                                if (candidate.length < shortest.length) shortest = candidate;
                            }
                        }
                        name = shortest.length < 50 ? shortest : cardText.substring(0, 30);
                    }

                    const badgeEl = card.querySelector('[data-e2e="badge-role-name"]');
                    let verification = 'none';
                    let verifyType = '';
                    if (badgeEl) {
                        verifyType = badgeEl.textContent.trim();
                        if (verifyType.includes('企业') || verifyType.includes('品牌') || verifyType.includes('店铺')) {
                            verification = 'blue_v';
                        } else if (verifyType.includes('个人') || verifyType.includes('达人') || verifyType.includes('音乐人') || verifyType.includes('演员') || verifyType.includes('医生')) {
                            verification = 'yellow_v';
                        } else if (verifyType.includes('官方') || verifyType.includes('机构') || verifyType.includes('媒体') || verifyType.includes('政府')) {
                            verification = 'official';
                        } else {
                            verification = 'verified';
                        }
                    } else if (cardText.includes('认证徽章')) {
                        verification = 'verified';
                    }

                    const douyinIdMatch = cardText.match(/抖音号:\s*(\S+)/);
                    const douyinId = douyinIdMatch ? douyinIdMatch[1] : '';
                    const followersMatch = cardText.match(/([\d.]+万?)\s*粉丝/);
                    const followerCount = followersMatch ? followersMatch[1] : '';
                    const likesMatch = cardText.match(/([\d.]+万?)\s*获赞/);
                    const likeCount = likesMatch ? likesMatch[1] : '';

                    const pEls = card.querySelectorAll('p');
                    let description = '';
                    if (pEls.length > 1) {
                        const lastP = pEls[pEls.length - 1];
                        const text = lastP.textContent.trim();
                        if (text && text !== '此用户没有填写简介' && text !== name) {
                            description = text;
                        }
                    }

                    const isPrivate = cardText.includes('私密账号');

                    if (name || href) {
                        results.push({
                            name: name, profile_url: href, verification: verification,
                            verify_type: verifyType, douyin_id: douyinId,
                            follower_count: followerCount, like_count: likeCount,
                            description: description, is_private: isPrivate, platform: 'douyin'
                        });
                    }
                }
                return results;
            }""")

            # 二次认证检测
            for u in users_data:
                if u.get("verification") == "unknown":
                    try:
                        detail = await self._page.evaluate("""(profileUrl) => {
                            const links = document.querySelectorAll('a[href*="/user/"]');
                            for (const link of links) {
                                if (link.href === profileUrl) {
                                    const badgeEl = link.querySelector('[data-e2e="badge-role-name"]');
                                    if (badgeEl) {
                                        const roleText = badgeEl.textContent.trim();
                                        if (roleText.includes('企业') || roleText.includes('品牌') || roleText.includes('店铺')) return 'blue_v';
                                        if (roleText.includes('个人') || roleText.includes('达人') || roleText.includes('音乐人') || roleText.includes('演员')) return 'yellow_v';
                                        if (roleText.includes('官方') || roleText.includes('机构') || roleText.includes('媒体')) return 'official';
                                        return 'verified';
                                    }
                                    if (link.textContent.includes('认证徽章')) return 'verified';
                                    return 'none';
                                }
                            }
                            return 'none';
                        }""", u.get("profile_url", ""))
                        u["verification"] = detail
                    except Exception:
                        pass

            return {
                "brand": keyword,
                "platform": "douyin",
                "platform_name": "抖音",
                "search_url": search_url,
                "total_found": min(len(users_data), 30),
                "users": users_data[:30],
                "error": "",
            }

        except Exception as e:
            return {
                "brand": keyword,
                "platform": "douyin",
                "platform_name": "抖音",
                "search_url": search_url,
                "total_found": 0,
                "users": [],
                "error": str(e),
            }
