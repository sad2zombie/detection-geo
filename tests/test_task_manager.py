# -*- coding: utf-8 -*-
"""task_manager 平台字段规范化。"""

from core.task_manager import (
    _coerce_platform_list,
    _task_platform_keys,
    _with_canonical_platforms,
)


def test_coerce_platform_list():
    assert _coerce_platform_list(None) == []
    assert _coerce_platform_list("") == []
    assert _coerce_platform_list("baidu") == ["baidu"]
    assert _coerce_platform_list(["baidu", "douyin", ""]) == ["baidu", "douyin"]


def test_task_platform_keys_prefers_platform_then_platforms():
    assert _task_platform_keys({"platform": ["baidu"]}) == ["baidu"]
    assert _task_platform_keys({"platforms": ["douyin"]}) == ["douyin"]
    assert _task_platform_keys({"platform": [], "platforms": ["xhs"]}) == ["xhs"]
    assert _task_platform_keys({"platform": ["baidu"], "platforms": ["douyin"]}) == ["baidu"]


def test_with_canonical_platforms_drops_legacy_field():
    out = _with_canonical_platforms({
        "task_id": "t1",
        "platforms": ["baidu", "douyin"],
        "keyword": "西屋",
    })
    assert out["platform"] == ["baidu", "douyin"]
    assert "platforms" not in out
