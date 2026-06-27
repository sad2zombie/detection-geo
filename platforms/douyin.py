# -*- coding: utf-8 -*-
"""抖音平台搜索模块（仅 _do_search 核心逻辑）"""

import asyncio
from urllib.parse import quote

from config import DOUYIN_PROFILE
from platforms.base import BasePlatform, SearchResult
from platforms import register_platform


@register_platform
class DouyinPlatform(BasePlatform):
    platform_key = "douyin"
    platform_name = "抖音"
    profile_dir = str(DOUYIN_PROFILE)
    home_url = "https://www.douyin.com"

    async def _do_search(self, keyword: str) -> SearchResult:
        await self._ensure_browser(headless=False)
        search_url = f"https://www.douyin.com/search/{quote(keyword)}?type=user"

        try:
            if not await self._goto_with_retry(search_url):
                return self._err_result(keyword, search_url, "导航抖音搜索页失败")

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
                current_count = await self._page.evaluate(
                    "() => document.querySelectorAll('.search-result-card').length"
                )
                if current_count >= 30:
                    break

            users_data = await self._page.evaluate("""() => {
                const results = [];
                const cards = document.querySelectorAll('.search-result-card');
                const seen = new Set();

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
                    const userLink = card.querySelector('a[href*="/user/"]');
                    const href = userLink ? userLink.href : '';
                    if (!href || href.includes('/user/self') || seen.has(href)) continue;
                    seen.add(href);

                    const fullText = card.textContent.trim();

                    const badgeEl = card.querySelector('[data-e2e="badge-role-name"]');
                    const verification = badgeEl ? '蓝V' : '未认证';

                    let douyinId = '';
                    let likeCount = '';
                    let followerCount = '';

                    const idTextEl = findInnermostEl(card, '抖音号:');
                    if (idTextEl) {
                        let row = idTextEl;
                        while (row.parentElement && row.parentElement.children.length < 3) {
                            row = row.parentElement;
                        }
                        const infoRow = row.parentElement || row;
                        const items = Array.from(infoRow.children).filter(child => {
                            const t = child.textContent.trim();
                            return t.length > 0 && t !== '·' && t !== '|';
                        });
                        if (items.length >= 1) douyinId = items[0].textContent.replace('抖音号:', '').trim();
                        if (items.length >= 2) likeCount = items[1].textContent.replace('获赞', '').trim();
                        if (items.length >= 3) followerCount = items[2].textContent.replace('粉丝', '').trim();
                    }

                    const likeMatch = fullText.match(/([\\d.]+万?)\\s*获赞/);
                    if (!likeCount && likeMatch) likeCount = likeMatch[1];

                    const followerMatch = fullText.match(/([\\d.]+万?)\\s*粉丝/);
                    if (!followerCount && followerMatch) followerCount = followerMatch[1];

                    if (!douyinId) {
                        const idMatch = fullText.match(/抖音号:\\s*(\\S+)/);
                        if (idMatch) {
                            let rawId = idMatch[1];
                            if (likeCount) {
                                const likeNum = likeCount.replace('万', '');
                                if (rawId.endsWith(likeNum)) {
                                    rawId = rawId.slice(0, -likeNum.length);
                                }
                            }
                            douyinId = rawId.trim();
                        }
                    }

                    let name = '';
                    if (badgeEl) {
                        const titleBox = badgeEl.parentElement.previousElementSibling;
                        if (titleBox) name = titleBox.textContent.trim();
                    }
                    if (!name) {
                        const firstP = card.querySelector('p');
                        if (firstP) name = firstP.textContent.trim();
                    }
                    if (!name || name.length > 50) {
                        const endIdx = fullText.indexOf('抖音号:');
                        if (endIdx > 0 && endIdx < 100) {
                            name = fullText.substring(0, endIdx).trim();
                            ['认证徽章', '关注', '店铺账号'].forEach(tag => {
                                const idx = name.indexOf(tag);
                                if (idx > 0) name = name.substring(0, idx).trim();
                            });
                        }
                    }

                    let description = '';
                    const allP = card.querySelectorAll('p');
                    if (allP.length >= 2) {
                        const lastP = allP[allP.length - 1];
                        const descText = lastP.textContent.trim();
                        if (descText !== name && descText.length > 10) {
                            description = descText;
                        }
                    }
                    if (!description) {
                        const fanIdx = fullText.indexOf('粉丝');
                        if (fanIdx > -1) {
                            description = fullText.substring(fanIdx + 2).trim();
                        }
                    }

                    const isPrivate = fullText.includes('私密账号');

                    if (name || href) {
                        results.push({
                            name: name,
                            profile_url: href,
                            verification: verification,
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
                "platform": self.platform_key,
                "platform_name": self.platform_name,
                "search_url": search_url,
                "total_found": min(len(users_data), 30),
                "users": users_data[:30],
                "error": "",
            }

        except Exception as e:
            return self._err_result(keyword, search_url, str(e))

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