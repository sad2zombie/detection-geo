# -*- coding: utf-8 -*-
"""小红书平台搜索模块（仅 _do_search 核心逻辑）"""

import asyncio

from config import XHS_PROFILE
from platforms.base import BasePlatform, SearchResult
from platforms import register_platform


@register_platform
class XiaohongshuPlatform(BasePlatform):
    platform_key = "xiaohongshu"
    platform_name = "小红书"
    profile_dir = str(XHS_PROFILE)
    home_url = "https://www.xiaohongshu.com"

    async def _do_search(self, keyword: str) -> SearchResult:
        await self._ensure_browser(headless=False)

        try:
            if not await self._goto_with_retry("https://www.xiaohongshu.com"):
                return self._err_result(keyword, "https://www.xiaohongshu.com", "导航小红书首页失败")

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
            for _wait in range(15):
                for sel in input_box_selectors:
                    try:
                        loc = self._page.locator(sel).first
                        if await loc.count() > 0:
                            input_locator = loc
                            found_input_sel = sel
                            break
                    except Exception:
                        continue
                if input_locator is not None:
                    break
                await asyncio.sleep(1)

            if input_locator is None:
                print(f"    [{self.platform_name}搜索] 未找到搜索输入框，直接返回无数据", flush=True)
                return self._err_result(keyword, "https://www.xiaohongshu.com", "未找到搜索输入框")

            print(f"    [{self.platform_name}搜索] 定位搜索输入框: {found_input_sel}", flush=True)
            await asyncio.sleep(3)

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
                    print(f"    [{self.platform_name}搜索] evaluate 设置值成功: {eval_result.get('value')}", flush=True)
                else:
                    print(f"    [{self.platform_name}搜索] evaluate 设置值失败: {eval_result}", flush=True)
            except Exception as eval_err:
                print(f"    [{self.platform_name}搜索] evaluate 异常: {str(eval_err)[:80]}", flush=True)

            if not set_value_ok:
                try:
                    await input_locator.fill(keyword, timeout=3000)
                    print(f"    [{self.platform_name}搜索] fill 关键词成功: {keyword}", flush=True)
                except Exception as fill_err:
                    print(f"    [{self.platform_name}搜索] fill 也失败: {str(fill_err)[:80]}", flush=True)
                    try:
                        await input_locator.click(timeout=3000)
                        await self._page.keyboard.type(keyword, delay=30)
                        print(f"    [{self.platform_name}搜索] keyboard.type 成功", flush=True)
                    except Exception as type_err:
                        return self._err_result(keyword, "https://www.xiaohongshu.com", f"输入关键词失败: {str(type_err)[:80]}")

            await asyncio.sleep(3)
            current_value = ""
            try:
                current_value = await input_locator.input_value()
            except Exception:
                pass
            try:
                eval_val = await self._page.evaluate(
                    "() => { const ta = document.querySelector('.textarea-container textarea.textarea'); return ta ? ta.value : null; }"
                )
                if eval_val:
                    current_value = eval_val
            except Exception:
                pass
            print(f"    [{self.platform_name}搜索] 输入框当前值: '{current_value}'", flush=True)
            if not current_value:
                return self._err_result(keyword, "https://www.xiaohongshu.com", "输入框为空")

            print(f"    [{self.platform_name}搜索] 按下回车，搜索关键词: {keyword}", flush=True)

            try:
                await input_locator.click(timeout=3000, force=True)
            except Exception:
                pass
            try:
                await input_locator.focus(timeout=3000, force=True)
            except Exception:
                pass

            await self._page.keyboard.press("Enter")
            await asyncio.sleep(3)

            try:
                await self._page.reload(wait_until="domcontentloaded", timeout=20000)
            except Exception:
                pass
            await asyncio.sleep(3)

            # 等待用户 tab 出现并点击
            tab_clicked = False
            for _wait in range(15):
                try:
                    eval_res = await self._page.evaluate(
                        """() => {
                            const target = document.querySelector('#user .channel-content');
                            if (!target) return {ok: false, reason: '#user .channel-content not found'};
                            target.click();
                            return {ok: true, text: target.textContent ? target.textContent.trim() : '', parentId: target.parentElement ? target.parentElement.id : ''};
                        }"""
                    )
                    if eval_res and eval_res.get("ok"):
                        tab_clicked = True
                        break
                except Exception:
                    pass

                if not tab_clicked:
                    for sel in ['.channel-content', '[class*="channel-content"]', '[class*="tab-item"]', '[class*="tab"]:has-text("用户")', 'text="用户"']:
                        try:
                            loc = self._page.locator(sel).first
                            if await loc.count() > 0 and await loc.is_visible():
                                await loc.click(timeout=3000, force=True)
                                tab_clicked = True
                                break
                        except Exception:
                            continue
                if tab_clicked:
                    break
                await asyncio.sleep(1)

            if tab_clicked:
                await asyncio.sleep(4)
            else:
                print(f"    [{self.platform_name}搜索] 未找到用户tab，继续使用当前页面", flush=True)

            for i in range(3):
                await self._page.evaluate("window.scrollBy(0, 600)")
                await asyncio.sleep(1.5)
                print(f"    [{self.platform_name}搜索] 滚动第 {i + 1} 次", flush=True)

            users_data = await self._page.evaluate(r"""() => {
                const results = [];
                const cards = document.querySelectorAll('div.user-list-item');
                const seen = new Set();

                for (const card of cards) {
                    const link = card.querySelector('a[href*="/user/profile/"]');
                    if (!link) continue;
                    const rawHref = link.getAttribute('href');
                    const profileUrl = rawHref.split('?')[0];
                    if (!profileUrl || seen.has(profileUrl)) continue;
                    seen.add(profileUrl);
                    const fullUrl = 'https://www.xiaohongshu.com' + profileUrl;

                    const nameEl = card.querySelector('div.user-name');
                    let name = nameEl ? nameEl.textContent.trim().replace(/[√✓]$/, '').trim() : '';

                    const verifyIcon = card.querySelector('span.verify-icon svg use');
                    let verification = '未认证';
                    let verifyType = '';
                    if (verifyIcon) {
                        const xlink = verifyIcon.getAttribute('xlink:href') || verifyIcon.getAttribute('href') || '';
                        if (xlink.includes('#company')) {
                            verification = '企业认证';
                            verifyType = '企业认证';
                        } else if (xlink.includes('#person')) {
                            verification = '个人认证';
                            verifyType = '个人认证';
                        }
                    }

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

            print(f"    [{self.platform_name}搜索] 提取到 {len(users_data)} 个用户卡片数据", flush=True)

            final_users = users_data[:30]

            return {
                "brand": keyword,
                "platform": self.platform_key,
                "platform_name": self.platform_name,
                "search_url": "https://www.xiaohongshu.com",
                "total_found": len(final_users),
                "users": final_users[:30],
                "error": "",
            }

        except Exception as e:
            return self._err_result(keyword, "https://www.xiaohongshu.com", str(e))

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