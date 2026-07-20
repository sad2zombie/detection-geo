# -*- coding: utf-8 -*-
"""Web 搜索服务 —— 百度（优先，含反风控） / Bing / 博查。

引擎实现见 core.web_engines.*；本模块只负责降级编排。
"""

from __future__ import annotations

import asyncio

import config
from core.web_engines import baidu as _baidu
from core.web_engines import bing as _bing
from core.web_engines import bocha as _bocha
from core.web_engines.common import (
    _is_error_result,
    _search_results_relevant,
    _tag_engine,
)


async def web_search(query: str, max_results: int = 5, force_engine: str = "") -> list[dict]:
    """
    执行网络搜索。
    降级链路: 百度 HTTP → 百度浏览器 → Bing HTML → Bing浏览器 → Bing API → 博查。
    force_engine 指定时跳过降级链，仅使用指定引擎。

    Returns:
        [{ "title": "...", "url": "...", "snippet": "...", "_engine": "..." }]
    """
    # ── force_engine 模式：仅使用指定引擎（百度 HTTP 失败时仍尝试浏览器版）──
    if force_engine:
        if force_engine == "baidu":
            results = await _baidu._search_baidu(query, max_results)
            if results and not _is_error_result(results) and _search_results_relevant(query, results):
                return _tag_engine(results, "百度")
            if not results or _is_error_result(results):
                print("[Baidu] HTTP 不可用，force_engine=baidu 尝试 CloakBrowser 版", flush=True)
                results = await _baidu._search_baidu_browser(query, max_results)
                if results and not _is_error_result(results) and _search_results_relevant(query, results):
                    return _tag_engine(results, "百度-浏览器")
        elif force_engine == "bing":
            results = await _bing._search_bing_html(query, max_results)
            if results and _search_results_relevant(query, results):
                return _tag_engine(results, "Bing")
        elif force_engine == "bocha":
            results = await _bocha._search_bocha(query, max_results)
            if results and not _is_error_result(results) and _search_results_relevant(query, results):
                return _tag_engine(results, "博查")
        return _tag_engine([], force_engine)

    baidu_in_cooldown = _baidu.is_in_cooldown()
    if baidu_in_cooldown:
        remain = _baidu.cooldown_remaining_seconds()
        print(f"[Search] 百度冷却中，跳过百度（剩余{remain}s）", flush=True)

    # ── 1. 百度搜索（优先，被风控时重试 1 次） ──
    if not baidu_in_cooldown:
        results = await _baidu._search_baidu(query, max_results)
        if results and not _is_error_result(results) and _search_results_relevant(query, results):
            return _tag_engine(results, "百度")
        if results and not _is_error_result(results):
            print("[Search] 百度 HTTP 结果与查询不相关，继续降级", flush=True)

        print("[Search] 百度第1次被拦截，等待3s后重试", flush=True)
        await asyncio.sleep(3)
        results = await _baidu._search_baidu(query, max_results)
        if results and not _is_error_result(results) and _search_results_relevant(query, results):
            return _tag_engine(results, "百度")
        if results and not _is_error_result(results):
            print("[Search] 百度 HTTP 重试结果仍不相关，尝试浏览器版", flush=True)

        # HTTP 百度失败，尝试 CloakBrowser 版百度
        print("[Search] HTTP百度被拦截，尝试CloakBrowser版", flush=True)
        results = await _baidu._search_baidu_browser(query, max_results)
        if results and not _is_error_result(results) and _search_results_relevant(query, results):
            return _tag_engine(results, "百度-浏览器")
        if results and not _is_error_result(results):
            print("[Search] 百度浏览器版结果不相关，继续降级", flush=True)

        await _baidu.enter_cooldown()
        print(f"[Search] 百度连续被拦截，进入冷却期 {_baidu.BAIDU_COOLDOWN_SECONDS}s", flush=True)

    # ── 2. Bing HTML 搜索（百度不可用时降级，无需 API Key） ──
    results = await _bing._search_bing_html(query, max_results)
    if results and not _is_error_result(results) and _search_results_relevant(query, results):
        return _tag_engine(results, "Bing")

    # ── 2.5 Bing 浏览器版（HTTP 版结果不相关时降级） ──
    print("[Search] Bing HTTP 结果不理想，尝试CloakBrowser版", flush=True)
    results = await _bing._search_bing_browser(query, max_results)
    if results and not _is_error_result(results) and _search_results_relevant(query, results):
        return _tag_engine(results, "Bing-浏览器")

    # ── 3. Bing API 搜索（如有 API Key） ──
    if config.BING_API_KEY:
        results = await _bing._search_bing(query, max_results)
        if results and not _is_error_result(results) and _search_results_relevant(query, results):
            return _tag_engine(results, "Bing-API")

    # ── 4. 博查 AI 搜索（最终降级） ──
    if config.BOCHA_API_KEY:
        results = await _bocha._search_bocha(query, max_results)
        if results and not _is_error_result(results) and _search_results_relevant(query, results):
            return _tag_engine(results, "博查")
        if results and not _is_error_result(results):
            print("[Search] 博查结果与查询不相关", flush=True)
        print("[Search] 博查搜索失败", flush=True)

    return _tag_engine([], "无可用引擎")
