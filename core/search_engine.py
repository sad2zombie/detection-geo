# -*- coding: utf-8 -*-
"""搜索调度器 — 管理多平台搜索执行（异步版本）+ 品牌匹配分析"""

import asyncio
import json
from datetime import datetime

from platforms import get_platform
from platforms.base import SearchResult
from config import RESULTS_DIR, ENABLED_PLATFORM_KEYS, filter_platform_keys


class DetectBusyError(Exception):
    """已有 detect 任务在执行，拒绝并发请求。"""


_detect_running = False
_detect_current_platform: str | None = None
_detect_state_lock: asyncio.Lock | None = None


def _get_detect_state_lock() -> asyncio.Lock:
    global _detect_state_lock
    if _detect_state_lock is None:
        _detect_state_lock = asyncio.Lock()
    return _detect_state_lock


def is_detect_busy() -> bool:
    """是否有检测流程正在执行（/api/detect、任务管理、消费拉取共用）。"""
    return _detect_running


def get_detect_current_platform() -> str | None:
    """当前正在检测的平台 key；无检测时为 None。"""
    return _detect_current_platform


def is_platform_detect_busy(platform_key: str) -> bool:
    """指定平台是否正在执行检测。"""
    return _detect_running and _detect_current_platform == platform_key


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


# ============================================================
# 各平台预处理：过滤 → 按品牌相似度排序 → 精简字段
# ============================================================

def _brand_name_similarity(brand: str, name: str) -> float:
    """品牌名与账号名的相似度评分（越高越相关）。"""
    bn = brand.replace(" ", "").strip().lower()
    nc = name.replace(" ", "").strip().lower()
    if not bn or not nc:
        return 0.0
    if bn == nc:
        return 100.0
    if bn in nc:
        idx = nc.find(bn)
        pos_bonus = max(0, 10 - idx)
        return 85.0 + len(bn) / max(len(nc), 1) * 10 + pos_bonus
    if nc in bn:
        return 75.0 + len(nc) / max(len(bn), 1) * 10
    matched = 0
    for ch in bn:
        if ch in nc:
            matched += 1
    ordered = 0
    ni = 0
    for ch in bn:
        while ni < len(nc):
            if nc[ni] == ch:
                ordered += 1
                ni += 1
                break
            ni += 1
    overlap_score = matched / len(bn) * 35
    order_score = ordered / len(bn) * 25
    return overlap_score + order_score


def _user_sort_key(u: dict, brand: str) -> tuple:
    """主排序：品牌相似度；次排序：粉丝数、获赞数。"""
    sim = _brand_name_similarity(brand, u.get("name", ""))
    fc = _parse_follower_count(u.get("follower_count"))
    lc = _parse_follower_count(u.get("like_count"))
    return (sim, fc if fc is not None else -1, lc if lc is not None else -1)


def _preprocess_douyin_users(users: list[dict], brand: str) -> list[dict] | None:
    """抖音：过滤蓝V → 按品牌名相似度排序 → 取前20 → 精简字段 → URL脱敏"""
    blue_v_users = [u for u in users if u.get("verification") == "蓝V"]
    if not blue_v_users:
        return None

    blue_v_users.sort(key=lambda u: _user_sort_key(u, brand), reverse=True)

    result = []
    for u in blue_v_users[:20]:
        url = u.get("profile_url", "")
        if "?" in url:
            url = url.split("?")[0]
        result.append({
            "name": u.get("name", ""),
            "profile_url": url,
            "account_id": u.get("douyin_id", ""),
        })
    return result


def _preprocess_xhs_users(users: list[dict], brand: str) -> list[dict] | None:
    """小红书：过滤企业认证 → 按品牌名相似度排序 → 取前20 → 精简字段 → URL脱敏"""
    verified_users = [u for u in users if u.get("verification") == "企业认证"]
    if not verified_users:
        return None

    verified_users.sort(key=lambda u: _user_sort_key(u, brand), reverse=True)

    result = []
    for u in verified_users[:20]:
        url = u.get("profile_url", "")
        if "?" in url:
            url = url.split("?")[0]
        result.append({
            "name": u.get("name", ""),
            "profile_url": url,
            "account_id": u.get("xhs_id", ""),
        })
    return result


