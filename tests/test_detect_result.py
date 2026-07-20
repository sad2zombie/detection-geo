# -*- coding: utf-8 -*-
from core.detect_result import (
    baidu_score_str,
    empty_platform_result,
    format_detect_errors,
    wrap_platform_result,
)


def test_wrap_platform_result():
    assert wrap_platform_result("douyin", {"users": []}) == {
        "platform": "douyin",
        "data": {"users": []},
    }


def test_format_detect_errors_empty():
    assert format_detect_errors(None) == ""
    assert format_detect_errors([]) == ""
    assert format_detect_errors([{"platform": "baidu", "message": "  "}]) == ""


def test_format_detect_errors_joins():
    assert format_detect_errors([
        {"platform": "baidu", "message": "超时"},
        {"platform": "", "message": "网络错误"},
    ]) == "baidu: 超时; 网络错误"


def test_baidu_score_str():
    assert baidu_score_str(None) == ""
    assert baidu_score_str("") == ""
    assert baidu_score_str(85) == "85"
    assert baidu_score_str(85.0) == "85"
    assert baidu_score_str("x") == "x"


def test_empty_platform_result_shapes():
    assert empty_platform_result("douyin", "西屋") == {
        "platform": "douyin",
        "data": {"users": []},
    }
    assert empty_platform_result("xiaohongshu", "西屋") == {
        "platform": "xiaohongshu",
        "data": {"users": []},
    }
    assert empty_platform_result("baidu", "西屋") == {
        "platform": "baidu",
        "data": {"score": "", "assessment_grade": ""},
    }
    assert empty_platform_result("official_website", "西屋") == {
        "platform": "official_website",
        "data": {"brand_name": "西屋", "website": "", "description": ""},
    }
    assert empty_platform_result("jd", "西屋") == {
        "platform": "jd",
        "data": {},
    }
