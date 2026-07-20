# -*- coding: utf-8 -*-
"""品牌官网规则识别与结果合成。"""

from __future__ import annotations

import re
import httpx
from urllib.parse import urlparse, urlunparse

import config

# UGC / 内容平台，不可作为品牌官网
_UGC_HOST_MARKERS = (
    "meipian.cn", "zhihu.com", "douban.com", "weibo.com", "weibo.cn",
    "douyin.com", "xiaohongshu.com", "xhslink.com", "toutiao.com",
    "mp.weixin.qq.com", "bilibili.com", "youku.com", "iqiyi.com",
    "163.com", "sohu.com", "ifeng.com",
)

# 搜索引擎主域（含子域），不可作为品牌官网
_SEARCH_ENGINE_HOSTS = (
    "baidu.com", "bing.com", "google.com", "sogou.com",
    "so.com", "sm.cn", "yahoo.com", "duckduckgo.com",
)

# 搜索平台聚合页标题特征，非品牌官网
_AGGREGATION_TITLE_MARKERS = (
    "精选笔记", "视频合集", "资讯聚合", "相关搜索", "大家在看",
    "百度笔记", "百家号",
)

_NON_OFFICIAL_PATH_MARKERS = (
    "/article/", "/dy/", "/news/", "/News/", "/rain/a/",
    "/pinpai/", "/dpfx/", "/softdown/", "/brand/",
    "/ask/", "/question/", "/wenda/", "/qa/",
    "/club/", "/bbs/", "/forum/", "/topic/",
    "/list-", "/column/", "/post/", "/posts/", "/p/",
    "/doc/", "/detail/", "/content/", "/archives/",
)

_COMPANY_SUFFIXES = (
    "股份有限公司", "有限责任公司", "有限公司", "集团公司", "集团", "公司",
)
_INDUSTRY_SUFFIXES = (
    "化妆品", "科技", "实业", "贸易", "电子", "食品", "药业", "家居", "服饰", "服装",
)


def _extract_brand_tokens(brand_name: str) -> list[str]:
    """从公司全称中提取用于标题匹配的品牌核心词（如 广州市海丝妍化妆品有限公司 → 海丝妍）。"""
    orig = brand_name.replace(" ", "").strip()
    if not orig:
        return []
    core = orig
    for suffix in _COMPANY_SUFFIXES:
        if core.endswith(suffix) and len(core) > len(suffix):
            core = core[:-len(suffix)]
            break
    for suffix in _INDUSTRY_SUFFIXES:
        if core.endswith(suffix) and len(core) > len(suffix) + 1:
            core = core[:-len(suffix)]
    prev = None
    while prev != core:
        prev = core
        core = re.sub(
            r"^(?:中国)?(?:[\u4e00-\u9fff]{2,10}?(?:省|市|自治区|特别行政区)|"
            r"(?:北京|上海|天津|重庆)(?:市)?)",
            "",
            core,
            count=1,
        )
    tokens: list[str] = []
    for t in (core, orig):
        if len(t) >= 2 and t not in tokens:
            tokens.append(t)

    # 拆分子词：将中文+英文混合的品牌名拆分
    # 例如 "火山全域GEO" → ["火山", "全域", "GEO"]
    sub_tokens = []
    if core and len(core) >= 4:
        # 提取连续的中文部分和英文部分
        parts = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]+', core)
        for part in parts:
            if len(part) >= 2 and part not in tokens and part not in sub_tokens:
                sub_tokens.append(part)
        # 对于较长的中文部分，进一步拆分为2字词组
        for part in parts:
            if re.match(r'^[\u4e00-\u9fff]+$', part) and len(part) >= 4:
                for i in range(0, len(part) - 1, 2):
                    sub_token = part[i:i+2]
                    if sub_token not in tokens and sub_token not in sub_tokens:
                        sub_tokens.append(sub_token)

    tokens.extend(sub_tokens)
    return tokens or [orig]


