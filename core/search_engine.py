# -*- coding: utf-8 -*-
"""搜索调度器 — 多平台搜索编排 + detect 入口（匹配/忙锁已拆出）。"""

import logging

import asyncio
import json
from datetime import datetime

from platforms import get_platform
from platforms.base import SearchResult
from config import RESULTS_DIR, ENABLED_PLATFORM_KEYS, filter_platform_keys
from core.brand_match import (
    analyze_brand_result,
    preprocess_douyin_users,
    preprocess_jd_users,
    preprocess_official_website,
    preprocess_taobao_users,
    preprocess_xhs_users,
)
from core.detect_guard import (  # noqa: F401 — 兼容旧 import 路径
    DetectBusyError,
    detect_slot,
    get_detect_current_platform,
    is_detect_busy,
    is_platform_detect_busy,
)
from core.detect_result import (
    baidu_score_str,
    empty_platform_result,
    format_detect_errors,
    wrap_platform_result,
)

logger = logging.getLogger(__name__)


# ============================================================
# 全局缓存（搜索调度时填充，分析接口读取）
# ============================================================
# 全局预处理结果缓存（平台名 → 预处理后用户列表）
preprocessed_cache: dict[str, list[dict] | None] = {}

# 全局记录最近一次搜索关键词
_last_keyword: str = ""

# 百度品牌匹配分析结果
analysis_cache: dict[str, dict] = {}

# 一级信源：品牌官网查询结果
brand_website_cache: dict | None = None

# 对外 detect / Kafka 固定返回的平台及顺序
DETECT_PLATFORM_ORDER = ENABLED_PLATFORM_KEYS


def _reset_analysis_caches() -> None:
    """每次搜索前清空，避免上次结果污染。"""
    preprocessed_cache.clear()
    analysis_cache.clear()


def _platform_result_from_cache(platform: str, brand: str) -> dict:
    """从缓存构建单平台结果；无缓存或预处理为空则返回空结构。"""
    if platform == "official_website":
        ow = preprocessed_cache.get("official_website")
        if ow:
            return wrap_platform_result("official_website", {
                "brand_name": ow.get("brand_name", brand),
                "website": ow.get("website", ""),
                "description": ow.get("description", ""),
            })
        return empty_platform_result(platform, brand)

    if platform == "douyin":
        dy = preprocessed_cache.get("douyin")
        return wrap_platform_result("douyin", {"users": dy if dy else []})

    if platform == "xiaohongshu":
        xhs = preprocessed_cache.get("xiaohongshu")
        return wrap_platform_result("xiaohongshu", {"users": xhs if xhs else []})

    if platform == "baidu":
        bd = analysis_cache.get("baidu")
        if bd:
            return wrap_platform_result("baidu", {
                "score": baidu_score_str(bd.get("score", "")),
                "assessment_grade": bd.get("assessment_grade", "") or "",
            })
        return empty_platform_result(platform, brand)

    return empty_platform_result(platform, brand)


def build_detect_response(
    brand: str,
    task_id: str,
    errors: list | None = None,
    status: str = "succeed",
    platform_key: str = "",
) -> dict:
    """构建对外 detect / Kafka 响应；results 为单个平台对象。"""
    err_list = errors or []
    if status not in ("succeed", "failed"):
        status = "failed" if err_list else "succeed"
    if not platform_key:
        raise ValueError("platform_key 不能为空")
    return {
        "task_id": task_id,
        "brand": brand,
        "status": status,
        "results": _platform_result_from_cache(platform_key, brand),
        "errors": format_detect_errors(err_list),
    }


async def detect_brand_async(
    keyword: str,
    platform_key: str,
    task_id: str = "",
) -> dict:
    """detect 入口：每次只检测一个平台。"""
    from config import DETECT_TOTAL_TIMEOUT_SECONDS, DETECT_PLATFORM_TIMEOUT_SECONDS, normalize_platform

    platform_key = normalize_platform(platform_key)

    async with detect_slot(platform_key):
        errors: list[dict] = []
        try:
            async with asyncio.timeout(DETECT_TOTAL_TIMEOUT_SECONDS):
                search_results = await search_platforms_async(
                    keyword,
                    [platform_key],
                    platform_timeout=DETECT_PLATFORM_TIMEOUT_SECONDS,
                )
        except TimeoutError:
            errors.append({
                "platform": platform_key,
                "message": f"检测超时（{DETECT_TOTAL_TIMEOUT_SECONDS}秒）",
            })
            return build_detect_response(
                keyword, task_id, errors, status="failed", platform_key=platform_key
            )

        errors = [
            {"platform": r["platform"], "message": r["error"]}
            for r in search_results
            if r.get("error")
        ]
        status = "failed" if errors else "succeed"
        return build_detect_response(
            keyword, task_id, errors, status=status, platform_key=platform_key
        )