def _preprocess_jd_users(users: list[dict], brand: str) -> dict | None:
    """京东：先匹配品牌名，再匹配"官方旗舰店"，取第一个匹配"""
    brand_users = [u for u in users if brand.replace(" ", "").lower() in u.get("name", "").replace(" ", "").lower()]
    official = [u for u in brand_users if "官方旗舰店" in u.get("name", "")]
    if not official:
        return None
    u = official[0]
    url = u.get("profile_url", "")
    if "?" in url:
        url = url.split("?")[0]
    return {"platform": "jd", "name": u.get("name", ""), "profile_url": url}


def _preprocess_taobao_users(users: list[dict], brand: str) -> dict | None:
    """淘宝：先匹配品牌名，再匹配"官方旗舰店"，取第一个匹配"""
    brand_users = [u for u in users if brand.replace(" ", "").lower() in u.get("name", "").replace(" ", "").lower()]
    official = [u for u in brand_users if "官方旗舰店" in u.get("name", "")]
    if not official:
        return None
    u = official[0]
    url = u.get("profile_url", "")
    if "?" in url:
        url = url.split("?")[0]
    return {"platform": "taobao", "name": u.get("name", ""), "profile_url": url}


# ============================================================
# 百度品牌匹配分析
# ============================================================

def analyze_brand_result(brand: str, users: list[dict]) -> dict:
    """用 brand 对 users 中的 name 或 description 做子串匹配，任意一个命中计1分。

    返回值示例：``{"platform": "baidu", "score": 85, "assessment_grade": "中高"}``
    """
    total = len(users)
    matched = sum(
        1 for u in users
        if brand.replace(" ", "").lower() in u.get("name", "").replace(" ", "").lower()
        or brand.replace(" ", "").lower() in u.get("description", "").replace(" ", "").lower()
    )
    score = round(matched / total * 100) if total > 0 else 0

    if score >= 90:
        grade = "优"
    elif score >= 75:
        grade = "良"
    elif score >= 60:
        grade = "中"
    else:
        grade = "差"

    return {
        "platform": "baidu",
        "score": score,
        "assessment_grade": grade,
    }


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


def _wrap_platform_result(platform: str, data: dict) -> dict:
    return {"platform": platform, "data": data}


def _format_detect_errors(errors: list | None) -> str:
    if not errors:
        return ""
    parts: list[str] = []
    for e in errors:
        platform = e.get("platform", "")
        message = str(e.get("message", "") or "").strip()
        if not message:
            continue
        parts.append(f"{platform}: {message}" if platform else message)
    return "; ".join(parts)


def _baidu_score_str(score) -> str:
    if score == "" or score is None:
        return ""
    try:
        return str(int(score))
    except (TypeError, ValueError):
        return str(score)


def _empty_platform_result(platform: str, brand: str) -> dict:
    """单平台无数据时的空结构（对接契约）。"""
    if platform == "official_website":
        return _wrap_platform_result("official_website", {
            "brand_name": brand,
            "website": "",
            "description": "",
        })
    if platform == "douyin":
        return _wrap_platform_result("douyin", {"users": []})
    if platform == "xiaohongshu":
        return _wrap_platform_result("xiaohongshu", {"users": []})
    if platform == "baidu":
        return _wrap_platform_result("baidu", {"score": "", "assessment_grade": ""})
    return _wrap_platform_result(platform, {})


