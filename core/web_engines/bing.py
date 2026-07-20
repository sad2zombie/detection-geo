# -*- coding: utf-8 -*-
"""Bing 搜索适配器（HTML + Browser + API）。"""

from __future__ import annotations

import logging

import httpx

import config

logger = logging.getLogger(__name__)

async def _search_bing_html(query: str, max_results: int = 5) -> list[dict]:
    """Bing HTML 抓取（无需 API Key），风控比百度宽松得多。"""
    import re
    from html import unescape

    logger.info(f"[Bing] 搜索: {query}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
    }

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        try:
            resp = await client.get(
                "https://cn.bing.com/search",
                params={"q": query, "count": max_results * 2, "setlang": "zh-CN"},
                headers=headers,
            )
            if resp.status_code != 200:
                logger.info(f"[Bing] HTTP {resp.status_code}")
                return [{"title": "Bing搜索失败", "url": "", "snippet": f"HTTP {resp.status_code}"}]

            html = resp.text
            results = []

            algo_pattern = re.compile(
                r'<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>(.*?)(?=<li[^>]*class="[^"]*b_algo|</ul>|</ol>|$)',
                re.DOTALL,
            )

            for m in algo_pattern.finditer(html):
                block = m.group(1)
                link_m = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL)
                if not link_m:
                    continue
                url = link_m.group(1)
                title = re.sub(r'<[^>]+>', '', link_m.group(2)).strip()
                title = unescape(title)

                snippet = ""
                snip_m = re.search(r'<p[^>]*class="[^"]*b_lineclamp[^"]*"[^>]*>(.*?)</p>', block, re.DOTALL)
                if not snip_m:
                    snip_m = re.search(r'<div[^>]*class="[^"]*b_caption[^"]*"[^>]*>.*?<p[^>]*>(.*?)</p>', block, re.DOTALL)
                if not snip_m:
                    snip_m = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
                if snip_m:
                    snippet = re.sub(r'<[^>]+>', '', snip_m.group(1)).strip()
                    snippet = unescape(snippet)

                if title and url and not url.startswith("javascript"):
                    results.append({"title": title, "url": url, "snippet": snippet})
                if len(results) >= max_results:
                    break

            logger.info(f"[Bing] 解析到 {len(results)} 条结果")

            if not results:
                return [{"title": "Bing搜索", "url": f"https://cn.bing.com/search?q={query}", "snippet": "未找到结果"}]

            return results
        except Exception as e:
            logger.error(f"[Bing] 异常: {type(e).__name__}: {e}")
            return [{"title": "Bing搜索错误", "url": "", "snippet": str(e)}]


async def _search_bing(query: str, max_results: int = 5) -> list[dict]:
    """Bing Web Search API v7。"""
    if not config.BING_API_KEY:
        return [{"title": "配置错误", "url": "", "snippet": "BING_API_KEY 未配置"}]

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(
                "https://api.bing.microsoft.com/v7.0/search",
                params={"q": query, "count": max_results},
                headers={"Ocp-Apim-Subscription-Key": config.BING_API_KEY},
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for item in data.get("webPages", {}).get("value", []):
                results.append({
                    "title": item.get("name", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("snippet", ""),
                })
            return results[:max_results]
        except Exception as e:
            return [{"title": "搜索错误", "url": "", "snippet": f"Bing 搜索失败: {e}"}]

async def _search_bing_browser(query: str, max_results: int = 5) -> list[dict]:
    """Bing 搜索（CloakBrowser 真实浏览器版本）。
    HTTP 版返回不相关结果时降级到此版本。
    """
    import re
    from html import unescape

    logger.info(f"[Bing-Browser] 搜索: {query}")
    try:
        from core.browser_manager import get_browser_manager
        from config import COOKIE_DIR
        bing_profile = str(COOKIE_DIR / "bing_profile")

        bm = get_browser_manager()
        async with bm.acquire_page(bing_profile, headless=True) as page_ctx:
            page = page_ctx.page
            await page.goto(
                f"https://cn.bing.com/search?q={query}&count={max_results * 2}&setlang=zh-CN",
                wait_until="domcontentloaded",
                timeout=20000,
            )
            await page.wait_for_timeout(2000)

            # 提取搜索结果
            results = await page.evaluate("""(maxResults) => {
                const items = document.querySelectorAll('li.b_algo');
                const out = [];
                for (const li of items) {
                    const h2 = li.querySelector('h2 a');
                    if (!h2) continue;
                    const href = h2.getAttribute('href') || '';
                    const title = h2.innerText.trim();
                    const snipEl = li.querySelector('p.b_lineclamp2, p.b_lineclamp3, .b_caption p');
                    const snippet = snipEl ? snipEl.innerText.trim() : '';
                    if (href && title) {
                        out.push({ title, url: href, snippet });
                    }
                    if (out.length >= maxResults) break;
                }
                return out;
            }""", max_results)

            logger.info(f"[Bing-Browser] 提取到 {len(results)} 条结果")
            return results if results else [{"title": "Bing搜索", "url": "", "snippet": "未找到结果"}]

    except Exception as e:
        logger.error(f"[Bing-Browser] 异常: {type(e).__name__}: {e}")
        return [{"title": "Bing搜索错误", "url": "", "snippet": str(e)}]
