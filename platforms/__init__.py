# -*- coding: utf-8 -*-
"""平台 __init__"""

from platforms.douyin import DouyinPlatform
from platforms.baidu import BaiduPlatform
from platforms.xiaohongshu import XiaohongshuPlatform
from platforms.taobao import TaobaoPlatform
from platforms.jd import JdPlatform

PLATFORM_MAP = {
    "douyin": DouyinPlatform,
    "baidu": BaiduPlatform,
    "xiaohongshu": XiaohongshuPlatform,
    "taobao": TaobaoPlatform,
    "jd": JdPlatform,
}


def get_platform(key: str):
    """根据 key 获取平台实例"""
    cls = PLATFORM_MAP.get(key)
    if cls:
        return cls()
    return None


def get_all_platforms():
    """获取所有已启用平台实例"""
    from config import PLATFORMS
    instances = []
    for key, info in PLATFORMS.items():
        if info.get("enabled"):
            cls = PLATFORM_MAP.get(key)
            if cls:
                instances.append(cls())
    return instances