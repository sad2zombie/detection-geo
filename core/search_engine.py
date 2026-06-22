# -*- coding: utf-8 -*-
"""搜索调度器 — 管理多平台搜索执行（异步版本）"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

from platforms import get_platform
from platforms.base import SearchResult
from config import RESULTS_DIR


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


async def search_platforms_async(keyword: str, platform_keys: list[str]) -> list[SearchResult]:
    """异步执行多平台搜索（顺序执行，避免共享 browser_manager 单例时并发抢锁）

    若需要真正并发，可改为每个平台使用独立的 BrowserManager 实例。
    """
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
            result = await platform.search(keyword)
            filepath = _save_result(key, keyword, result)
            result["saved_to"] = filepath
            results.append(result)
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
