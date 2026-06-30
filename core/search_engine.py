# -*- coding: utf-8 -*-
"""搜索调度器 — 管理多平台搜索执行（异步版本）+ 品牌匹配分析"""

import asyncio
import json
from datetime import datetime

from platforms import get_platform
from platforms.base import SearchResult
from config import RESULTS_DIR


class DetectBusyError(Exception):
    """已有 detect 任务在执行，拒绝并发请求。"""


_detect_running = False
_detect_state_lock: asyncio.Lock | None = None


def _get_detect_state_lock() -> asyncio.Lock:
    global _detect_state_lock
    if _detect_state_lock is None:
        _detect_state_lock = asyncio.Lock()
    return _detect_state_lock


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
# 各平台预处理：brand 匹配 → 过滤 → 排序 → 精简字段
# ============================================================

def _preprocess_douyin_users(users: list[dict], brand: str) -> list[dict] | None:
    """抖音：先匹配品牌名 → 过滤蓝V → 按粉丝数降序 → 取前3 → 精简字段 → URL脱敏"""
    brand_users = [u for u in users if brand.replace(" ", "").lower() in u.get("name", "").replace(" ", "").lower()]
    blue_v_users = [u for u in brand_users if u.get("verification") == "蓝V"]
    if not blue_v_users:
        return None

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
            "platform": "douyin",
            "name": u.get("name", ""),
            "profile_url": url,
            "douyin_id": u.get("douyin_id", ""),
        })
    return result


def _preprocess_xhs_users(users: list[dict]) -> list[dict] | None:
    """小红书：过滤企业认证 → 按粉丝数降序 → 取前3 → 精简字段 → URL脱敏"""
    verified_users = [u for u in users if u.get("verification") == "企业认证"]
    if not verified_users:
        return None

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
            "platform": "xiaohongshu",
            "name": u.get("name", ""),
            "profile_url": url,
            "xhs_id": u.get("xhs_id", ""),
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
        grade = "高"
    elif score >= 75:
        grade = "中高"
    elif score >= 60:
        grade = "中"
    else:
        grade = "低"

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

# 对外 detect 接口固定返回的平台及顺序
DETECT_PLATFORM_ORDER = (
    "official_website",
    "douyin",
    "xiaohongshu",
    "baidu",
    "taobao",
    "jd",
)


def _reset_analysis_caches() -> None:
    """每次搜索前清空，避免上次结果污染。"""
    preprocessed_cache.clear()
    analysis_cache.clear()


def _empty_platform_result(platform: str, brand: str) -> dict:
    """单平台无数据时的空结构（对接契约）。"""
    if platform == "official_website":
        return {"platform": "official_website", "brand_name": brand, "website": "", "description": ""}
    if platform == "douyin":
        return {"platform": "douyin", "users": []}
    if platform == "xiaohongshu":
        return {"platform": "xiaohongshu", "users": []}
    if platform == "baidu":
        return {"platform": "baidu", "score": "", "assessment_grade": ""}
    if platform == "taobao":
        return {"platform": "taobao", "name": "", "profile_url": ""}
    if platform == "jd":
        return {"platform": "jd", "name": "", "profile_url": ""}
    return {"platform": platform}


def _platform_result_from_cache(platform: str, brand: str) -> dict:
    """从缓存构建单平台结果；无缓存或预处理为空则返回空结构。"""
    if platform == "official_website":
        ow = preprocessed_cache.get("official_website")
        if ow:
            return {
                "platform": "official_website",
                "brand_name": ow.get("brand_name", brand),
                "website": ow.get("website", ""),
                "description": ow.get("description", ""),
                "source": ow.get("source", ""),
            }
        return _empty_platform_result(platform, brand)

    if platform == "douyin":
        dy = preprocessed_cache.get("douyin")
        return {"platform": "douyin", "users": dy if dy else []}

    if platform == "xiaohongshu":
        xhs = preprocessed_cache.get("xiaohongshu")
        return {"platform": "xiaohongshu", "users": xhs if xhs else []}

    if platform == "baidu":
        bd = analysis_cache.get("baidu")
        if bd:
            return {
                "platform": "baidu",
                "score": bd.get("score", ""),
                "assessment_grade": bd.get("assessment_grade", ""),
            }
        return _empty_platform_result(platform, brand)

    if platform in ("taobao", "jd"):
        data = preprocessed_cache.get(platform)
        if data:
            return {
                "platform": platform,
                "name": data.get("name", ""),
                "profile_url": data.get("profile_url", ""),
            }
        return _empty_platform_result(platform, brand)

    return _empty_platform_result(platform, brand)


