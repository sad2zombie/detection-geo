# -*- coding: utf-8 -*-
"""平台注册中心。

用 ``@register_platform`` 装饰器自动注册平台类，新增平台只需 import 即可，
无需手动维护映射表。
"""

from platforms.base import BasePlatform

_REGISTRY: dict[str, type[BasePlatform]] = {}


def register_platform(cls: type[BasePlatform]) -> type[BasePlatform]:
    """装饰器：注册平台到全局映射。"""
    _REGISTRY[cls.platform_key] = cls
    return cls


def get_platform(key: str) -> BasePlatform | None:
    """根据 platform_key 获取平台实例。"""
    cls = _REGISTRY.get(key)
    return cls() if cls else None


def get_all_platforms() -> list[BasePlatform]:
    """获取所有已启用平台实例。"""
    from config import PLATFORMS
    return [
        get_platform(k)
        for k, v in PLATFORMS.items()
        if v.get("enabled") and k in _REGISTRY
    ]


def get_enabled_keys() -> list[str]:
    """获取所有已启用平台 key（按 config.PLATFORMS 声明顺序）。"""
    from config import PLATFORMS
    return [k for k, v in PLATFORMS.items() if v.get("enabled") and k in _REGISTRY]


# 触发装饰器注册（类定义即注册）
from platforms.douyin import DouyinPlatform          # noqa: F401, E402
from platforms.baidu import BaiduPlatform            # noqa: F401, E402
from platforms.xiaohongshu import XiaohongshuPlatform  # noqa: F401, E402
from platforms.taobao import TaobaoPlatform          # noqa: F401, E402
from platforms.jd import JdPlatform                  # noqa: F401, E402