def _save_result(platform_key: str, brand: str, result: dict) -> str:
    """保存搜索结果到磁盘"""
    platform_dir = RESULTS_DIR / platform_key
    platform_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    safe_brand = "".join(c for c in brand if c.isalnum() or c in "._- ").strip()[:50]
    filename = f"{date_str}_{safe_brand}.json"
    filepath = platform_dir / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return str(filepath)


async def search_platforms_async(
    keyword: str,
    platform_keys: list[str],
    platform_timeout: float | None = None,
) -> list[SearchResult]:
    """异步执行多平台搜索（顺序执行，避免共享 browser_manager 单例时并发抢锁）。

    Args:
        platform_timeout: 单平台超时秒数；None 表示不限制（前端 /api/search 用）。
    """
    global _last_keyword
    _reset_analysis_caches()
    _last_keyword = keyword
    results: list[SearchResult] = []

    for key in platform_keys:
        platform = get_platform(key)
        if platform is None:
            results.append({
                "brand": keyword,
                "platform": key,
                "platform_name": key,
                "search_url": "",
                "total_found": 0,
                "users": [],
                "error": f"不支持的平台: {key}",
            })
            continue
        try:
            if platform_timeout:
                result = await asyncio.wait_for(
                    platform.search(keyword),
                    timeout=platform_timeout,
                )
            else:
                result = await platform.search(keyword)

            # 按平台执行对应的预处理，并写入缓存
            if not result.get("error") and result.get("users"):
                if key == "douyin":
                    preprocessed_cache["douyin"] = preprocess_douyin_users(result["users"], keyword)
                elif key == "xiaohongshu":
                    preprocessed_cache["xiaohongshu"] = preprocess_xhs_users(result["users"], keyword)
                elif key == "jd":
                    preprocessed_cache["jd"] = preprocess_jd_users(result["users"], keyword)
                elif key == "taobao":
                    preprocessed_cache["taobao"] = preprocess_taobao_users(result["users"], keyword)
                elif key == "baidu":
                    analysis_cache["baidu"] = analyze_brand_result(keyword, result["users"])
                elif key == "official_website":
                    preprocessed_cache["official_website"] = preprocess_official_website(result["users"])

            filepath = _save_result(key, keyword, result)
            result["saved_to"] = filepath
            results.append(result)
        except asyncio.TimeoutError:
            logger.warning(f"[Search] {key} 平台检测超时（{int(platform_timeout)}秒）")
            results.append({
                "brand": keyword,
                "platform": key,
                "platform_name": platform.platform_name,
                "search_url": "",
                "total_found": 0,
                "users": [],
                "error": f"平台检测超时（{int(platform_timeout)}秒）",
            })
        except Exception as e:
            results.append({
                "brand": keyword,
                "platform": key,
                "platform_name": platform.platform_name,
                "search_url": "",
                "total_found": 0,
                "users": [],
                "error": str(e),
            })
        finally:
            try:
                await platform.close()
            except Exception:
                pass

    return results


def get_aggregated_analysis() -> dict:
    """聚合所有平台的分析结果（统一返回给前端）。"""
    import uuid

    task_id = str(uuid.uuid4())[:8]
    brand = _last_keyword
    results: list = []

    if "official_website" in preprocessed_cache:
        ow = preprocessed_cache.get("official_website")
        if ow:
            results.append(wrap_platform_result("official_website", {
                "brand_name": ow.get("brand_name", brand),
                "website": ow.get("website", ""),
                "description": ow.get("description", ""),
            }))
        else:
            results.append(wrap_platform_result("official_website", {
                "brand_name": brand,
                "website": "未找到",
                "description": "",
            }))

    if "douyin" in preprocessed_cache:
        dy_data = preprocessed_cache.get("douyin")
        results.append(wrap_platform_result("douyin", {"users": dy_data if dy_data else []}))

    if "xiaohongshu" in preprocessed_cache:
        xhs_data = preprocessed_cache.get("xiaohongshu")
        results.append(wrap_platform_result("xiaohongshu", {"users": xhs_data if xhs_data else []}))

    if "baidu" in analysis_cache:
        bd = analysis_cache["baidu"]
        results.append(wrap_platform_result("baidu", {
            "score": baidu_score_str(bd.get("score", "")),
            "assessment_grade": bd.get("assessment_grade", "") or "",
        }))

    return {
        "task_id": task_id,
        "brand": brand,
        "status": "succeed",
        "results": results,
        "errors": "",
    }