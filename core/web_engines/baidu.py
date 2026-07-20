# -*- coding: utf-8 -*-
"""百度搜索适配器（HTTP + CloakBrowser）。"""

from __future__ import annotations

import asyncio
import json
import time
import random
import httpx

_baidu_client: httpx.AsyncClient | None = None
_baidu_warmed_up: bool = False
_last_baidu_request_time: float = 0.0
_baidu_blocked_until: float = 0.0
BAIDU_COOLDOWN_SECONDS = 60   # 冷却 60 秒
BAIDU_MIN_INTERVAL = 3.0      # 两次请求最小间隔 3 秒

# UA 池：轮换 User-Agent 降低指纹识别
_BAIDU_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]


def _baidu_headers() -> dict:
    """生成带随机 UA 的完整浏览器请求头。"""
    ua = random.choice(_BAIDU_UA_POOL)
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Cache-Control": "max-age=0",
        "Sec-Ch-Ua": '"Chromium";v="125", "Not.A/Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }


async def _get_baidu_client() -> httpx.AsyncClient:
    """获取带 cookie 持久化的百度客户端（复用 session）。"""
    global _baidu_client, _baidu_warmed_up
    if _baidu_client is None or _baidu_client.is_closed:
        _baidu_client = httpx.AsyncClient(timeout=15.0, follow_redirects=True)
        _baidu_warmed_up = False
    if not _baidu_warmed_up:
        try:
            await _baidu_client.get("https://www.baidu.com/", headers=_baidu_headers())
            _baidu_warmed_up = True
            print("[Baidu] 预热完成，已获取 cookie", flush=True)
        except Exception:
            pass
    return _baidu_client


async def _reset_baidu_client() -> None:
    """重置百度客户端：关闭连接、清除被标记的 cookie，下次调用自动重建。"""
    global _baidu_client, _baidu_warmed_up
    if _baidu_client and not _baidu_client.is_closed:
        await _baidu_client.aclose()
    _baidu_client = None
    _baidu_warmed_up = False
    print("[Baidu] 客户端已重置（cookie 清除）", flush=True)


def is_in_cooldown() -> bool:
    """百度是否处于风控冷却期。"""
    return time.time() < _baidu_blocked_until


def cooldown_remaining_seconds() -> int:
    """冷却剩余秒数；未在冷却中时为 0。"""
    remain = int(_baidu_blocked_until - time.time())
    return remain if remain > 0 else 0


async def enter_cooldown() -> None:
    """进入风控冷却并重置客户端。"""
    global _baidu_blocked_until
    _baidu_blocked_until = time.time() + BAIDU_COOLDOWN_SECONDS
    await _reset_baidu_client()


async def _baidu_throttle() -> None:
    """请求节流：确保两次百度请求之间至少间隔 BAIDU_MIN_INTERVAL 秒。"""
    global _last_baidu_request_time
    now = time.time()
    elapsed = now - _last_baidu_request_time
    if elapsed < BAIDU_MIN_INTERVAL:
        wait = BAIDU_MIN_INTERVAL - elapsed
        await asyncio.sleep(wait)
    _last_baidu_request_time = time.time()


async def _resolve_baidu_redirects(results: list[dict]) -> None:
    """解析百度跳转链接，将 baidu.com/link?url=... 替换为真实 URL。"""

    async def _resolve_one(idx: int, url: str):
        if "baidu.com/link" not in url and "baidu.com/rec" not in url:
            return
        try:
            client = await _get_baidu_client()
            resp = await client.head(url, follow_redirects=False, headers=_baidu_headers())
            location = resp.headers.get("location", "")
            if location and not location.startswith("/"):
                results[idx]["url"] = location
                return
            resp = await client.get(url, follow_redirects=False, headers=_baidu_headers())
            location = resp.headers.get("location", "") or str(resp.url)
            if location and not location.startswith("/"):
                results[idx]["url"] = location
        except Exception:
            pass

    tasks = [
        _resolve_one(i, r["url"])
        for i, r in enumerate(results)
        if "baidu.com" in r.get("url", "")
    ]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
        resolved = sum(1 for r in results if "baidu.com" not in r.get("url", ""))
        print(f"[Baidu] URL 解析: {resolved}/{len(tasks)} 成功", flush=True)


