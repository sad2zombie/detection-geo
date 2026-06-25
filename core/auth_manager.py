# -*- coding: utf-8 -*-
"""登录状态管理器（异步版本）"""

import asyncio
from typing import Any

from platforms import get_platform
from platforms.base import BasePlatform


class AuthManager:
    """管理各平台登录 / Cookie 持久化（异步 API）"""

    def __init__(self):
        self._instances: dict[str, BasePlatform] = {}
        # 状态缓存：lifespan 启动检测后写入；/api/auth/status 无脑读；手动 🔄 强制刷新写回
        # 形状: { platform_key: {"platform": str, "platform_name": str, "isLoggedIn": bool, "note": str, "error": str} }
        self._status_cache: dict[str, dict] = {}
        # Per-platform 锁：lifespan 自动检测 与 前端手动检测 不能并发跑同一个平台，
        # 否则两者共享同一个 DouyinPlatform 实例的 self._ctx / self._page，一个 close() 置 None
        # 另一个协程随后就拿到 None 再调 .cookies() / .goto() 报 'NoneType' object has no attribute ...
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, platform_key: str) -> asyncio.Lock:
        if platform_key not in self._locks:
            self._locks[platform_key] = asyncio.Lock()
        return self._locks[platform_key]

    def _get_platform(self, key: str) -> BasePlatform:
        if key not in self._instances:
            self._instances[key] = get_platform(key)
        return self._instances[key]

    def get_cached_status(self, platform_key: str | None = None):
        """读缓存（不启浏览器）。platform_key=None → 全部。"""
        if platform_key is not None:
            return self._status_cache.get(platform_key)
        return list(self._status_cache.values())

    async def check_status(self, platform_key: str) -> dict:
        """检查指定平台登录状态（异步），结果写入 _status_cache。

        浏览器无头启 → 检测 → 无论结果如何 finally 关闭（释放 chromium 资源，
        否则一次检测后会一直占着进程和 profile 锁）。
        """
        async with self._get_lock(platform_key):
            p = self._get_platform(platform_key)
            if p is None:
                result = {"platform": platform_key, "platform_name": platform_key, "isLoggedIn": False, "error": "不支持的平台"}
            else:
                try:
                    status = await p.check_login_status()
                    raw_reason = status.get("reason", "")
                    # 截断 reason：去掉 Cookie 列表那段（如 "但存在登录Cookie: [...]"）
                    # 只保留前面的判断原因部分，tooltip 里好读
                    cookie_list_start = raw_reason.find("，但存在登录Cookie")
                    clean_reason = raw_reason[:cookie_list_start] if cookie_list_start > 0 else raw_reason
                    result = {
                        "platform": platform_key,
                        "platform_name": p.platform_name,
                        "isLoggedIn": status.get("isLoggedIn", False),
                        "note": clean_reason,
                    }
                except Exception as e:
                    result = {
                        "platform": platform_key,
                        "platform_name": platform_key,
                        "isLoggedIn": False,
                        "error": str(e),
                    }
                finally:
                    # 检测后必关：释放 chromium 资源 / profile 锁
                    try:
                        await p.close()
                    except Exception:
                        pass
            self._status_cache[platform_key] = result
            return result

    async def check_all_status(self) -> list[dict]:
        """检查所有平台登录状态（顺序执行：避免一次性起多个无头 chromium 抢资源）

        原 gather() 在同一事件循环里并发启多个 browser context，profile 锁会打架。
        改成串行更稳，启动慢一点但成功率 100%。
        """
        from config import PLATFORMS

        results: list[dict] = []
        for key in PLATFORMS:
            results.append(await self.check_status(key))
        return results

    async def login_platform(self, platform_key: str, url: str | None = None) -> dict:
        """打开指定平台浏览器并等待用户登录（异步）。

        login() 不再自动关闭浏览器，浏览器保持打开以便后续检测复用。

        url 不为空时：BM 启动浏览器 → 独立 newPage → goto url → 后台监听 page 关闭后 release。
        """
        async with self._get_lock(platform_key):
            p = self._get_platform(platform_key)
            if p is None:
                return {"success": False, "error": "不支持的平台"}
            try:
                if url:
                    page = await self._open_profile(p, url)
                    return {"success": True, "platform": platform_key, "platform_name": p.platform_name, "opened": True, "url": url, "_page": page}
                success = await p.login()
                return {"success": success, "platform": platform_key, "platform_name": p.platform_name}
            except Exception as e:
                return {"success": False, "platform": platform_key, "error": str(e)}

    async def _open_profile(self, p: BasePlatform, url: str) -> Any:
        """用平台的持久化 BrowserContext 启浏览器 + 独立 newPage 打开 url。

        完成后返回 page 对象（不关闭，page 关闭由后台任务监听后自动 release 引用）。
        """
        await p._ensure_browser(headless=False)
        if p._ctx is None:
            raise RuntimeError("浏览器未就绪")
        page = await p._ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"[AuthManager] open_profile goto 失败（保留 page）: {e}", flush=True)

        async def _wait_close_and_release():
            try:
                await page.wait_for_event("close", timeout=3600 * 1000)
            except Exception:
                pass
            finally:
                try:
                    await p._bm.release()
                except Exception:
                    pass

        asyncio.create_task(_wait_close_and_release())
        return page