def _platform_result_from_cache(platform: str, brand: str) -> dict:
    """从缓存构建单平台结果；无缓存或预处理为空则返回空结构。"""
    if platform == "official_website":
        ow = preprocessed_cache.get("official_website")
        if ow:
            return _wrap_platform_result("official_website", {
                "brand_name": ow.get("brand_name", brand),
                "website": ow.get("website", ""),
                "description": ow.get("description", ""),
            })
        return _empty_platform_result(platform, brand)

    if platform == "douyin":
        dy = preprocessed_cache.get("douyin")
        return _wrap_platform_result("douyin", {"users": dy if dy else []})

    if platform == "xiaohongshu":
        xhs = preprocessed_cache.get("xiaohongshu")
        return _wrap_platform_result("xiaohongshu", {"users": xhs if xhs else []})

    if platform == "baidu":
        bd = analysis_cache.get("baidu")
        if bd:
            return _wrap_platform_result("baidu", {
                "score": _baidu_score_str(bd.get("score", "")),
                "assessment_grade": bd.get("assessment_grade", "") or "",
            })
        return _empty_platform_result(platform, brand)

    return _empty_platform_result(platform, brand)


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
        "errors": _format_detect_errors(err_list),
    }


async def detect_brand_async(
    keyword: str,
    platform_key: str,
    task_id: str = "",
) -> dict:
    """detect 入口：每次只检测一个平台。"""
    global _detect_running, _detect_current_platform
    from config import DETECT_TOTAL_TIMEOUT_SECONDS, DETECT_PLATFORM_TIMEOUT_SECONDS, normalize_platform

    platform_key = normalize_platform(platform_key)

    async with _get_detect_state_lock():
        if _detect_running:
            raise DetectBusyError()
        _detect_running = True
        _detect_current_platform = platform_key

    try:
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
    finally:
        async with _get_detect_state_lock():
            _detect_running = False
            _detect_current_platform = None


def _preprocess_official_website(users: list[dict]) -> dict | None:
    """官网：提取品牌名、官网URL、简介"""
    if not users:
        return None
    u = users[0]
    return {
        "platform": "official_website",
        "brand_name": u.get("name", ""),
        "website": u.get("profile_url", ""),
        "description": u.get("description", ""),
        "source": u.get("source", ""),
    }


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
                    preprocessed_cache["douyin"] = _preprocess_douyin_users(result["users"], keyword)
                elif key == "xiaohongshu":
                    preprocessed_cache["xiaohongshu"] = _preprocess_xhs_users(result["users"], keyword)
                elif key == "jd":
                    preprocessed_cache["jd"] = _preprocess_jd_users(result["users"], keyword)
                elif key == "taobao":
                    preprocessed_cache["taobao"] = _preprocess_taobao_users(result["users"], keyword)
                elif key == "baidu":
                    analysis_cache["baidu"] = analyze_brand_result(keyword, result["users"])
                elif key == "official_website":
                    preprocessed_cache["official_website"] = _preprocess_official_website(result["users"])

            filepath = _save_result(key, keyword, result)
            result["saved_to"] = filepath
            results.append(result)
        except asyncio.TimeoutError:
            print(f"[Search] {key} 平台检测超时（{int(platform_timeout)}秒）", flush=True)
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
            results.append(_wrap_platform_result("official_website", {
                "brand_name": ow.get("brand_name", brand),
                "website": ow.get("website", ""),
                "description": ow.get("description", ""),
            }))
        else:
            results.append(_wrap_platform_result("official_website", {
                "brand_name": brand,
                "website": "未找到",
                "description": "",
            }))

    if "douyin" in preprocessed_cache:
        dy_data = preprocessed_cache.get("douyin")
        results.append(_wrap_platform_result("douyin", {"users": dy_data if dy_data else []}))

    if "xiaohongshu" in preprocessed_cache:
        xhs_data = preprocessed_cache.get("xiaohongshu")
        results.append(_wrap_platform_result("xiaohongshu", {"users": xhs_data if xhs_data else []}))

    if "baidu" in analysis_cache:
        bd = analysis_cache["baidu"]
        results.append(_wrap_platform_result("baidu", {
            "score": _baidu_score_str(bd.get("score", "")),
            "assessment_grade": bd.get("assessment_grade", "") or "",
        }))

    return {
        "task_id": task_id,
        "brand": brand,
        "status": "succeed",
        "results": results,
        "errors": "",
    }