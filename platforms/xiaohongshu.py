# -*- coding: utf-8 -*-
"""小红书平台搜索模块"""

import asyncio
from typing import Any

from config import XHS_PROFILE
from platforms.base import BasePlatform, SearchResult, UserResult
from core.browser_manager import get_browser_manager


class XiaohongshuPlatform(BasePlatform):
    platform_key = "xiaohongshu"
    platform_name = "小红书"
    profile_dir = str(XHS_PROFILE)

    def __init__(self):
        self._bm = get_browser_manager()
        self._ctx: Any = None
        self._page: Any = None

    async def _ensure_browser(self, headless: bool | None = None) -> None:
        if self._ctx is not None and not self._bm.is_alive():
            self._ctx = None
            self._page = None
            try:
                await self._bm.shutdown()
            except Exception:
                pass

        if self._ctx is None or not self._bm.is_alive() or (headless is not None and headless != self._bm._headless):
            self._ctx, self._page = await self._bm.ensure_page(str(XHS_PROFILE), headless=headless)
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
        self._bm._closed = False
        self._bm._ctx = None

    # ---------- 登录状态检测（HTTP 探测，不开浏览器）----------
    # ---------- 登录状态检测（轻量：只查 profile 目录是否存在）----------
    async def check_login_status(self) -> dict:
        """检查小红书是否已登录。

        约定：profile 目录存在即视为已登录（不再做任何 HTTP/页面验证）。
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
                + 'padding:14px 24px;background:linear-gradient(135deg,#ff6b6b,#ee5a5a);'
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
        """打开浏览器，注入悬浮保存按钮，用户扫码登录后点击保存即可"""
        await self._ensure_browser(headless=False)

        await self._page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        await self._inject_save_button()

        print("    [小红书登录] 浏览器已打开，请在浏览器中用小红书APP扫码登录后点击右上角「💾 保存登录」按钮", flush=True)

        max_wait = 600
        elapsed = 0
        eval_fail_streak = 0
        while elapsed < max_wait:
            await asyncio.sleep(2)
            elapsed += 2
            # 守卫 1：用户手动关掉了浏览器/页面（profile 已落盘，这里直接退出，不要再傻等）
            if self._page is None or self._page.is_closed() or not self._bm.is_alive():
                print("    [小红书登录] 检测到浏览器/页面已关闭，结束等待", flush=True)
                await self.close()
                return False
            try:
                saved = await self._page.evaluate("() => window.__cloak_saved || false", timeout=3000)
                if saved:
                    await asyncio.sleep(1)
                    print("    [小红书登录] Cookie已保存！关闭浏览器…", flush=True)
                    await self.close()
                    return True
                eval_fail_streak = 0
            except Exception as eval_err:
                eval_fail_streak += 1
                # 守卫 2：连续 2 次 evaluate 失败（典型场景：浏览器被关、ctx 死掉），立即退出
                if eval_fail_streak >= 2:
                    print(f"    [小红书登录] 浏览器无响应（连续失败 {eval_fail_streak} 次）: {str(eval_err)[:80]}", flush=True)
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
        """通过页面登录弹窗和header登录按钮检测登录态（辅助方法，供 search 使用）

        简化版：profile 目录存在即视为已登录，不在搜索流程中再做任何 HTTP/页面验证。
        """
        from pathlib import Path
        return bool(self.profile_dir) and Path(self.profile_dir).exists()

    # ---------- 通用：带重试的导航 ----------
    async def _goto_with_retry(self, url: str, retries: int = 2, timeout: int = 30000) -> bool:
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

    # ---------- 搜索 ----------
    async def search(self, keyword: str) -> SearchResult:
        await self._ensure_browser(headless=False)

        try:
            status = await self._check_login_by_page()
            print(f"    [小红书搜索] 登录态检测: {'已登录' if status else '未登录'}", flush=True)

            if not await self._goto_with_retry("https://www.xiaohongshu.com"):
                return {
                    "brand": keyword,
                    "platform": "xiaohongshu",
                    "platform_name": "小红书",
                    "search_url": "https://www.xiaohongshu.com",
                    "total_found": 0,
                    "users": [],
                    "error": "导航小红书首页失败",
                }
            await asyncio.sleep(3)

            # 关闭弹窗
            try:
                await self._page.evaluate("""() => {
                    document.querySelectorAll('[class*="close"]').forEach(el => {
                        try { el.click(); } catch(e) {}
                    });
                    document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}));
                }""")
            except Exception:
                pass
            await asyncio.sleep(1)

            # 等待搜索框出现（首页是 SPA，textarea 由 JS 异步渲染）
            input_box_selectors = [
                'textarea[placeholder*="搜索"]',
                'textarea[placeholder*="搜一搜"]',
                'textarea[placeholder*="输入"]',
                'textarea.textarea',
                '.textarea-container textarea',
                'input[placeholder*="搜索"]',
                'input[placeholder*="搜一搜"]',
                'input[type="search"]',
                '[class*="search-bar"] input',
                '[class*="searchBar"] input',
                '[class*="search-input"] input',
                '[class*="searchInput"]',
                '[class*="search-box"] input',
            ]
            input_locator = None
            found_input_sel = None
            # 最多等待 15 秒，每 1 秒重试一次
            for _wait in range(15):
                for sel in input_box_selectors:
                    try:
                        loc = self._page.locator(sel).first
                        if await loc.count() > 0:
                            # 不强求 is_visible（hidden textarea 也算存在），用 exists 判定
                            input_locator = loc
                            found_input_sel = sel
                            break
                    except Exception:
                        continue
                if input_locator is not None:
                    break
                await asyncio.sleep(1)

            if input_locator is None:
                # 调试：dump 页面里所有 textarea 和 input 的简短信息
                try:
                    debug_info = await self._page.evaluate("""() => {
                        const out = {textareas: [], inputs: [], url: location.href, title: document.title};
                        document.querySelectorAll('textarea').forEach((el, i) => {
                            if (i < 10) out.textareas.push({
                                cls: el.className, ph: el.placeholder,
                                visible: !!(el.offsetParent !== null || el.getBoundingClientRect().height>0)
                            });
                        });
                        document.querySelectorAll('input').forEach((el, i) => {
                            if (i < 10) out.inputs.push({
                                cls: el.className, ph: el.placeholder, type: el.type,
                                visible: !!(el.offsetParent !== null || el.getBoundingClientRect().height>0)
                            });
                        });
                        return out;
                    }""")
                    print(f"    [小红书搜索] 调试信息: URL={debug_info.get('url')} title={debug_info.get('title')}", flush=True)
                    print(f"    [小红书搜索] 调试 textarea: {debug_info.get('textareas')}", flush=True)
                    print(f"    [小红书搜索] 调试 input: {debug_info.get('inputs')}", flush=True)
                except Exception as e:
                    print(f"    [小红书搜索] 调试失败: {e}", flush=True)
                print(f"    [小红书搜索] 未找到搜索输入框，直接返回无数据", flush=True)
                return {
                    "brand": keyword,
                    "platform": "xiaohongshu",
                    "platform_name": "小红书",
                    "search_url": "https://www.xiaohongshu.com",
                    "total_found": 0,
                    "users": [],
                    "error": "未找到搜索输入框",
                }

            print(f"    [小红书搜索] 定位搜索输入框: {found_input_sel}", flush=True)
            await asyncio.sleep(3)

            # 2) 通过 page.evaluate 注入 JS 设置 value 并触发 input/change/focus 事件
            #    （Playwright 的 fill 在小红书 SPA 上偶尔不触发 Vue 的响应）
            await asyncio.sleep(2)
            set_value_ok = False
            try:
                eval_result = await self._page.evaluate(
                    """(kw) => {
                        const ta = document.querySelector('.textarea-container .textarea-wrapper textarea.textarea');
                        if (!ta) return {ok: false, reason: 'no-textarea'};
                        ta.focus();
                        const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                        setter.call(ta, kw);
                        ta.dispatchEvent(new Event('input', { bubbles: true }));
                        ta.dispatchEvent(new Event('change', { bubbles: true }));
                        ta.dispatchEvent(new Event('focus', { bubbles: true }));
                        return {ok: true, value: ta.value, focused: document.activeElement === ta};
                    }""",
                    keyword,
                )
                if eval_result and eval_result.get("ok"):
                    set_value_ok = True
                    print(f"    [小红书搜索] evaluate 设置值成功: {eval_result.get('value')}", flush=True)
                else:
                    print(f"    [小红书搜索] evaluate 设置值失败: {eval_result}", flush=True)
            except Exception as eval_err:
                print(f"    [小红书搜索] evaluate 异常: {str(eval_err)[:80]}", flush=True)

            if not set_value_ok:
                # fallback 到 fill
                try:
                    await input_locator.fill(keyword, timeout=3000)
                    print(f"    [小红书搜索] fill 关键词成功: {keyword}", flush=True)
                except Exception as fill_err:
                    print(f"    [小红书搜索] fill 也失败: {str(fill_err)[:80]}", flush=True)
                    try:
                        await input_locator.click(timeout=3000)
                        await self._page.keyboard.type(keyword, delay=30)
                        print(f"    [小红书搜索] keyboard.type 成功", flush=True)
                    except Exception as type_err:
                        print(f"    [小红书搜索] keyboard.type 也失败: {str(type_err)[:80]}", flush=True)
                        return {
                            "brand": keyword,
                            "platform": "xiaohongshu",
                            "platform_name": "小红书",
                            "search_url": "https://www.xiaohongshu.com",
                            "total_found": 0,
                            "users": [],
                            "error": f"输入关键词失败: {str(type_err)[:80]}",
                        }

            # 3) 验证输入框内容确实有值
            await asyncio.sleep(3)
            current_value = ""
            try:
                current_value = await input_locator.input_value()
            except Exception:
                pass
            # 同时从 evaluate 拿一次实际值（绕过 Playwright 缓存）
            try:
                eval_val = await self._page.evaluate(
                    "() => { const ta = document.querySelector('.textarea-container textarea.textarea'); return ta ? ta.value : null; }"
                )
                if eval_val:
                    current_value = eval_val
            except Exception:
                pass
            print(f"    [小红书搜索] 输入框当前值: '{current_value}'", flush=True)
            if not current_value:
                print(f"    [小红书搜索] 输入框仍为空，直接返回无数据", flush=True)
                return {
                    "brand": keyword,
                    "platform": "xiaohongshu",
                    "platform_name": "小红书",
                    "search_url": "https://www.xiaohongshu.com",
                    "total_found": 0,
                    "users": [],
                    "error": "输入框为空",
                }

            # 4) 按回车搜索（click textarea 让推荐词浮层失焦消失，再 focus 拉回，最后 Enter）
            print(f"    [小红书搜索] 按下回车，搜索关键词: {keyword}", flush=True)

            try:
                await input_locator.click(timeout=3000, force=True)
                print(f"    [小红书搜索] click textarea 成功，推荐词浮层应已消失", flush=True)
            except Exception as ce:
                print(f"    [小红书搜索] click textarea 失败: {str(ce)[:60]}", flush=True)

            try:
                await input_locator.focus(timeout=3000, force=True)
            except Exception as fe:
                print(f"    [小红书搜索] focus textarea 失败: {str(fe)[:60]}", flush=True)

            await self._page.keyboard.press("Enter")
            print(f"    [小红书搜索] 回车已发送", flush=True)
            await asyncio.sleep(3)

            # 刷新一次页面，让搜索结果 DOM 重新渲染（避免 Vue 没及时挂载 tab/卡片）
            try:
                await self._page.reload(wait_until="domcontentloaded", timeout=20000)
                print(f"    [小红书搜索] 刷新页面完成", flush=True)
            except Exception as re:
                print(f"    [小红书搜索] 刷新页面失败: {str(re)[:60]}", flush=True)
            await asyncio.sleep(3)
            # 等待搜索结果页加载（用户tab 是异步渲染的）
            user_tab_selectors = [
                '.channel-content',
                '[class*="channel-content"]',
                '[class*="tab-item"]',
                '[class*="tab"]:has-text("用户")',
                'text="用户"',
            ]
            tab_clicked = False
            # 等待最多 15 秒，让搜索结果页的 tab 出现
            for _wait in range(15):
                # 优先用 evaluate 直接定位 #user .channel-content 并 click
                try:
                    eval_res = await self._page.evaluate(
                        """() => {
                            const target = document.querySelector('#user .channel-content');
                            if (!target) return {ok: false, reason: '#user .channel-content not found'};
                            const text = target.textContent ? target.textContent.trim() : '';
                            target.click();
                            return {ok: true, tag: target.tagName, cls: target.className, text: text, id: target.id, parentId: target.parentElement ? target.parentElement.id : ''};
                        }"""
                    )
                    if eval_res and eval_res.get("ok"):
                        tab_clicked = True
                        print(f"    [小红书搜索] 点击用户tab成功: #{eval_res.get('id')} {eval_res.get('text')} (parent=#{eval_res.get('parentId')})", flush=True)
                        print(f"    [小红书搜索] 当前URL: {self._page.url}", flush=True)
                        break
                    else:
                        print(f"    [小红书搜索] evaluate 查找失败: {eval_res}", flush=True)
                except Exception as ev_err:
                    print(f"    [小红书搜索] evaluate 点击tab异常: {str(ev_err)[:80]}", flush=True)

                # evaluate 失败时回退到 Playwright 选择器
                if not tab_clicked:
                    for sel in user_tab_selectors:
                        try:
                            loc = self._page.locator(sel).first
                            if await loc.count() > 0 and await loc.is_visible():
                                await loc.click(timeout=3000, force=True)
                                tab_clicked = True
                                print(f"    [小红书搜索] Playwright 点击tab: {sel}", flush=True)
                                break
                        except Exception:
                            continue
                if tab_clicked:
                    break
                await asyncio.sleep(1)

            if tab_clicked:
                await asyncio.sleep(4)
            else:
                print(f"    [小红书搜索] 未找到用户tab，继续使用当前页面", flush=True)

            # 滚动加载更多
            for i in range(3):
                await self._page.evaluate("window.scrollBy(0, 600)")
                await asyncio.sleep(1.5)
                print(f"    [小红书搜索] 滚动第 {i + 1} 次", flush=True)

            # 提取用户列表
            # DOM 结构：
            #   div.user-list-item
            #     a[href*="/user/profile/"]   ← 整个卡片链接（?xsec_token=...）
            #       div.user-item-box
            #         div.avatar-container > img.user-image
            #         div.user-info
            #           div.user-name-box
            #             div.user-name  +  span.verify-icon > svg.use[xlink:href="#company"]
            #           span.user-desc  (小红书号：xxx)
            #           div.user-desc  (粉丝・xxx  笔记・xxx)
            users_data = await self._page.evaluate("""() => {
                const results = [];
                const cards = document.querySelectorAll('div.user-list-item');
                const seen = new Set();

                for (const card of cards) {
                    // 提取 profile 链接（?xsec_token= 前面的部分，不含哈希值）
                    const link = card.querySelector('a[href*="/user/profile/"]');
                    if (!link) continue;
                    const rawHref = link.getAttribute('href');
                    const profileUrl = rawHref.split('?')[0];
                    if (!profileUrl || seen.has(profileUrl)) continue;
                    seen.add(profileUrl);
                    const fullUrl = 'https://www.xiaohongshu.com' + profileUrl;

                    // 用户名
                    const nameEl = card.querySelector('div.user-name');
                    let name = nameEl ? nameEl.textContent.trim().replace(/[√✓]$/, '').trim() : '';

                    // 认证标识：通过 svg use xlink:href 判断
                    // #company = 蓝色圆圈勾（企业认证）
                    // #person  = 红色勾（个人认证）
                    const verifyIcon = card.querySelector('span.verify-icon svg use');
                    let verification = 'none';
                    let verifyType = '';
                    if (verifyIcon) {
                        const xlink = verifyIcon.getAttribute('xlink:href') || verifyIcon.getAttribute('href') || '';
                        if (xlink.includes('#company')) {
                            verification = 'blue_v';
                            verifyType = '企业认证';
                        } else if (xlink.includes('#person')) {
                            verification = 'yellow_v';
                            verifyType = '个人认证';
                        }
                    }

                    // 小红书号
                    const allSpans = card.querySelectorAll('span.user-desc');
                    let xhsId = '';
                    for (const span of allSpans) {
                        const text = span.textContent.trim();
                        const match = text.match(/小红书号[：:](.+)/);
                        if (match) {
                            xhsId = match[1].trim();
                            break;
                        }
                    }

                    // 粉丝数、笔记数、简介
                    let followerCount = '';
                    let noteCount = '';
                    let description = '';
                    const descDivs = card.querySelectorAll('div.user-desc');
                    for (const div of descDivs) {
                        const text = div.textContent.trim();
                        const fansMatch = text.match(/(?:粉丝|粉丝数)[・:]([\d.]+万?)/);
                        if (fansMatch) followerCount = fansMatch[1];
                        const notesMatch = text.match(/(?:笔记|笔记数)[・:]([\d.]+万?)/);
                        if (notesMatch) noteCount = notesMatch[1];
                        // 第一段不是小红书号的文本就是简介
                        if (description === '' && !text.match(/^(?:粉丝|笔记|小红书号)/) && text.length > 0 && text.length < 100) {
                            description = text;
                        }
                    }

                    if (name || profileUrl) {
                        results.push({
                            name: name,
                            profile_url: fullUrl,
                            verification: verification,
                            verify_type: verifyType,
                            xhs_id: xhsId,
                            follower_count: followerCount,
                            note_count: noteCount,
                            description: description,
                            platform: 'xiaohongshu',
                        });
                    }
                }
                return results;
            }""")

            print(f"    [小红书搜索] 提取到 {len(users_data)} 个用户卡片数据", flush=True)

            # ⚠️ 不再逐个进入用户主页，避免触发风控
            # 卡片列表本身已包含 name / xhs_id / 粉丝数 / 笔记数 / 简介 / 认证，直接用即可
            final_users = users_data[:30]
            for idx, u in enumerate(final_users):
                print(f"    [小红书搜索] 用户 {idx + 1}: {u.get('name', '')} | 认证={u.get('verification', 'none')} | 粉丝={u.get('follower_count', '')}", flush=True)

            return {
                "brand": keyword,
                "platform": "xiaohongshu",
                "platform_name": "小红书",
                "search_url": "https://www.xiaohongshu.com",
                "total_found": len(final_users),
                "users": final_users[:30],
                "error": "",
            }

        except Exception as e:
            return {
                "brand": keyword,
                "platform": "xiaohongshu",
                "platform_name": "小红书",
                "search_url": "https://www.xiaohongshu.com",
                "total_found": 0,
                "users": [],
                "error": str(e),
            }
