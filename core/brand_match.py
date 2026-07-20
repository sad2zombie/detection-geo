# -*- coding: utf-8 -*-
"""品牌匹配 / 平台结果预处理（纯函数，无 IO）。"""

from __future__ import annotations


def parse_follower_count(raw: str | int | float | None) -> float | None:
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


def brand_name_similarity(brand: str, name: str) -> float:
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


def user_sort_key(u: dict, brand: str) -> tuple:
    """主排序：品牌相似度；次排序：粉丝数、获赞数。"""
    sim = brand_name_similarity(brand, u.get("name", ""))
    fc = parse_follower_count(u.get("follower_count"))
    lc = parse_follower_count(u.get("like_count"))
    return (sim, fc if fc is not None else -1, lc if lc is not None else -1)


def preprocess_douyin_users(users: list[dict], brand: str) -> list[dict] | None:
    """抖音：过滤蓝V → 按品牌名相似度排序 → 取前20 → 精简字段 → URL脱敏"""
    blue_v_users = [u for u in users if u.get("verification") == "蓝V"]
    if not blue_v_users:
        return None

    blue_v_users.sort(key=lambda u: user_sort_key(u, brand), reverse=True)

    result = []
    for u in blue_v_users[:20]:
        url = u.get("profile_url", "")
        if "?" in url:
            url = url.split("?")[0]
        result.append({
            "name": u.get("name", ""),
            "profile_url": url,
            "account_id": u.get("douyin_id", ""),
            "follower_count": u.get("follower_count", "") or "",
        })
    return result


def preprocess_xhs_users(users: list[dict], brand: str) -> list[dict] | None:
    """小红书：过滤企业认证 → 按品牌名相似度排序 → 取前20 → 精简字段 → URL脱敏"""
    verified_users = [u for u in users if u.get("verification") == "企业认证"]
    if not verified_users:
        return None

    verified_users.sort(key=lambda u: user_sort_key(u, brand), reverse=True)

    result = []
    for u in verified_users[:20]:
        url = u.get("profile_url", "")
        if "?" in url:
            url = url.split("?")[0]
        result.append({
            "name": u.get("name", ""),
            "profile_url": url,
            "account_id": u.get("xhs_id", ""),
            "follower_count": u.get("follower_count", "") or "",
        })
    return result


def preprocess_jd_users(users: list[dict], brand: str) -> dict | None:
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


def preprocess_taobao_users(users: list[dict], brand: str) -> dict | None:
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


def preprocess_official_website(users: list[dict]) -> dict | None:
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
