# -*- coding: utf-8 -*-
"""搜索调度器 — 管理多平台搜索执行（异步版本）"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

from platforms import get_platform
from platforms.base import SearchResult
from config import RESULTS_DIR


def _parse_follower_count(raw: str | int | float | None) -> float | None:
    """解析粉丝数字符串，返回浮点数或 None（无法解析时）"""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if "万" in s:
        try:
            return float(s.replace("万", "")) * 10000
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def _preprocess_douyin_users(users: list[dict]) -> list[dict]:
    """抖音预处理：过滤蓝V → 按粉丝数降序 → 取前3 → 精简字段 → URL脱敏"""
    blue_v_users = [u for u in users if u.get("verification") == "蓝V"]

    def sort_key(u: dict):
        fc = _parse_follower_count(u.get("follower_count"))
        lc = _parse_follower_count(u.get("like_count"))
        return (fc if fc is not None else -1, lc if lc is not None else -1)

    blue_v_users.sort(key=sort_key, reverse=True)

    result = []
    for u in blue_v_users[:3]:
        url = u.get("profile_url", "")
        if "?" in url:
            url = url.split("?")[0]
        result.append({
            "name": u.get("name", ""),
            "profile_url": url,
            "douyin_id": u.get("douyin_id", ""),
        })
    return result


def _preprocess_xhs_users(users: list[dict]) -> list[dict]:
    """小红书预处理：过滤企业认证 → 按粉丝数降序 → 取前3 → 精简字段 → URL脱敏"""
    verified_users = [u for u in users if u.get("verification") == "企业认证"]

    def sort_key(u: dict):
        fc = _parse_follower_count(u.get("follower_count"))
        lc = _parse_follower_count(u.get("like_count"))
        return (fc if fc is not None else -1, lc if lc is not None else -1)

    verified_users.sort(key=sort_key, reverse=True)

    result = []
    for u in verified_users[:3]:
        url = u.get("profile_url", "")
        if "?" in url:
            url = url.split("?")[0]
        result.append({
            "name": u.get("name", ""),
            "profile_url": url,
            "xhs_id": u.get("xhs_id", ""),
        })
    return result


# 全局预处理结果缓存（平台名 → 预处理后用户列表）
preprocessed_cache: dict[str, list[dict]] = {}


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
            if key == "douyin" and not result.get("error") and result.get("users"):
                preprocessed_cache["douyin"] = _preprocess_douyin_users(result["users"])
            elif key == "xiaohongshu" and not result.get("error") and result.get("users"):
                preprocessed_cache["xiaohongshu"] = _preprocess_xhs_users(result["users"])
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