def build_detect_response(
    brand: str,
    task_id: str,
    errors: list | None = None,
    status: str = "completed",
) -> dict:
    """构建对外 detect 接口响应：固定 6 平台全量返回。"""
    results = [_platform_result_from_cache(p, brand) for p in DETECT_PLATFORM_ORDER]
    return {
        "task_id": task_id,
        "brand": brand,
        "status": status,
        "results": results,
        "errors": errors or [],
    }


async def detect_brand_async(
    keyword: str,
    platform_keys: list[str] | None = None,
    task_id: str = "",
) -> dict:
    """同步 detect 入口：搜索完成后一次性返回固定 6 平台聚合结果。"""
    global _detect_running
    from config import PLATFORMS, DETECT_TOTAL_TIMEOUT_SECONDS, DETECT_PLATFORM_TIMEOUT_SECONDS

    async with _get_detect_state_lock():
        if _detect_running:
            raise DetectBusyError()
        _detect_running = True

    try:
        if not platform_keys:
            platform_keys = [k for k, v in PLATFORMS.items() if v.get("enabled")]

        errors: list[dict] = []
        try:
            async with asyncio.timeout(DETECT_TOTAL_TIMEOUT_SECONDS):
                search_results = await search_platforms_async(
                    keyword,
                    platform_keys,
                    platform_timeout=DETECT_PLATFORM_TIMEOUT_SECONDS,
                )
        except TimeoutError:
            errors.append({
                "platform": "_global",
                "message": f"检测总超时（{DETECT_TOTAL_TIMEOUT_SECONDS}秒），已返回已完成平台的结果",
            })
            return build_detect_response(keyword, task_id, errors, status="partial")

        errors = [
            {"platform": r["platform"], "message": r["error"]}
            for r in search_results
            if r.get("error")
        ]
        status = "partial" if errors else "completed"
        return build_detect_response(keyword, task_id, errors, status=status)
    finally:
        async with _get_detect_state_lock():
            _detect_running = False


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
                    preprocessed_cache["xiaohongshu"] = _preprocess_xhs_users(result["users"])
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
    """聚合所有平台的分析结果（统一返回给前端）。

    返回结构：
        ``{"task_id": str, "brand": str, "status": "completed", "results": [...], "errors": [...]}``
    """
    import uuid

    task_id = str(uuid.uuid4())[:8]
    brand = _last_keyword
    results: list = []
    errors: list = []

    # 一级信源：品牌官网
    if "official_website" in preprocessed_cache:
        ow = preprocessed_cache["official_website"]
        if ow:
            results.append(ow)
        else:
            results.append({"platform": "official_website", "brand_name": brand, "website": "未找到", "description": ""})

    # 抖音
    if "douyin" in preprocessed_cache:
        dy_data = preprocessed_cache["douyin"]
        results.append({"platform": "douyin", "users": dy_data if dy_data else []})

    # 小红书
    if "xiaohongshu" in preprocessed_cache:
        xhs_data = preprocessed_cache["xiaohongshu"]
        results.append({"platform": "xiaohongshu", "users": xhs_data if xhs_data else []})

    # 百度
    if "baidu" in analysis_cache:
        results.append({
            "platform": "baidu",
            "score": analysis_cache["baidu"].get("score", ""),
            "assessment_grade": analysis_cache["baidu"].get("assessment_grade", ""),
        })

    # 淘宝
    if "taobao" in preprocessed_cache:
        tb_data = preprocessed_cache["taobao"]
        if tb_data:
            results.append({
                "platform": "taobao",
                "name": tb_data.get("name", ""),
                "profile_url": tb_data.get("profile_url", ""),
            })
        else:
            results.append({"platform": "taobao", "name": "", "profile_url": ""})

    # 京东
    if "jd" in preprocessed_cache:
        jd_data = preprocessed_cache["jd"]
        if jd_data:
            results.append({
                "platform": "jd",
                "name": jd_data.get("name", ""),
                "profile_url": jd_data.get("profile_url", ""),
            })
        else:
            results.append({"platform": "jd", "name": "", "profile_url": ""})

    return {
        "task_id": task_id,
        "brand": brand,
        "status": "completed",
        "results": results,
        "errors": errors,
    }