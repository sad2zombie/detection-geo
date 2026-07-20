# -*- coding: utf-8 -*-
from core.brand_match import (
    analyze_brand_result,
    brand_name_similarity,
    parse_follower_count,
    preprocess_douyin_users,
    preprocess_jd_users,
    preprocess_official_website,
)


def test_parse_follower_count():
    assert parse_follower_count(None) is None
    assert parse_follower_count(123) == 123.0
    assert parse_follower_count("1.5万") == 15000.0
    assert parse_follower_count("abc") is None


def test_brand_name_similarity_exact_and_contains():
    assert brand_name_similarity("西屋", "西屋") == 100.0
    assert brand_name_similarity("", "西屋") == 0.0
    assert brand_name_similarity("西屋", "西屋官方旗舰店") > 85.0
    assert brand_name_similarity("西屋电器", "西屋") >= 75.0


def test_preprocess_douyin_filters_blue_v_and_strips_query():
    users = [
        {"name": "杂牌", "verification": "蓝V", "profile_url": "https://x?a=1", "douyin_id": "1", "follower_count": "10"},
        {"name": "西屋", "verification": "蓝V", "profile_url": "https://y?b=2", "douyin_id": "2", "follower_count": "100"},
        {"name": "西屋素人", "verification": "", "profile_url": "https://z", "douyin_id": "3", "follower_count": "999"},
    ]
    out = preprocess_douyin_users(users, "西屋")
    assert out is not None
    assert len(out) == 2
    assert out[0]["name"] == "西屋"
    assert out[0]["profile_url"] == "https://y"
    assert out[0]["account_id"] == "2"


def test_preprocess_douyin_none_without_blue_v():
    assert preprocess_douyin_users([{"name": "西屋", "verification": ""}], "西屋") is None


def test_preprocess_jd_requires_official_flagship():
    users = [
        {"name": "西屋旗舰店", "profile_url": "https://jd/1?x=1"},
        {"name": "西屋官方旗舰店", "profile_url": "https://jd/2?x=1"},
    ]
    out = preprocess_jd_users(users, "西屋")
    assert out == {
        "platform": "jd",
        "name": "西屋官方旗舰店",
        "profile_url": "https://jd/2",
    }


def test_analyze_brand_result_grades():
    users = [
        {"name": "西屋官网", "description": ""},
        {"name": "其他", "description": "提到西屋"},
        {"name": "无关", "description": "无关"},
    ]
    out = analyze_brand_result("西屋", users)
    assert out["platform"] == "baidu"
    assert out["score"] == 67
    assert out["assessment_grade"] == "中"


def test_preprocess_official_website():
    assert preprocess_official_website([]) is None
    assert preprocess_official_website([{
        "name": "西屋",
        "profile_url": "https://example.com",
        "description": "简介",
        "source": "百度",
    }]) == {
        "platform": "official_website",
        "brand_name": "西屋",
        "website": "https://example.com",
        "description": "简介",
        "source": "百度",
    }