def _attach_snippets_by_position(html: str, results: list[dict]) -> None:
    """按结果在 HTML 中的位置就近匹配 snippet。"""
    import re
    from html import unescape

    # 1. class 模式 snippet（带位置）
    snippet_patterns = [
        # 新版百度 cosc 组件布局
        re.compile(r'<span[^>]*class="[^"]*summary-text[^"]*"[^>]*>(.*?)</span>', re.DOTALL),
        re.compile(r'<div[^>]*class="[^"]*summary-gap[^"]*"[^>]*>(.*?)</div>', re.DOTALL),
        # 旧版百度布局
        re.compile(r'<span[^>]*class="[^"]*c-abstract[^"]*"[^>]*>(.*?)</span>', re.DOTALL),
        re.compile(r'<span[^>]*class="[^"]*content-right[^"]*"[^>]*>(.*?)</span>', re.DOTALL),
        re.compile(r'<div[^>]*class="[^"]*c-abstract[^"]*"[^>]*>(.*?)</div>', re.DOTALL),
        re.compile(r'<span[^>]*class="[^"]*c-span-last[^"]*"[^>]*>(.*?)</span>', re.DOTALL),
    ]
    class_snips = []
    for pat in snippet_patterns:
        for m in pat.finditer(html):
            text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            text = unescape(text)
            if text:
                class_snips.append((m.start(), text))
        if class_snips:
            break

    # 2. s-data 结构化摘要（带位置）
    sdata_snips = []
    sdata_pattern = re.compile(r'<!--s-data:(.*?)-->', re.DOTALL)
    for sm in sdata_pattern.finditer(html):
        try:
            data = json.loads(sm.group(1))
            sd = data.get("summaryData", {})
            texts = []
            for line in sd.get("generalLines", []):
                for d in line.get("data", []):
                    t = d.get("text", "")
                    if t:
                        t = re.sub(r'<[^>]+>', '', t).strip()
                        if t:
                            texts.append(t)
            if texts:
                sdata_snips.append((sm.start(), " ".join(texts)))
        except Exception:
            continue

    print(f"[Baidu] snippet 源: class={len(class_snips)} s-data={len(sdata_snips)}", flush=True)

    # 3. 合并两个数据源，按位置排序，对每条结果取其后最近的未使用 snippet
    all_snips = sorted(class_snips + sdata_snips, key=lambda x: x[0])
    used = set()
    for r in results:
        rpos = r.get("_pos", 0)
        for idx, (spos, text) in enumerate(all_snips):
            if idx in used:
                continue
            if spos >= rpos:
                r["snippet"] = text
                used.add(idx)
                break
    for r in results:
        r.pop("_pos", None)


async def _search_baidu_browser(query: str, max_results: int = 5) -> list[dict]:
    """百度搜索（CloakBrowser 真实浏览器版本，反风控能力强）。
    HTTP 版被拦截时自动降级到此版本。
    """
    print(f"[Baidu-Browser] 搜索: {query}", flush=True)
    try:
        from core.browser_manager import get_browser_manager
        from config import COOKIE_DIR
        baidu_profile = str(COOKIE_DIR / "baidu_profile")

        bm = get_browser_manager()
        async with bm.acquire_page(baidu_profile, headless=True) as page_ctx:
            page = page_ctx.page
            await page.goto(
                f"https://www.baidu.com/s?wd={query}",
                wait_until="domcontentloaded",
                timeout=15000,
            )
            await page.wait_for_timeout(1500)

            # 检查是否被拦截
            content = await page.content()
            if "百度安全验证" in content:
                print("[Baidu-Browser] 安全验证拦截", flush=True)
                return [{"title": "百度被拦截", "url": "", "snippet": "浏览器版也被拦截"}]

            # 提取搜索结果
            results = await page.evaluate("""(maxResults) => {
                const items = document.querySelectorAll('h3.t a, h3[class*="t"] a');
                const out = [];
                for (const a of items) {
                    const href = a.getAttribute('href') || '';
                    const title = a.innerText.trim();
                    if (href && title && !href.includes('baidu.com/baidu.php')) {
                        out.push({ title, url: href, snippet: '' });
                    }
                    if (out.length >= maxResults) break;
                }
                return out;
            }""", max_results)

            print(f"[Baidu-Browser] 提取到 {len(results)} 条结果", flush=True)

            # 解析百度跳转链接
            if results:
                await _resolve_baidu_redirects(results)

            return results if results else [{"title": "百度搜索", "url": "", "snippet": "未找到结果"}]

    except Exception as e:
        print(f"[Baidu-Browser] 异常: {type(e).__name__}: {e}", flush=True)
        return [{"title": "百度搜索错误", "url": "", "snippet": str(e)}]


