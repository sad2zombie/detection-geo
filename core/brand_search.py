# -*- coding: utf-8 -*-
"""品牌官网查询（一级信源）—— 大模型优先 + 分平台降级 + 规则提取。

核心流程（与实现一致）：
1. 大模型优先（需 LLM_API_KEY）
2. 查询「品牌名」/「品牌名官网」/「品牌名品牌」：百度 → Bing → 博查，每次立即规则匹配
"""

from __future__ import annotations

import config
from core.brand_llm import SOURCE_LLM, _llm_fallback
from core.brand_rules import _is_error_results, _synthesize_brand_answer
from core.web_search import web_search

# ── 结果缓存（与 search_engine.py 的缓存机制对齐）──
_brand_result_cache: dict | None = None

_SEARCH_SUFFIXES = ("官网", "品牌")

__all__ = ["SOURCE_LLM", "search_brand", "get_cached_brand_result"]


async def search_brand(brand_name: str) -> dict:
    """
    品牌官网查询主入口。

    返回:
        {
            "brand_name": "西屋",
            "website": "https://www.westinghouse.com.cn",
            "description": "西屋电气是一家...",
            "source": "百度" | "Bing" | "博查" | SOURCE_LLM | "-",
            "error": ""
        }
    """
    global _brand_result_cache

    result = await _pipeline_search(brand_name)
    _brand_result_cache = result
    return result


def get_cached_brand_result() -> dict | None:
    return _brand_result_cache


async def _pipeline_search(brand_name: str) -> dict:
    """查询流水线：先大模型 → 再搜索平台（百度 → Bing → 博查），每个平台逐查询词匹配。"""
    print(f"[Brand] 开始查询品牌官网: {brand_name}", flush=True)

    # ── 阶段 1：大模型优先 ──
    if config.LLM_API_KEY:
        print("[Brand] ── 阶段 大模型（优先） ──", flush=True)
        llm_result = await _llm_fallback(brand_name)
        if llm_result and llm_result.get("website") and llm_result["website"] != "未找到":
            print(f"[Brand] 大模型命中官网: {llm_result['website']}", flush=True)
            return llm_result
        print("[Brand] 大模型未命中，进入搜索平台阶段", flush=True)
    else:
        print("[Brand] LLM_API_KEY 未配置，跳过大模型阶段", flush=True)

    # ── 阶段 2：搜索平台降级链 ──
    stages: list[tuple[str, str]] = [
        ("百度", "baidu"),
        ("Bing", "bing"),
    ]
    if config.BOCHA_API_KEY:
        stages.append(("博查", "bocha"))
    else:
        print("[Brand] BOCHA_API_KEY 未配置，跳过博查阶段", flush=True)

    for query in [brand_name] + [f"{brand_name}{s}" for s in _SEARCH_SUFFIXES]:
        print(f"[Brand] ── 查询: {query} ──", flush=True)
        for platform_label, engine in stages:
            print(f"[Brand][{platform_label}] 搜索: {query}", flush=True)
            results = await web_search(query, max_results=5, force_engine=engine)
            if results and not _is_error_results(results):
                engine_tag = results[0].get("_engine", platform_label)
                print(f"[Brand][{platform_label}] 完成: {len(results)} 条有效结果 (_engine={engine_tag})", flush=True)
                result = await _synthesize_brand_answer(brand_name, results, allow_llm_fallback=False)
                if result.get("website") and result["website"] != "未找到":
                    print(
                        f"[Brand] 在 {platform_label} 命中官网: {result['website']} "
                        f"(来源: {result.get('source', '-')})",
                        flush=True,
                    )
                    return result
            else:
                print(f"[Brand][{platform_label}] 完成: 0 条有效结果", flush=True)
        print(f"[Brand] 查询 '{query}' 未命中，进入下一个查询", flush=True)

    print("[Brand] 所有阶段均未找到官网", flush=True)
    return {
        "brand_name": brand_name,
        "website": "未找到",
        "description": "未能获取到该品牌信息，请尝试更换搜索词。",
        "source": "-",
        "error": "",
    }
