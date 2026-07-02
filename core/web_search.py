# -*- coding: utf-8 -*-
"""Web 搜索服务 —— 百度（优先，含反风控） / Bing。

移植自 huoshangeo-master/app/services/web_search.py，
删除博查搜索分支，settings.* → config.*。
"""

import asyncio
import json
import time
import random
import httpx

import config

# ── 百度反风控状态 ──
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


async def _baidu_throttle() -> None:
    """请求节流：确保两次百度请求之间至少间隔 BAIDU_MIN_INTERVAL 秒。"""
    global _last_baidu_request_time
    now = time.time()
    elapsed = now - _last_baidu_request_time
    if elapsed < BAIDU_MIN_INTERVAL:
        wait = BAIDU_MIN_INTERVAL - elapsed
        await asyncio.sleep(wait)
    _last_baidu_request_time = time.time()


async def web_search(query: str, max_results: int = 5, force_engine: str = "") -> list[dict]:
    """
    执行网络搜索。
    降级链路: 百度 HTTP → 百度浏览器 → Bing HTML → Bing浏览器 → Bing API → 博查。
    force_engine 指定时跳过降级链，仅使用指定引擎。

    Returns:
        [{ "title": "...", "url": "...", "snippet": "...", "_engine": "..." }]
    """
    global _baidu_blocked_until

    # ── force_engine 模式：仅使用指定引擎 ──
    if force_engine:
        if force_engine == "baidu":
            results = await _search_baidu(query, max_results)
            if results and _search_results_relevant(query, results):
                return _tag_engine(results, "百度")
        elif force_engine == "bing":
            results = await _search_bing_html(query, max_results)
            if results and _search_results_relevant(query, results):
                return _tag_engine(results, "Bing")
        elif force_engine == "bocha":
            results = await _search_bocha(query, max_results)
            if results and not _is_error_result(results) and _search_results_relevant(query, results):
                return _tag_engine(results, "博查")
        return _tag_engine([], force_engine)

    baidu_in_cooldown = time.time() < _baidu_blocked_until
    if baidu_in_cooldown:
        remain = int(_baidu_blocked_until - time.time())
        print(f"[Search] 百度冷却中，跳过百度（剩余{remain}s）", flush=True)

    # ── 1. 百度搜索（优先，被风控时重试 1 次） ──
    if not baidu_in_cooldown:
        results = await _search_baidu(query, max_results)
        if results and not _is_error_result(results) and _search_results_relevant(query, results):
            return _tag_engine(results, "百度")
        if results and not _is_error_result(results):
            print("[Search] 百度 HTTP 结果与查询不相关，继续降级", flush=True)

        print("[Search] 百度第1次被拦截，等待3s后重试", flush=True)
        await asyncio.sleep(3)
        results = await _search_baidu(query, max_results)
        if results and not _is_error_result(results) and _search_results_relevant(query, results):
            return _tag_engine(results, "百度")
        if results and not _is_error_result(results):
            print("[Search] 百度 HTTP 重试结果仍不相关，尝试浏览器版", flush=True)

        # HTTP 百度失败，尝试 CloakBrowser 版百度
        print("[Search] HTTP百度被拦截，尝试CloakBrowser版", flush=True)
        results = await _search_baidu_browser(query, max_results)
        if results and not _is_error_result(results) and _search_results_relevant(query, results):
            return _tag_engine(results, "百度-浏览器")
        if results and not _is_error_result(results):
            print("[Search] 百度浏览器版结果不相关，继续降级", flush=True)

        _baidu_blocked_until = time.time() + BAIDU_COOLDOWN_SECONDS
        await _reset_baidu_client()
        print(f"[Search] 百度连续被拦截，进入冷却期 {BAIDU_COOLDOWN_SECONDS}s", flush=True)

    # ── 2. Bing HTML 搜索（百度不可用时降级，无需 API Key） ──
    results = await _search_bing_html(query, max_results)
    if results and not _is_error_result(results) and _search_results_relevant(query, results):
        return _tag_engine(results, "Bing")

    # ── 2.5 Bing 浏览器版（HTTP 版结果不相关时降级） ──
    print("[Search] Bing HTTP 结果不理想，尝试CloakBrowser版", flush=True)
    results = await _search_bing_browser(query, max_results)
    if results and not _is_error_result(results) and _search_results_relevant(query, results):
        return _tag_engine(results, "Bing-浏览器")

    # ── 3. Bing API 搜索（如有 API Key） ──
    if config.BING_API_KEY:
        results = await _search_bing(query, max_results)
        if results and not _is_error_result(results) and _search_results_relevant(query, results):
            return _tag_engine(results, "Bing-API")

    # ── 4. 博查 AI 搜索（最终降级） ──
    if config.BOCHA_API_KEY:
        results = await _search_bocha(query, max_results)
        if results and not _is_error_result(results) and _search_results_relevant(query, results):
            return _tag_engine(results, "博查")
        if results and not _is_error_result(results):
            print("[Search] 博查结果与查询不相关", flush=True)
        print("[Search] 博查搜索失败", flush=True)

    return _tag_engine([], "无可用引擎")


