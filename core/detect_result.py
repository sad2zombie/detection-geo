# -*- coding: utf-8 -*-
"""Detect / Kafka 结果组装的公共契约（无副作用）。"""

from __future__ import annotations


def wrap_platform_result(platform: str, data: dict) -> dict:
    return {"platform": platform, "data": data}


def format_detect_errors(errors: list | None) -> str:
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


def baidu_score_str(score) -> str:
    if score == "" or score is None:
        return ""
    try:
        return str(int(score))
    except (TypeError, ValueError):
        return str(score)


def empty_platform_result(platform: str, brand: str) -> dict:
    """单平台无数据时的空结构（对接契约）。"""
    if platform == "official_website":
        return wrap_platform_result("official_website", {
            "brand_name": brand,
            "website": "",
            "description": "",
        })
    if platform == "douyin":
        return wrap_platform_result("douyin", {"users": []})
    if platform == "xiaohongshu":
        return wrap_platform_result("xiaohongshu", {"users": []})
    if platform == "baidu":
        return wrap_platform_result("baidu", {"score": "", "assessment_grade": ""})
    return wrap_platform_result(platform, {})
