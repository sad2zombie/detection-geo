# -*- coding: utf-8 -*-
"""品牌官网大模型查询。"""

from __future__ import annotations

import logging

import json
import re
import httpx
from urllib.parse import urlparse, urlunparse

from core.llm_client import llm_chat
from core.brand_rules import _is_search_engine_host, _is_ugc_host

logger = logging.getLogger(__name__)

SOURCE_LLM = "大模型"

_LLM_BRAND_SYSTEM_PROMPT = (
    "你是一个品牌信息查询助手。用户会给你一个品牌名称，"
    "请你输出相关品牌信息，品牌的官方网站URL和简要介绍。\n"
    "要求：\n"
    "1. 不要编造结果，不确定或者没有证据的都需要如实回答\n"
    "2. 返回的域名必须完整（如：www.xxx.com），而且域名中的xxx不可能为中文\n"
    "3. 不能返回空结果，只能返回JSON格式：{\"brand_name\": \"...\", \"website\": \"...\", \"description\": \"...\"}"
)


_LLM_NOT_FOUND_MARKERS = frozenset({
    "未找到", "无", "未知", "没有", "查不到", "无法确定",
    "n/a", "null", "none", "not found", "unknown",
})


def _is_llm_not_found(website: str) -> bool:
    """模型明确表示未找到官网（含空值）。"""
    if not website or not website.strip():
        return True
    return website.strip().lower() in _LLM_NOT_FOUND_MARKERS


def _is_valid_llm_website(website: str) -> bool:
    """校验大模型返回的官网 URL，拒绝中文域名和明显无效格式。"""
    if _is_llm_not_found(website):
        return False
    url = website.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    if re.search(r"[\u4e00-\u9fff]", host):
        return False
    if _is_ugc_host(url) or _is_search_engine_host(url):
        return False
    return bool(re.match(
        r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$",
        host,
    ))


def _normalize_llm_website(website: str) -> str:
    """补全 scheme，去掉路径，归一化为首页 URL。"""
    url = website.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
    return url


async def _verify_page_reachable(website: str) -> bool:
    """URL 可达性验证：访问 URL，能拿到响应就算通过。"""
    url = website.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    _UA = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
            resp = await client.get(url, headers=_UA)
            if resp.status_code < 400:
                logger.info(f"[Brand][验证] URL可达: {url} (status={resp.status_code})")
                return True
            if resp.status_code in (403, 429):
                logger.warning(f"[Brand][验证] URL被拦截但存在: {url} (status={resp.status_code})")
                return True
            logger.warning(f"[Brand][验证] URL不可达: {url} (status={resp.status_code})")
            return False

    except httpx.TimeoutException:
        logger.warning(f"[Brand][验证] 页面超时: {url}")
        return False
    except Exception as e:
        logger.error(f"[Brand][验证] 页面请求失败: {url} ({e})")
        return False


async def _llm_query_once(brand_name: str, query: str) -> tuple[dict | None, bool]:
    """单次大模型品牌官网查询。

    Returns:
        (result, stop): stop=True 表示模型明确未找到，无需再换问法查询。
    """
    response = await llm_chat(
        messages=[
            {"role": "system", "content": _LLM_BRAND_SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ],
        max_tokens=2000,
        temperature=0,
        extra_body={"enable_search": True},
    )

    content = response.get("content", "").strip()
    json_match = re.search(r'\{[^{}]+\}', content)
    if not json_match:
        logger.warning(f"[Brand][大模型] 返回格式异常 (query={query!r}): {content[:200]}")
        return None, False

    data = json.loads(json_match.group())
    website = (data.get("website") or "").strip()
    description = (data.get("description") or "").strip()
    if _is_llm_not_found(website):
        logger.info(f"[Brand][大模型] 未找到 (query={query!r})")
        return None, True

    if not _is_valid_llm_website(website):
        logger.warning(f"[Brand][大模型] 无效官网已丢弃 (query={query!r}): {website!r}")
        return None, False

    # URL 可达性验证：能访问就算通过
    reachable = await _verify_page_reachable(website)
    if not reachable:
        logger.warning(f"[Brand][大模型] 验证未通过 (query={query!r}): {website!r}")
        return None, False

    website = _normalize_llm_website(website)
    logger.info(f"[Brand][大模型] 命中 (query={query!r}): {website}")
    return {
        "brand_name": brand_name,
        "website": website,
        "description": description,
        "source": SOURCE_LLM,
        "error": "",
    }, False


async def _llm_fallback(brand_name: str) -> dict | None:
    """各搜索平台均未命中时，调用大模型直接回答品牌官网。"""
    queries = [
        f"{brand_name}的官网",
        f"{brand_name} 官方网站",
        brand_name,
    ]
    try:
        for query in queries:
            logger.info(f"[Brand][大模型] 查询: {query}")
            result, stop = await _llm_query_once(brand_name, query)
            if result:
                return result
            if stop:
                logger.warning("[Brand][大模型] 模型返回未找到，跳过后续大模型查询")
                break
    except Exception as e:
        logger.error(f"[Brand][大模型] 调用失败: {e}")
    return None
