# -*- coding: utf-8 -*-
"""抖音平台搜索模块（异步版本-鲁棒修复版）"""

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
        """关闭浏览器，释放引用计数"""
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
        self._bm._closed = False
        self._bm._ctx = None

    async def check_login_status(self) -> dict:
        """检查抖音是否已登录（轻量检测）"""
        from pathlib import Path
        logged = bool(self.profile_dir) and Path(self.profile_dir).exists()
        return {
            "platform": self.platform_key,
            "isLoggedIn": logged,
            "note": "已登录" if logged else f"profile 目录不存在（请先登录）: {self.profile_dir}",
        }

    async def _inject_save_button(self) -> None:
        """注入悬浮保存按钮"""
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
        """打开浏览器手动登录"""
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
                if eval_fail_streak >= 2:
                    print(f"    [登录] 浏览器无响应（连续失败 {eval_fail_streak} 次）: {str(eval_err)[:80]}", flush=True)
                    await self.close()
                    return False
                try:
                    await asyncio.sleep(2)
                    await self._inject_save_button()
                except Exception:
                    pass
        await self.close()
        return False

    async def _check_login_by_page(self) -> bool:
        """页面级登录态检测"""
        from pathlib import Path
        return bool(self.profile_dir) and Path(self.profile_dir).exists()

    async def _goto_with_retry(self, url: str, retries: int = 2, timeout: int = 30000) -> bool:
        """带重试的导航"""
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

    # ---------- 搜索（核心修复：不依赖动态类名，文本特征+字段互验）----------
    async def search(self, keyword: str) -> SearchResult:
        await self._ensure_browser(headless=False)
        search_url = f"https://www.douyin.com/search/{quote(keyword)}?type=user"

        try:
            status = await self._check_login_by_page()
            print(f"    [搜索] 登录态检测: {'已登录' if status else '未登录'}", flush=True)

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

            # 关闭登录弹窗
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

            # 滚动加载
            for _ in range(5):
                await self._page.evaluate("window.scrollBy(0, 1000)")
                await asyncio.sleep(1.5)
                current_count = await self._page.evaluate("""() => {
                    return document.querySelectorAll('.search-result-card').length;
                }""")
                if current_count >= 30:
                    break

            # 核心提取逻辑（不依赖动态类名，文本特征定位+字段互验）
            users_data = await self._page.evaluate("""() => {
                const results = [];
                const cards = document.querySelectorAll('.search-result-card');
                const seen = new Set();

                // 辅助：找包含指定文本的最内层元素
                function findInnermostEl(root, keyword) {
                    const all = root.querySelectorAll('*');
                    let target = null;
                    for (const el of all) {
                        const text = el.textContent.trim();
                        if (text.includes(keyword)) {
                            if (!target || el.children.length < target.children.length) {
                                target = el;
                            }
                        }
                    }
                    return target;
                }

                for (const card of cards) {
                    // 用户主页链接去重
                    const userLink = card.querySelector('a[href*="/user/"]');
                    const href = userLink ? userLink.href : '';
                    if (!href || href.includes('/user/self') || seen.has(href)) continue;
                    seen.add(href);

                    const fullText = card.textContent.trim();

                    // 1. 认证信息（用稳定的 data-e2e 属性，不会变）
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
                    } else if (fullText.includes('认证徽章')) {
                        verification = 'verified';
                    }

                    // 2. 核心字段：抖音号、获赞、粉丝（先提格式固定的获赞/粉丝，再反推截断抖音号）
                    let douyinId = '';
                    let likeCount = '';
                    let followerCount = '';

                    // 优先通过「抖音号」文本定位信息行，提取三个字段
                    const idTextEl = findInnermostEl(card, '抖音号:');
                    if (idTextEl) {
                        // 向上找到信息行容器
                        let row = idTextEl;
                        while (row.parentElement && row.parentElement.children.length < 3) {
                            row = row.parentElement;
                        }
                        const infoRow = row.parentElement || row;
                        // 过滤掉分隔符、空元素
                        const items = Array.from(infoRow.children).filter(child => {
                            const t = child.textContent.trim();
                            return t.length > 0 && t !== '·' && t !== '|';
                        });
                        if (items.length >= 1) {
                            douyinId = items[0].textContent.replace('抖音号:', '').trim();
                        }
                        if (items.length >= 2) {
                            likeCount = items[1].textContent.replace('获赞', '').trim();
                        }
                        if (items.length >= 3) {
                            followerCount = items[2].textContent.replace('粉丝', '').trim();
                        }
                    }

                    // 兜底正则：先提取格式固定的获赞、粉丝数
                    const likeMatch = fullText.match(/([\\d.]+万?)\\s*获赞/);
                    if (!likeCount && likeMatch) likeCount = likeMatch[1];

                    const followerMatch = fullText.match(/([\\d.]+万?)\\s*粉丝/);
                    if (!followerCount && followerMatch) followerCount = followerMatch[1];

                    // 抖音号兜底 + 粘连截断（用已提取的获赞数反推截断）
                    if (!douyinId) {
                        const idMatch = fullText.match(/抖音号:\\s*(\\S+)/);
                        if (idMatch) {
                            let rawId = idMatch[1];
                            // 关键修复：如果抖音号末尾粘连了获赞数，直接截断
                            if (likeCount) {
                                const likeNum = likeCount.replace('万', '');
                                if (rawId.endsWith(likeNum)) {
                                    rawId = rawId.slice(0, -likeNum.length);
                                }
                            }
                            douyinId = rawId.trim();
                        }
                    }

                    // 3. 账号昵称
                    let name = '';
                    // 优先从认证徽章上方找标题
                    if (badgeEl) {
                        let titleBox = badgeEl.parentElement.previousElementSibling;
                        if (titleBox) name = titleBox.textContent.trim();
                    }
                    // 兜底：找第一个p标签
                    if (!name) {
                        const firstP = card.querySelector('p');
                        if (firstP) name = firstP.textContent.trim();
                    }
                    // 终极兜底：从文本开头截取到抖音号之前
                    if (!name || name.length > 50) {
                        const endIdx = fullText.indexOf('抖音号:');
                        if (endIdx > 0 && endIdx < 100) {
                            name = fullText.substring(0, endIdx).trim();
                            // 去掉认证徽章等后缀
                            ['认证徽章', '关注', '店铺账号'].forEach(tag => {
                                const idx = name.indexOf(tag);
                                if (idx > 0) name = name.substring(0, idx).trim();
                            });
                        }
                    }

                    // 4. 简介
                    let description = '';
                    const allP = card.querySelectorAll('p');
                    if (allP.length >= 2) {
                        const lastP = allP[allP.length - 1];
                        const descText = lastP.textContent.trim();
                        if (descText !== name && descText.length > 10) {
                            description = descText;
                        }
                    }
                    // 兜底：粉丝数后面的长文本
                    if (!description) {
                        const fanIdx = fullText.indexOf('粉丝');
                        if (fanIdx > -1) {
                            description = fullText.substring(fanIdx + 2).trim();
                        }
                    }

                    // 5. 私密账号标记
                    const isPrivate = fullText.includes('私密账号');

                    if (name || href) {
                        results.push({
                            name: name,
                            profile_url: href,
                            verification: verification,
                            verify_type: verifyType,
                            douyin_id: douyinId,
                            follower_count: followerCount,
                            like_count: likeCount,
                            description: description,
                        });
                    }
                }
                return results;
            }""")

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