# -*- coding: utf-8 -*-
"""浏览器生命周期管理器（异步 API + 单例 + 引用计数）

核心设计：
- 使用 CloakBrowser 官方的 Async API（launch_persistent_context_async）
- 与 FastAPI/uvicorn 共享 asyncio event loop，零线程切换
- 所有操作都是 async/await，简洁可靠
- 浏览器在首次请求时懒启动，归零时关闭

解决以下问题：
- Playwright Sync API 在 asyncio loop 中调用 → 改用官方 Async API
- 浏览器用完不关闭 → 引用计数归零自动关闭
- 残留 lockfile 导致 exitCode=21 → 启动时强制清理
- Chromium 进程泄漏 → 完整 await close() 流程

用法：
    from core.browser_manager import get_browser_manager

    bm = get_browser_manager()
    async with bm.acquire_page(profile_dir) as page_ctx:
        page = page_ctx["page"]
        # ... 执行业务逻辑 ...
    # 离开 with 块时引用计数归零，浏览器自动关闭
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time
from pathlib import Path
from typing import Any, Optional

from config import (
    BROWSER_HEADLESS,
    BROWSER_IDLE_TIMEOUT,
    BROWSER_LAUNCH_RETRIES,
    BROWSER_LAUNCH_TIMEOUT,
    CLOAKBROWSER_DIR,
)


# ---------------------------------------------------------------------------
# CloakBrowser 动态导入
# ---------------------------------------------------------------------------
def _ensure_cloakbrowser():
    """确保 cloakbrowser 在 sys.path 中"""
    cb_dir = str(CLOAKBROWSER_DIR)
    if cb_dir not in __import__("sys").path:
        __import__("sys").path.insert(0, cb_dir)


_ensure_cloakbrowser()
from cloakbrowser import launch_persistent_context_async  # noqa: E402  (动态导入后)


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------
_instance: "BrowserManager | None" = None
_instance_lock: Optional[asyncio.Lock] = None


def get_browser_manager() -> "BrowserManager":
    """获取 BrowserManager 全局单例（线程安全）"""
    global _instance, _instance_lock
    if _instance is None:
        import threading as _threading
        with _threading.Lock():
            if _instance is None:
                _instance = BrowserManager()
    return _instance


async def _shutdown_browser_manager_async() -> None:
    """进程退出时彻底关闭浏览器管理器（async 版本）"""
    global _instance
    if _instance is not None:
        try:
            await _instance.shutdown()
        except Exception:
            pass
        _instance = None


def _shutdown_browser_manager() -> None:
    """进程退出时彻底关闭浏览器管理器（同步包装，由 atexit 注册）"""
    global _instance
    if _instance is not None:
        try:
            # 在同步上下文中无法 await，使用 run_until_complete（如果事件循环已关闭则跳过）
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    # 事件循环已关闭，跳过
                    return
                if loop.is_running():
                    # 事件循环正在运行（不应该在 atexit 时发生）
                    return
                loop.run_until_complete(_shutdown_browser_manager_async())
            except RuntimeError:
                # 没有事件循环或已关闭
                pass
        except Exception:
            pass
        _instance = None


# ---------------------------------------------------------------------------
# BrowserManager
# ---------------------------------------------------------------------------
class BrowserManager:
    """基于 CloakBrowser Async API 的浏览器生命周期管理器。

    架构：
    - 浏览器实例 (BrowserContext) 持有在 asyncio 事件循环线程
    - 所有 Playwright 操作都是 await
    - 引用计数：acquire +1, release -1, 归零时关闭
    - 锁文件自动清理（启动前 + 失败重试时）
    """

    def __init__(self):
        self._lock: Optional[asyncio.Lock] = None  # 内部 _ref_count / _launch 串行化
        # 跨平台全局互斥锁：所有公开 API 都先抢这个锁，确保同一时间只有一个平台
        # 能启动/操作浏览器；否则抖音登录还没点保存，淘宝又进来 ensure_page 会触发
        # _launch → _close_browser，把抖音的 page 干掉。
        self._global_lock: Optional[asyncio.Lock] = None
        self._ref_count = 0
        self._ctx: Any = None  # CloakBrowser BrowserContext (async)
        self._last_used: float = time.time()
        self._profile_dir: str | None = None
        self._headless: bool = BROWSER_HEADLESS
        self._closed = False

    def _get_lock(self) -> asyncio.Lock:
        """懒创建 asyncio.Lock（必须在 event loop 中创建）"""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _get_global_lock(self) -> asyncio.Lock:
        """懒创建跨平台全局互斥锁。"""
        if self._global_lock is None:
            self._global_lock = asyncio.Lock()
        return self._global_lock

    # ---- 公共 API（全部 async）----

    async def acquire(self, profile_dir: str | None = None, headless: bool | None = None) -> None:
        """增加引用计数；若浏览器未启动或已死则启动新实例

        Args:
            profile_dir: profile 目录
            headless: 是否无头模式。None 表示沿用当前设置（首次默认 BROWSER_HEADLESS）。
                      传入 True/False 会强制使用该模式，并在 headless 与当前不一致时重启浏览器。
        """
        # 全局互斥锁：跨平台串行化（避免并发 ensure_page / _launch 互相干掉对方）
        async with self._get_global_lock():
            async with self._get_lock():
                async with asyncio.timeout(BROWSER_LAUNCH_TIMEOUT + 10):
                    # headless 切换时先关闭旧实例（必须在这里更新 _headless，否则 _need_relaunch 判断会出错）
                    if headless is not None and self._ctx is not None:
                        if headless != self._headless:
                            await self._close_browser()
                        self._headless = headless
                    if await self._need_relaunch(profile_dir, headless):
                        await self._launch(profile_dir, headless)
                    else:
                        if profile_dir is not None:
                            self._profile_dir = profile_dir
                    self._ref_count += 1
                    self._last_used = time.time()

    async def release(self) -> None:
        """减少引用计数；归零时关闭浏览器"""
        async with self._get_global_lock():
            async with self._get_lock():
                if self._ref_count <= 0:
                    return
                self._ref_count -= 1
                if self._ref_count <= 0:
                    await self._close_browser()

    def get_context(self) -> Any | None:
        """获取当前 BrowserContext（同步，仅供遗留代码使用）"""
        if self._ctx is None or self._closed:
            return None
        return self._ctx

    def get_page(self) -> Any | None:
        """获取当前 Page（同步，仅供遗留代码使用）"""
        ctx = self.get_context()
        if ctx is None:
            return None
        try:
            return ctx.pages[0] if ctx.pages else None
        except Exception:
            return None

    async def ensure_page(self, profile_dir: str | None = None, headless: bool | None = None) -> tuple[Any, Any]:
        """
        确保有可用的 context 和 page。
        返回 (context, page)。若内部浏览器已死，自动重建。
        """
        # 全局互斥锁：跨平台串行化
        async with self._get_global_lock():
            async with self._get_lock():
                async with asyncio.timeout(BROWSER_LAUNCH_TIMEOUT + 10):
                    # headless 切换时先关闭旧实例（必须在这里更新 _headless，否则 _need_relaunch 判断会出错）
                    if headless is not None and self._ctx is not None:
                        if headless != self._headless:
                            await self._close_browser()
                        self._headless = headless
                    if await self._need_relaunch(profile_dir, headless):
                        await self._launch(profile_dir, headless)
                    self._ref_count += 1
                    self._last_used = time.time()
                    ctx = self._ctx
                    if not ctx.pages:
                        page = await ctx.new_page()
                    else:
                        page = ctx.pages[0]
                    return ctx, page

    # ---- 上下文管理器 ----

    @contextlib.asynccontextmanager
    async def acquire_page(self, profile_dir: str | None = None, headless: bool | None = None):
        """
        异步上下文管理器用法：
            async with bm.acquire_page(profile_dir, headless=False) as page_ctx:
                page = page_ctx.page
                # ... 执行业务逻辑 ...
        进入时自动 acquire，退出时自动 release。

        Args:
            profile_dir: profile 目录
            headless: 是否无头模式。None 沿用当前设置。登录场景传 False 即可见浏览器。
        """
        await self.acquire(profile_dir, headless)
        try:
            if self._ctx is None:
                raise RuntimeError("Browser not available after acquire")
            if not self._ctx.pages:
                page = await self._ctx.new_page()
            else:
                page = self._ctx.pages[0]
            yield _PageCtx(self, page, self._ctx)
        finally:
            try:
                await self.release()
            except Exception:
                pass

    # ---- 内部实现（全部 async） ----

    async def _need_relaunch(self, profile_dir: str | None = None, headless: bool | None = None) -> bool:
        """检查浏览器是否需要重新启动"""
        if self._ctx is None or self._closed:
            return True
        # headless 模式不一致 → 需要重启
        if headless is not None and headless != self._headless:
            return True
        try:
            # async API: 直接 await
            _ = self._ctx.pages  # 访问属性，触发可用性检查
            return False
        except Exception:
            return True

    # ---- 锁文件 & 残留进程清理 ----

    def _cleanup_profile_locks(self, profile_dir: str) -> list[str]:
        """清理 Chromium 持久化 profile 的残留锁文件，返回被清理的文件名列表"""
        cleaned: list[str] = []
        p = Path(profile_dir)
        if not p.exists():
            return cleaned
        for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"):
            lock_file = p / lock_name
            if lock_file.exists():
                try:
                    lock_file.unlink()
                    cleaned.append(lock_file.name)
                except Exception as e:
                    print(f"[BrowserManager] 清理锁文件失败 {lock_file.name}: {e}", flush=True)
        return cleaned

    def _kill_stale_chrome_processes(self, profile_dir: str) -> list[int]:
        """杀死可能残留的 chrome.exe 进程（通过 user-data-dir 命令行匹配）"""
        killed: list[int] = []
        if sys.platform != "win32":
            return killed
        import subprocess
        try:
            result = subprocess.run(
                ["wmic", "process", "where",
                 f'CommandLine like "%{profile_dir}%"',
                 "get", "ProcessId"],
                capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace",
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.isdigit():
                    pid = int(line)
                    try:
                        subprocess.run(
                            ["taskkill", "/F", "/PID", str(pid)],
                            capture_output=True, timeout=5,
                        )
                        killed.append(pid)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[BrowserManager] 清理残留进程失败（忽略）: {e}", flush=True)
        return killed

    def _diagnose_profile(self, profile_dir: str) -> None:
        """打印 profile 目录诊断信息"""
        import re
        p = Path(profile_dir)
        if not p.exists():
            print(f"[BrowserManager] 诊断: profile 目录不存在，将自动创建", flush=True)
            return

        try:
            total_size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            size_mb = total_size / (1024 * 1024)
            print(f"[BrowserManager] 诊断: profile 目录大小 = {size_mb:.2f} MB", flush=True)
        except Exception:
            pass

        lock_files = []
        for name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"):
            fp = p / name
            if fp.exists():
                try:
                    lock_files.append(f"{name}({fp.stat().st_size}字节)")
                except Exception:
                    lock_files.append(f"{name}(?)")
        if lock_files:
            print(f"[BrowserManager] 诊断: 发现残留锁文件 → {lock_files}", flush=True)
        else:
            print(f"[BrowserManager] 诊断: 无残留锁文件", flush=True)

        local_state = p / "Local State"
        if local_state.exists():
            try:
                content = local_state.read_text(encoding="utf-8", errors="replace")
                m = re.search(r'"channel":"([^"]+)"', content)
                if m:
                    print(f"[BrowserManager] 诊断: Local State channel = {m.group(1)}", flush=True)
            except Exception:
                pass

    # ---- 启动 / 关闭（async） ----

    async def _launch(self, profile_dir: str | None = None, headless: bool | None = None) -> None:
        """异步启动浏览器：使用 CloakBrowser 官方 Async API"""
        # 先关闭旧实例
        await self._close_browser()

        profile = profile_dir or self._profile_dir or ""
        # 显式传入 headless 则使用；否则沿用当前
        if headless is not None:
            self._headless = headless
        actual_headless = self._headless

        print(f"[BrowserManager] 准备启动浏览器 headless={actual_headless} profile={profile}", flush=True)

        if profile:
            self._diagnose_profile(profile)
            # 启动前清理锁文件和残留进程
            cleaned = self._cleanup_profile_locks(profile)
            if cleaned:
                print(f"[BrowserManager] 已清理残留锁文件: {cleaned}", flush=True)
            killed = self._kill_stale_chrome_processes(profile)
            if killed:
                print(f"[BrowserManager] 已杀掉残留进程: {killed}", flush=True)

        last_error: Exception | None = None
        for attempt in range(BROWSER_LAUNCH_RETRIES + 1):
            try:
                ctx = await asyncio.wait_for(
                    launch_persistent_context_async(
                        profile,
                        headless=actual_headless,
                    ),
                    timeout=BROWSER_LAUNCH_TIMEOUT,
                )
                self._ctx = ctx
                self._profile_dir = profile
                self._last_used = time.time()
                self._closed = False
                print(
                    f"[BrowserManager] 浏览器启动成功（尝试 {attempt + 1}/{BROWSER_LAUNCH_RETRIES + 1}）",
                    flush=True,
                )
                return
            except Exception as e:
                last_error = e
                err_str = str(e)
                is_recoverable = any(
                    sig in err_str for sig in (
                        "exitCode=21",
                        "exit code 21",
                        "TargetClosedError",
                        "has been closed",
                        "has crashed",
                        "failed to create browser",
                        "Unable to launch",
                    )
                )
                if is_recoverable:
                    print(
                        f"[BrowserManager] 启动失败（尝试 {attempt + 1}/{BROWSER_LAUNCH_RETRIES + 1}）: {e}",
                        flush=True,
                    )
                    if profile:
                        cleaned = self._cleanup_profile_locks(profile)
                        if cleaned:
                            print(f"[BrowserManager] 已清理锁文件: {cleaned}", flush=True)
                        killed = self._kill_stale_chrome_processes(profile)
                        if killed:
                            print(f"[BrowserManager] 已杀掉残留进程: {killed}", flush=True)
                    self._ctx = None
                    await self._close_browser()
                    await asyncio.sleep(1)
                else:
                    raise

        raise RuntimeError(
            f"浏览器启动失败，已重试 {BROWSER_LAUNCH_RETRIES + 1} 次仍未成功。"
            f" 最后一个错误: {last_error}"
        ) from last_error

    async def _close_browser(self) -> None:
        """异步关闭浏览器（使用 CloakBrowser 官方 Async API 的 close）"""
        if self._ctx is None:
            return
        ctx = self._ctx
        self._ctx = None
        self._closed = True
        try:
            # CloakBrowser 已经 patch 过 close()，会自动 stop Playwright
            await ctx.close()
        except Exception as e:
            err = str(e)
            if "cannot switch to a different thread" in err:
                print("[BrowserManager] 浏览器在已退出的线程中，忽略关闭错误（资源将由 OS 回收）", flush=True)
            elif "no longer available" in err or "has been closed" in err or "TargetClosedError" in err:
                print("[BrowserManager] 浏览器已被关闭，跳过", flush=True)
            else:
                print(f"[BrowserManager] 关闭浏览器时异常（忽略）: {e}", flush=True)

    async def shutdown(self) -> None:
        """彻底关闭浏览器（服务关闭时调用）"""
        async with self._get_global_lock():
            try:
                await self._close_browser()
            except Exception:
                pass
            self._ref_count = 0

    def is_alive(self) -> bool:
        """检查浏览器是否存活（同步）"""
        if self._ctx is None or self._closed:
            return False
        return True


class _PageCtx:
    """acquire_page() 返回的上下文管理器，持有 page 和 context"""

    __slots__ = ("_bm", "_page", "_ctx")

    def __init__(self, bm: BrowserManager, page: Any, ctx: Any):
        self._bm = bm
        self._page = page
        self._ctx = ctx

    @property
    def page(self) -> Any:
        return self._page

    @property
    def context(self) -> Any:
        return self._ctx

    async def __aenter__(self) -> "_PageCtx":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            await self._bm.release()
        except Exception:
            pass


def _test_close_safety():
    """单元测试：重复关闭、不存在的 ctx 不应抛错"""
    import asyncio
    async def _run():
        bm = BrowserManager()
        await bm._close_browser()  # 无 ctx
        await bm._close_browser()  # 重复
        print("[BrowserManager] _close_browser() 单元测试通过")
    asyncio.run(_run())


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    _test_close_safety()
