# -*- coding: utf-8 -*-
"""官网平台（一级信源）—— 分平台搜索 + 规则提取 + 大模型兜底，不使用浏览器。

继承 BasePlatform 但覆盖所有浏览器相关方法，
直接委托 core.brand_search.search_brand() 执行查询。
"""

from platforms.base import BasePlatform, SearchResult
from platforms import register_platform


@register_platform
class OfficialWebsitePlatform(BasePlatform):
    platform_key = "official_website"
    platform_name = "官网"

    # 不需要浏览器，无需重试
    SEARCH_MAX_RETRIES = 0

    async def check_login_status(self) -> dict:
        """官网查询不需要浏览器，始终视为已登录。"""
        return {
            "platform": self.platform_key,
            "platform_name": self.platform_name,
            "isLoggedIn": True,
            "note": "分平台搜索 + 规则提取，无需浏览器登录",
        }

    async def login(self) -> bool:
        """官网查询无需登录，直接返回成功。"""
        return True

    async def close(self):
        """无需关闭浏览器。"""
        pass

    async def _do_search(self, keyword: str) -> SearchResult:
        """执行品牌官网查询。"""
        from core.brand_search import search_brand

        result = await search_brand(keyword)

        # 转换为 SearchResult 格式
        has_website = result.get("website") and result["website"] != "未找到"

        users = []
        if has_website:
            users.append({
                "name": result.get("brand_name", keyword),
                "profile_url": result["website"],
                "verification": "官方网站",
                "description": result.get("description", ""),
                "source": result.get("source", ""),
                "platform": self.platform_key,
            })

        return {
            "brand": keyword,
            "platform": self.platform_key,
            "platform_name": self.platform_name,
            "search_url": result.get("website", "") if has_website else "",
            "total_found": 1 if has_website else 0,
            "users": users,
            "error": result.get("error", "") if has_website else "",
        }

    async def search(self, keyword: str) -> SearchResult:
        """官网查询只执行一次，不走基类重试框架（避免误报「重试N次」）。"""
        try:
            return await self._do_search(keyword)
        except Exception as e:
            return {
                "brand": keyword,
                "platform": self.platform_key,
                "platform_name": self.platform_name,
                "search_url": "",
                "total_found": 0,
                "users": [],
                "error": str(e),
            }