def _is_error_result(results: list[dict]) -> bool:
    """检查结果是否为错误消息。"""
    if not results:
        return True
    first = results[0]
    title = first.get("title", "")
    snippet = first.get("snippet", "")
    error_keywords = ("搜索错误", "搜索失败", "ratelimit", "rate limit", "配置错误", "百度被拦截", "未找到结果")
    combined = (title + snippet).lower()
    return any(kw.lower() in combined for kw in error_keywords)


def _search_results_relevant(query: str, results: list[dict]) -> bool:
    """检查搜索结果是否与查询相关。

    用于过滤反爬页、乱码页、或解析错位导致的不相关条目。
    要求至少一条结果的标题或摘要包含品牌关键词。
    """
    if not results:
        return False
    query_clean = query.replace(" 官网", "").replace("官网", "").replace(" 品牌", "").replace("品牌", "").strip()
    if not query_clean:
        return True
    # 英文品牌名按整词匹配；中文按完整名或前两字匹配
    q_lower = query_clean.lower()
    for r in results:
        text = (r.get("title", "") + " " + r.get("snippet", "")).lower()
        if q_lower in text:
            return True
        if query_clean.isascii():
            continue
        if len(query_clean) >= 2 and query_clean[:2].lower() in text:
            return True
        if len(query_clean) >= 3 and query_clean[:3].lower() in text:
            return True
    return False


def _tag_engine(results: list[dict], engine: str) -> list[dict]:
    """为每条结果注入 _engine 字段，标识数据来源。"""
    for r in results:
        r["_engine"] = engine
    return results

async def _search_bocha(query: str, max_results: int = 5) -> list[dict]:
    """博查 AI 搜索 API（https://open.bochaai.com），中文搜索质量最佳。"""
    if not config.BOCHA_API_KEY:
        return [{"title": "配置错误", "url": "", "snippet": "BOCHA_API_KEY 未配置"}]

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(
                "https://api.bochaai.com/v1/web-search",
                headers={
                    "Authorization": f"Bearer {config.BOCHA_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "query": query,
                    "freshness": "noLimit",
                    "summary": True,
                    "count": min(max_results, 10),
                },
            )
            resp.raise_for_status()
            body = resp.json()

            # 兼容两种格式：结果在顶层 webPages 或 data.webPages
            data = body.get("data", body) if isinstance(body, dict) else body
            results = []
            for item in data.get("webPages", {}).get("value", [])[:max_results]:
                results.append({
                    "title": item.get("name", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("summary", "") or item.get("snippet", ""),
                })
            print(f"[Bocha] 查询: {query}, 解析到 {len(results)} 条结果", flush=True)
            return results
        except Exception as e:
            print(f"[Bocha] 请求异常: {type(e).__name__}: {e}", flush=True)
            return [{"title": "搜索错误", "url": "", "snippet": f"博查搜索失败: {e}"}]


async def _search_bing_html(query: str, max_results: int = 5) -> list[dict]:
    """Bing HTML 抓取（无需 API Key），风控比百度宽松得多。"""
    import re
    from html import unescape

    print(f"[Bing] 搜索: {query}", flush=True)

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
                print(f"[Bing] HTTP {resp.status_code}", flush=True)
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

            print(f"[Bing] 解析到 {len(results)} 条结果", flush=True)

            if not results:
                return [{"title": "Bing搜索", "url": f"https://cn.bing.com/search?q={query}", "snippet": "未找到结果"}]

            return results
        except Exception as e:
            print(f"[Bing] 异常: {type(e).__name__}: {e}", flush=True)
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


async def _search_bing_browser(query: str, max_results: int = 5) -> list[dict]:
    """Bing 搜索（CloakBrowser 真实浏览器版本）。
    HTTP 版返回不相关结果时降级到此版本。
    """
    import re
    from html import unescape

    print(f"[Bing-Browser] 搜索: {query}", flush=True)
    try:
        from core.browser_manager import get_browser_manager
        from config import COOKIE_DIR
        bing_profile = str(COOKIE_DIR / "baidu_profile")  # 复用 baidu_profile

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

            print(f"[Bing-Browser] 提取到 {len(results)} 条结果", flush=True)
            return results if results else [{"title": "Bing搜索", "url": "", "snippet": "未找到结果"}]

    except Exception as e:
        print(f"[Bing-Browser] 异常: {type(e).__name__}: {e}", flush=True)
        return [{"title": "Bing搜索错误", "url": "", "snippet": str(e)}]


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
