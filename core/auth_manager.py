# -*- coding: utf-8 -*-
"""登录状态管理器（异步版本）"""

import logging

import asyncio
from typing import Any

from platforms import get_platform
from platforms.base import BasePlatform

logger = logging.getLogger(__name__)


class AuthManager:
    """管理各平台登录 / Cookie 持久化（异步 API）。

    并发模型说明：
    - per-platform 锁已删除（曾经的 ``_locks`` 在 ``_global_lock`` 串行化下是冗余的）
    - BrowserManager._global_lock 已经把所有浏览器操作串行化，
      所以两个并发请求不会同时操作同一个平台的 BrowserContext
    - AuthManager 实例本身只持有平台实例引用和状态缓存，无并发安全顾虑
    """

    def __init__(self):
        self._instances: dict[str, BasePlatform] = {}
        # 形状: { platform_key: {"platform": str, "platform_name": str, "isLoggedIn": bool, "note": str, "error": str} }
        self._status_cache: dict[str, dict] = {}
        self._login_sessions: dict[str, int] = {}
        self._login_wait_tasks: dict[str, asyncio.Task] = {}

    def _get_platform(self, key: str) -> BasePlatform:
        if key not in self._instances:
            self._instances[key] = get_platform(key)
        return self._instances[key]

    def get_cached_status(self, platform_key: str | None = None):
        """读缓存（不启浏览器）。platform_key=None → 全部已启用平台。"""
        if platform_key is not None:
            return self._status_cache.get(platform_key)
        from config import ENABLED_PLATFORM_KEYS
        return [
            self._status_cache[k]
            for k in ENABLED_PLATFORM_KEYS
            if k in self._status_cache
        ]

    async def check_status(self, platform_key: str) -> dict:
        """检查指定平台登录状态（异步），结果写入 _status_cache。

        浏览器无头启 → 检测 → 无论结果如何 finally 关闭（释放 chromium 资源）。
        """
        p = self._get_platform(platform_key)
        if p is None:
            result = {"platform": platform_key, "platform_name": platform_key, "isLoggedIn": False, "error": "不支持的平台"}
        else:
            try:
                status = await p.check_login_status()
                raw_reason = status.get("reason", "") or status.get("note", "")
                # 截断 reason：去掉 Cookie 列表那段（如 "但存在登录Cookie: [...]"）
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
        """检查所有已启用平台登录状态（顺序执行：避免一次性起多个无头 chromium 抢资源）。"""
        from config import ENABLED_PLATFORM_KEYS

        results: list[dict] = []
        for key in ENABLED_PLATFORM_KEYS:
            results.append(await self.check_status(key))
        return results

    async def login_platform(self, platform_key: str, url: str | None = None) -> dict:
        """打开指定平台浏览器并等待用户登录（异步）。

        url 不为空时：启动有头浏览器 → 在首个窗口 goto url → 后台监听关闭后 release。
        """
        p = self._get_platform(platform_key)
        if p is None:
            return {"success": False, "error": "不支持的平台"}
        try:
            if url:
                logger.info(f"[AuthManager] login_platform: 打开 {url}")
                await self._open_profile(p, url)
                return {"success": True, "platform": platform_key, "platform_name": p.platform_name, "opened": True, "url": url}
            success = await p.login()
            if not success:
                return {"success": False, "platform": platform_key, "platform_name": p.platform_name, "error": "closed"}
            return {"success": True, "platform": platform_key, "platform_name": p.platform_name}
        except Exception as e:
            logger.error(f"[AuthManager] login_platform 异常: {type(e).__name__}: {e}")
            return {"success": False, "platform": platform_key, "error": str(e)}

    def _bump_login_session(self, platform_key: str) -> int:
        """开启新的 profile 打开会话，并取消上一轮的后台释放任务。"""
        session = self._login_sessions.get(platform_key, 0) + 1
        self._login_sessions[platform_key] = session
        return session

    async def _cancel_login_wait_task(self, platform_key: str) -> None:
        old_task = self._login_wait_tasks.pop(platform_key, None)
        if old_task and not old_task.done():
            old_task.cancel()
            try:
                await old_task
            except asyncio.CancelledError:
                pass

    async def _release_login_browser(self, p: BasePlatform) -> None:
        p._ctx = None
        p._page = None
        try:
            await p._bm.release()
            logger.info("[AuthManager] 浏览器资源已释放")
        except Exception as e:
            logger.warning(f"[AuthManager] release 异常（忽略）: {e}")

    async def _open_profile(self, p: BasePlatform, url: str) -> None:
        """用平台持久化 profile 启动有头浏览器，在首个窗口直接打开 url。"""
        await self._cancel_login_wait_task(p.platform_key)
        session = self._bump_login_session(p.platform_key)

        logger.info(f"[AuthManager] _open_profile: 启动浏览器 (session={session})")
        try:
            p._ctx, page = await p._bm.ensure_page(p.profile_dir, headless=False)
        except Exception as e:
            logger.error(f"[AuthManager] _open_profile 启动浏览器失败: {type(e).__name__}: {e}")
            await self._release_login_browser(p)
            raise

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.warning(f"[AuthManager] open_profile goto 失败（保留窗口）: {e}")

        async def _wait_close_and_release():
            """等待用户关闭页面/浏览器，然后释放资源。"""
            try:
                close_task = asyncio.create_task(
                    page.wait_for_event("close", timeout=3600 * 1000)
                )
                while not close_task.done():
                    await asyncio.sleep(2)
                    if not self._login_sessions.get(p.platform_key) == session:
                        logger.info("[AuthManager] 会话已被新请求取代，停止等待")
                        close_task.cancel()
                        break
                    try:
                        ctx = p._bm.get_context()
                        if ctx is None:
                            logger.info("[AuthManager] context 已消失，触发释放")
                            close_task.cancel()
                            break
                        _ = page.url
                    except Exception:
                        logger.info("[AuthManager] page 已关闭，触发释放")
                        close_task.cancel()
                        break
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"[AuthManager] wait_close 异常（忽略）: {e}")
            finally:
                await self._release_login_browser(p)

        task = asyncio.create_task(_wait_close_and_release())
        self._login_wait_tasks[p.platform_key] = task