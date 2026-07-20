# -*- coding: utf-8 -*-
from core.brand_llm import SOURCE_LLM, _is_llm_not_found, _is_valid_llm_website, _normalize_llm_website
from core.brand_rules import (
    _extract_brand_tokens,
    _is_error_results,
    _is_official_website_candidate,
    _is_search_engine_host,
    _is_ugc_host,
    _title_contains_brand,
)
from core.web_engines.common import (
    _is_error_result,
    _search_results_relevant,
    _tag_engine,
)


def test_web_common_error_and_tag():
    assert _is_error_result([]) is True
    assert _is_error_result([{"title": "搜索错误", "snippet": ""}]) is True
    assert _is_error_result([{"title": "西屋官网", "snippet": "ok"}]) is False
    tagged = _tag_engine([{"title": "a", "url": "", "snippet": ""}], "百度")
    assert tagged[0]["_engine"] == "百度"


def test_web_common_relevance():
    results = [{"title": "西屋电气官网", "snippet": ""}]
    assert _search_results_relevant("西屋", results) is True
    assert _search_results_relevant("完全无关品牌名xyz", results) is False


def test_brand_tokens_and_title():
    tokens = _extract_brand_tokens("广州市海丝妍化妆品有限公司")
    assert "海丝妍" in tokens or any("海丝妍" in t for t in tokens)
    assert _title_contains_brand("海丝妍官方网站", tokens) is True


def test_official_candidate_filters():
    assert _is_ugc_host("https://www.zhihu.com/question/1") is True
    assert _is_search_engine_host("https://www.baidu.com/s?wd=1") is True
    assert _is_official_website_candidate("https://www.example.com/") is True
    assert _is_official_website_candidate("https://www.example.com/article/123") is False


def test_is_error_results_alias():
    from core.web_engines.common import _is_error_result

    assert _is_error_results is _is_error_result
    assert _is_error_results([]) is True
    assert _is_error_results([{"title": "ok", "snippet": "ok"}]) is False


def test_llm_website_helpers():
    assert SOURCE_LLM == "大模型"
    assert _is_llm_not_found("未找到") is True
    assert _is_valid_llm_website("https://www.example.com/path") is True
    assert _is_valid_llm_website("https://中文.com") is False
    assert _normalize_llm_website("www.example.com/about") == "https://www.example.com"