async def _search_baidu(query: str, max_results: int = 5) -> list[dict]:
    """百度搜索（HTML 抓取），带 cookie 持久化 + 请求节流。"""
    import re
    from html import unescape

    await _baidu_throttle()

    print(f"[Baidu] 搜索: {query}", flush=True)

    client = await _get_baidu_client()
    try:
        resp = await client.get(
            "https://www.baidu.com/s",
            params={"wd": query},
            headers=_baidu_headers(),
        )
        if resp.status_code != 200:
            print(f"[Baidu] HTTP {resp.status_code}", flush=True)
            return [{"title": "百度搜索失败", "url": "", "snippet": f"HTTP {resp.status_code}"}]

        html = resp.text

        if "百度安全验证" in html or len(html) < 5000:
            print(f"[Baidu] 安全验证拦截，HTML长度={len(html)}", flush=True)
            return [{
                "title": "百度被拦截",
                "url": "",
                "snippet": "百度安全验证拦截，无法获取搜索结果",
            }]

        results = []

        h3_pattern = re.compile(
            r'<h3[^>]*class="[^"]*t[^"]*"[^>]*>.*?<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            re.DOTALL,
        )
        # 提取结果容器上的 mu 属性（新版百度直接给出真实 URL）
        mu_pattern = re.compile(
            r'<div[^>]*class="[^"]*result\s+c-container[^"]*"[^>]*\bmu="([^"]*)"',
        )
        mu_entries = [(m.start(), m.group(1)) for m in mu_pattern.finditer(html)]

        total_h3 = 0
        filtered_ad = 0
        for m in h3_pattern.finditer(html):
            total_h3 += 1
            href = m.group(1)
            if "baidu.com/baidu.php" in href:
                filtered_ad += 1
                continue
            title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            title = unescape(title)
            if title:
                results.append({
                    "title": title,
                    "url": href,
                    "snippet": "",
                    "_pos": m.start(),
                })
            if len(results) >= max_results:
                break
        print(f"[Baidu] h3.t 匹配 {total_h3} 条，过滤 baidu.php 广告 {filtered_ad} 条，取自然结果 {len(results)} 条", flush=True)

        if results:
            await _resolve_baidu_redirects(results)

        # mu 属性回退：跳转解析失败时，用最近的 mu 值作为真实 URL
        if mu_entries:
            for r in results:
                url = r.get("url", "")
                if "baidu.com/link" in url or "baidu.com/rec" in url:
                    rpos = r.get("_pos", 0)
                    best_mu = None
                    for mpos, mu_url in mu_entries:
                        if mpos <= rpos:
                            best_mu = mu_url
                        else:
                            break
                    if best_mu:
                        print(f"[Baidu] mu 回退: {url[:50]}... → {best_mu}", flush=True)
                        r["url"] = best_mu
        print(f"[Baidu] 解析到 {len(results)} 条结果", flush=True)

        _attach_snippets_by_position(html, results)

        if not results:
            return [{
                "title": "百度搜索",
                "url": f"https://www.baidu.com/s?wd={query}",
                "snippet": "未找到结果，请检查网络连接",
            }]

        return results
    except Exception as e:
        print(f"[Baidu] 异常: {type(e).__name__}: {e}", flush=True)
        return [{"title": "百度搜索错误", "url": "", "snippet": str(e)}]
