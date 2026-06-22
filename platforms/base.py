# -*- coding: utf-8 -*-
"""平台抽象基类"""

from abc import ABC, abstractmethod
from typing import TypedDict


class UserResult(TypedDict, total=False):
    """统一的用户搜索结果结构"""
    name: str
    profile_url: str
    verification: str          # blue_v / yellow_v / official / verified / none / unknown
    verify_type: str           # 认证类型文字，如 "店铺账号"
    douyin_id: str             # 平台ID
    follower_count: str
    like_count: str
    description: str
    is_private: bool
    platform: str              # 平台标识


class SearchResult(TypedDict):
    """统一的搜索结果结构"""
    brand: str
    platform: str
    platform_name: str
    search_url: str
    total_found: int
    users: list[UserResult]
    error: str


class BasePlatform(ABC):
    """平台搜索基类，所有平台模块需继承此类"""

    platform_key: str = ""     # 平台标识，如 "douyin"
    platform_name: str = ""    # 平台显示名，如 "抖音"
    profile_dir: str = ""      # Cookie 持久化目录

    @abstractmethod
    async def search(self, keyword: str) -> SearchResult:
        """执行搜索并返回结构化结果"""
        ...

    @abstractmethod
    async def check_login_status(self) -> dict:
        """检查登录状态"""
        ...

    @abstractmethod
    async def login(self) -> bool:
        """打开浏览器等待用户登录，返回是否成功"""
        ...