def _title_contains_brand(title: str, brand_tokens: list[str]) -> bool:
    """标题须包含至少一个品牌核心词（完整子串），禁止仅靠单字重合。"""
    title_clean = title.replace(" ", "")
    for tok in brand_tokens:
        if len(tok) >= 2 and tok in title_clean:
            return True
    return False


def _is_ugc_host(url: str) -> bool:
    host = (urlparse(url if "://" in url else "https://" + url).hostname or "").lower()
    return any(marker in host for marker in _UGC_HOST_MARKERS)


def _normalize_host(hostname: str) -> str:
    host = (hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _is_search_engine_host(url: str) -> bool:
    host = _normalize_host(
        urlparse(url if "://" in url else "https://" + url).hostname or ""
    )
    if not host:
        return False
    return any(host == se or host.endswith("." + se) for se in _SEARCH_ENGINE_HOSTS)


def _is_aggregation_title(title: str) -> bool:
    return any(marker in title for marker in _AGGREGATION_TITLE_MARKERS)


def _is_non_official_path(url: str) -> bool:
    """内页/文章/列表路径，不能当作品牌官网首页。"""
    parsed = urlparse(url if "://" in url else "https://" + url)
    path = (parsed.path or "/").lower()
    if path in ("", "/"):
        return False
    for marker in _NON_OFFICIAL_PATH_MARKERS:
        if marker.lower() in path:
            return True
    if re.match(r"^/[a-z0-9]{5,}$", path, re.I):
        return True
    if re.search(r"\.(html?|php|asp|aspx|jsp|shtml)$", path, re.I):
        segments = [s for s in path.split("/") if s]
        if len(segments) >= 1 and segments[-1] not in ("index.html", "index.htm", "default.html"):
            return True
    return path.count("/") >= 2


def _is_official_website_candidate(url: str) -> bool:
    return (
        bool(url)
        and not _is_ugc_host(url)
        and not _is_search_engine_host(url)
        and not _is_non_official_path(url)
    )


async def _synthesize_brand_answer(
    brand_name: str,
    all_results: list[dict],
    allow_llm_fallback: bool = True,
) -> dict:
    """
    规则引擎：从搜索结果中提取品牌官网。
    移植自 huoshangeo-master/app/services/agent.py 第539-837行。

    策略链：
    1. 主域名 + 官方标记 + 首页路径 → 候选集，按相关度择优
    2. 所有主域名结果中选品牌相关度最高的
    allow_llm_fallback=False 时仅返回规则结果，不触发大模型。
    """
    brand_name_clean = brand_name.replace(" ", "")
    brand_tokens = _extract_brand_tokens(brand_name)
    print(f"[Brand] 品牌核心词: {brand_tokens}", flush=True)

    # ── URL 清洗：剥离搜索引擎重定向包装 ──
    def _clean_url(url: str) -> str:
        if not url:
            return url
        if "duckduckgo.com/l/" in url and "uddg=" in url:
            from urllib.parse import parse_qs, urlparse as _up
            parsed = _up(url if "://" in url else "https://" + url)
            qs = parse_qs(parsed.query)
            uddg = qs.get("uddg", [None])[0]
            if uddg:
                return uddg
        return url

    # ── 判断域名是否为品牌官网候选 ──
    def _is_primary_domain(url: str) -> bool:
        parsed = urlparse(url if "://" in url else "https://" + url)
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False
        parts = hostname.split(".")
        if parts[0] == "www":
            parts = parts[1:]
        double_tlds = {"com.cn", "net.cn", "org.cn", "gov.cn", "co.jp", "co.uk", "com.hk"}
        if len(parts) >= 2 and ".".join(parts[-2:]) in double_tlds:
            return len(parts) == 3
        return len(parts) == 2

    # ── 解析搜索结果 ──
    parsed_results = []
    for r in all_results:
        title = r.get("title", "")
        url = _clean_url(r.get("url", ""))
        snippet = r.get("snippet", "")
        if any(kw in title for kw in ("搜索错误", "搜索失败", "配置错误", "百度搜索失败", "百度搜索", "百度被拦截")):
            continue
        if snippet and (snippet.startswith("HTTP ") or "未找到结果" in snippet):
            continue
        if not snippet:
            snippet = title
        if "百度图片" in title or url.startswith("https://image.baidu.com"):
            continue
        if any(host in url for host in (
            "tieba.baidu.com", "zhidao.baidu.com", "jingyan.baidu.com",
            "wenku.baidu.com", "map.baidu.com", "haokan.baidu.com",
        )):
            continue
        if _is_search_engine_host(url):
            continue
        if _is_aggregation_title(title):
            continue
        if _is_ugc_host(url):
            continue
        parsed_results.append({
            "title": title, "url": url, "snippet": snippet,
            "_engine": r.get("_engine", ""),
        })

    print(f"[Brand] 解析完成: 共 {len(parsed_results)} 条有效结果", flush=True)

    if not parsed_results:
        if allow_llm_fallback and config.LLM_API_KEY:
            print("[Brand][规则] 无有效搜索结果，尝试大模型平台", flush=True)
            from core.brand_llm import _llm_fallback
            llm_result = await _llm_fallback(brand_name)
            if llm_result:
                return llm_result
        return {
            "brand_name": brand_name,
            "website": "未找到",
            "description": "未能获取到该品牌信息，请尝试更换搜索词。",
            "source": "-",
            "error": "",
        }

    # ── 品牌名相关度评分 ──
    def _brand_relevance(r: dict) -> float:
        title = r["title"]
        url = r["url"]
        bn = brand_name_clean
        title_clean = title.replace(" ", "")

        score = 0.0
        if any(tok in title_clean for tok in brand_tokens if len(tok) >= 2):
            score += 10.0
        for marker in ("官网", "官方网站", "官方"):
            if marker in title:
                score += 3.0
                break
        title_match = sum(1 for ch in bn if ch in title_clean)
        if not any(tok in title_clean for tok in brand_tokens if len(tok) >= 2):
            score += title_match / max(len(bn), 1) * 2.0
        match_in_url = sum(1 for ch in bn if ch in url)
        score += match_in_url / max(len(bn), 1) * 3.0
        depth = url.count("/") - 2 if "://" in url else url.count("/")
        if depth <= 1:
            score += 0.8
        if depth > 3:
            score -= 3.0
        for seg in ("/article/", "/dy/", "/News/", "/news/", "/rain/a/",
                    "/pinpai/", "/dpfx/", "/softdown/", "/brand/",
                    "/ask/", "/question/", "/wenda/", "/qa/",
                    "/club/", "/bbs/", "/forum/", "/topic/"):
            if seg in url:
                score -= 3.0
                break
        for bad in ("十大品牌", "排行榜", "品牌排行", "评测", "测评", "排名", "对比"):
            if bad in title:
                score -= 4.0
                break
        # 无关业务关键词扣分（表明不是官网，而是第三方平台/代理商）
        _irrelevant_keywords = (
            "cps", "返利", "发单机器人", "私域群", "私域运营", "代运营",
            "招商加盟", "加盟", "代理", "分销", "淘客", "刷单", "薅羊毛",
        )
        for kw in _irrelevant_keywords:
            if kw in title or kw in r.get("snippet", ""):
                score -= 6.0
                break
        if _is_aggregation_title(title):
            score -= 8.0
        if title and title[0].isdigit():
            score -= 1.0
        _prod_pat1 = re.search(rf'{re.escape(bn)}\d', title_clean)
        _prod_pat2 = re.search(
            rf'{re.escape(bn)}(?:Pro|Max|Note|Air|Plus|Ultra|Lite|SE|GT|RS|Ace|Nova|Mate|Mix)\d?',
            title_clean, re.IGNORECASE
        )
        if _prod_pat1 or _prod_pat2:
            score -= 5.0
        # 域名拼音匹配
        try:
            from pypinyin import lazy_pinyin
            _host = (urlparse(url if '://' in url else 'https://' + url).hostname or '').lower()
            _parts = _host.split('.')
            if _parts and _parts[0] == 'www':
                _parts = _parts[1:]
            _double = {'com.cn', 'net.cn', 'org.cn', 'gov.cn', 'co.jp', 'co.uk', 'com.hk'}
            _body = ''
            if len(_parts) >= 2 and '.'.join(_parts[-2:]) in _double:
                _body = _parts[0]
            elif len(_parts) >= 2:
                _body = _parts[0]
            if _body:
                # 逐字检查：每个品牌字的拼音是否在域名中
                _pinyin_chars = lazy_pinyin(bn)
                _matched_chars = sum(1 for p in _pinyin_chars if p and p in _body)
                if _matched_chars > 0:
                    # 按比例加分：匹配字数/总字数 * 5 分
                    score += (_matched_chars / len(_pinyin_chars)) * 5.0
                # 完整拼音匹配额外加分
                _full = ''.join(_pinyin_chars).lower()
                _initial = ''.join(p[0] for p in _pinyin_chars if p).lower()
                _match_full = _full and (_full in _body or _body in _full)
                _match_initial = len(_initial) >= 2 and _initial == _body
                if _match_full or _match_initial:
                    score += 5.0  # 额外加分
        except Exception:
            pass
        return score

    MIN_BRAND_RELEVANCE = 8.0

    def _passes_brand_gate(r: dict) -> bool:
        return (
            _title_contains_brand(r["title"], brand_tokens)
            and _is_official_website_candidate(r["url"])
        )

    # 调试：打印每条结果的得分
    print(f"[Brand][调试] 共 {len(parsed_results)} 条结果进入评分:", flush=True)
    for r in parsed_results:
        score = _brand_relevance(r)
        print(f"[Brand][调试]   标题: {r['title'][:60]}  URL: {r['url'][:40]}  得分: {score:.1f}", flush=True)

    # ── 找官网 URL ──
    website = "未找到"
    website_item = None
    bn = brand_name_clean

    # 策略1: 主域名 + 官方标记 + 首页路径
    official_candidates = []
    for r in parsed_results:
        if not _is_primary_domain(r["url"]):
            continue
        if not _passes_brand_gate(r):
            continue
        if not any(m in r["title"] for m in ("官网", "官方网站", "官方")):
            continue
        url_path = r["url"]
        if any(seg in url_path for seg in (
            "/article/", "/dy/", "/News/", "/news/", "/rain/a/",
            "/pinpai/", "/dpfx/", "/softdown/", "/brand/",
            "/ask/", "/question/", "/wenda/", "/qa/",
            "/club/", "/bbs/", "/forum/", "/topic/", "/list-",
        )):
            continue
        depth = url_path.count("/") - 2 if "://" in url_path else url_path.count("/")
        if depth > 1:
            continue
        official_candidates.append(r)
    if official_candidates:
        best_official = max(official_candidates, key=_brand_relevance)
        if _brand_relevance(best_official) >= MIN_BRAND_RELEVANCE:
            website = best_official["url"]
            website_item = best_official
            print(f"[Brand] 策略1匹配(官方标记 候选{len(official_candidates)}): {best_official['title'][:50]} → {website}", flush=True)
        else:
            print(f"[Brand] 策略1跳过: 官方标记候选相关度不足", flush=True)

    # 策略2: 最佳相关度主域名（标题含品牌核心词 + 非内页路径）
    if website == "未找到":
        primary_candidates = [
            r for r in parsed_results
            if _is_primary_domain(r["url"]) and _passes_brand_gate(r)
        ]
        if primary_candidates:
            best_primary = max(primary_candidates, key=_brand_relevance)
            if _brand_relevance(best_primary) >= MIN_BRAND_RELEVANCE:
                website = best_primary["url"]
                website_item = best_primary
                print(f"[Brand] 策略2匹配(最佳相关度): {best_primary['title'][:50]} → {website}", flush=True)
            else:
                print(f"[Brand] 策略2跳过: 最高相关度 {_brand_relevance(best_primary):.1f} 低于阈值", flush=True)

    # 策略 3: URL 拼音匹配（最强信号）
    if website == "未找到":
        try:
            from pypinyin import lazy_pinyin
            _brand_pinyin = ''.join(lazy_pinyin(brand_name_clean)).lower()
            _brand_initials = ''.join(p[0] for p in lazy_pinyin(brand_name_clean) if p).lower()

            pinyin_candidates = []
            for r in parsed_results:
                if not _is_primary_domain(r["url"]):
                    continue
                if not _passes_brand_gate(r):
                    continue

                # 提取域名主体
                _host = (urlparse(r["url"] if '://' in r["url"] else 'https://' + r["url"]).hostname or '').lower()
                _parts = _host.split('.')
                if _parts and _parts[0] == 'www':
                    _parts = _parts[1:]
                _double = {'com.cn', 'net.cn', 'org.cn', 'gov.cn', 'co.jp', 'co.uk', 'com.hk'}
                _body = ''
                if len(_parts) >= 2 and '.'.join(_parts[-2:]) in _double:
                    _body = _parts[0]
                elif len(_parts) >= 2:
                    _body = _parts[0]

                if not _body:
                    continue

                # 检查域名是否匹配品牌拼音
                _match_full = _brand_pinyin and (_brand_pinyin in _body or _body in _brand_pinyin)
                _match_initial = len(_brand_initials) >= 2 and _brand_initials == _body

                if _match_full or _match_initial:
                    pinyin_candidates.append(r)

            if pinyin_candidates:
                # 拼音匹配中，选标题相关度最高的
                best_pinyin = max(pinyin_candidates, key=_brand_relevance)
                website = best_pinyin["url"]
                website_item = best_pinyin
                print(f"[Brand] 策略 3 匹配 (URL 拼音): {best_pinyin['title'][:50]} → {website}", flush=True)
        except Exception as e:
            print(f"[Brand] 策略 3 异常：{e}", flush=True)

    # ── URL 归一化：仅企业官网首页保留 scheme+host ──
    if website and website != "未找到":
        if _is_search_engine_host(website):
            print(f"[Brand] 搜索引擎域名，放弃匹配: {website}", flush=True)
            website = "未找到"
            website_item = None
        parsed = urlparse(website)
        if website != "未找到" and parsed.scheme and parsed.netloc:
            if _is_non_official_path(website):
                print(f"[Brand] 非首页路径，放弃匹配: {website}", flush=True)
                website = "未找到"
                website_item = None
            else:
                path = parsed.path or ""
                if path not in ("", "/"):
                    normalized = urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
                    if normalized != website:
                        print(f"[Brand] URL 归一化: {website} → {normalized}", flush=True)
                        website = normalized

    # ── 描述：优先官网 meta description，回退搜索 snippet ──
    description = ""
    if website and website != "未找到":
        official_desc = await _fetch_official_description(website)
        if official_desc:
            description = official_desc
            print(f"[Brand] 描述来源(官网meta): {description[:60]}", flush=True)
    if not description and website_item:
        description = website_item["snippet"]
        print(f"[Brand] 描述来源(搜索snippet回退): {website_item['title'][:40]}", flush=True)

    if website == "未找到" or not website:
        if allow_llm_fallback and config.LLM_API_KEY:
            print("[Brand][规则] 未匹配到官网，尝试大模型平台", flush=True)
            from core.brand_llm import _llm_fallback
            llm_result = await _llm_fallback(brand_name)
            if llm_result:
                return llm_result
        return {
            "brand_name": brand_name,
            "website": "未找到",
            "description": description or "未能获取到该品牌信息，请尝试更换搜索词。",
            "source": "-",
            "error": "",
        }

    return {
        "brand_name": brand_name,
        "website": website,
        "description": description,
        "source": _resolve_search_source(all_results, website, website_item) or "-",
        "error": "",
    }

# ─────────────────────────── 官网 meta description 抓取 ───────────────────────────


async def _fetch_official_description(url: str) -> str | None:
    """
    抓取官网页面提取品牌描述（权威来源）。
    回退链：meta description → og:description → title（组合）→ None。
    移植自 huoshangeo-master/app/services/agent.py 第955-1008行。
    """
    _UA = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True, headers=_UA) as c:
            r = await c.get(url)
            # 智能检测编码：优先从 HTML meta 读取，其次 Content-Type，最后尝试 GBK
            raw = r.content
            encoding = None
            # 1. 从 HTML meta charset 检测
            head = raw[:4096]
            m = re.search(rb'<meta[^>]*charset\s*=\s*["\']?([\w-]+)', head, re.IGNORECASE)
            if m:
                encoding = m.group(1).decode("ascii", errors="ignore").lower()
            # 2. 从 Content-Type 检测
            if not encoding:
                ct = r.headers.get("content-type", "")
                m2 = re.search(r'charset=([\w-]+)', ct, re.IGNORECASE)
                if m2:
                    encoding = m2.group(1).lower()
            # 3. 尝试解码
            for enc in [encoding, "utf-8", "gbk", "gb2312", "latin-1"]:
                if not enc:
                    continue
                try:
                    html = raw.decode(enc)
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            else:
                html = raw.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[Brand] 官网抓取失败 {url}: {type(e).__name__}: {e}", flush=True)
        return None

    def _extract_meta(name: str) -> str:
        for m in re.finditer(r"<meta\s[^>]*>", html, re.IGNORECASE):
            tag = m.group(0)
            if re.search(rf'(?:name|property)\s*=\s*["\']?{name}["\']?', tag, re.IGNORECASE):
                cm = re.search(r'content\s*=\s*["\']([^"\']*)["\']', tag, re.IGNORECASE)
                if cm:
                    return cm.group(1).strip()
        return ""

    def _extract_title() -> str:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else ""

    desc = _extract_meta("description")
    og = _extract_meta("og:description")
    title = _extract_title()
    print(f"[Brand] 官网页面: {url} HTML={len(html)}字 meta={len(desc)}字 og={len(og)}字 title={len(title)}字", flush=True)

    if len(desc) >= 30:
        return desc
    if len(og) >= 30:
        return og
    if desc and title:
        return f"{title}：{desc}"
    if og and title:
        return f"{title}：{og}"
    if title:
        return title
    if desc:
        return desc
    return None

def _resolve_search_source(
    all_results: list[dict],
    website_url: str = "",
    website_item: dict | None = None,
) -> str:
    """从搜索结果解析数据来源（平台名称，取自 web_search 的 _engine 字段）。"""
    if website_item and website_item.get("_engine"):
        return website_item["_engine"]
    if website_url and website_url != "未找到":
        for r in all_results:
            url = r.get("url", "")
            if url and (url in website_url or website_url in url):
                engine = r.get("_engine", "")
                if engine and engine not in ("未知", "无可用引擎"):
                    return engine
    for r in reversed(all_results):
        engine = r.get("_engine", "")
        if engine and engine not in ("未知", "无可用引擎"):
            return engine
    return ""


def _is_error_results(results: list[dict]) -> bool:
    """检查结果是否为错误消息。"""
    if not results:
        return True
    first = results[0]
    title = first.get("title", "")
    snippet = first.get("snippet", "")
    error_keywords = ("搜索错误", "搜索失败", "ratelimit", "rate limit", "配置错误", "百度被拦截", "未找到结果")
    combined = (title + snippet).lower()
    return any(kw.lower() in combined for kw in error_keywords)
