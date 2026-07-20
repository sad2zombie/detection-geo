# -*- coding: utf-8 -*-
"""Web 搜索公共工具。"""


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
