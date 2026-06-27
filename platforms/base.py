# -*- coding: utf-8 -*-
"""平台抽象基类 + 公共实现（Browser 生命周期 / 登录 / 搜索重试 全部上移）"""

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, TypedDict

from core.browser_manager import get_browser_manager


class UserResult(TypedDict, total=False):
    """统一的用户搜索结果结构"""
    name: str
    profile_url: str
    verification: str
    verify_type: str
    douyin_id: str
    xhs_id: str
    follower_count: str
    like_count: str
    note_count: str
    description: str
    is_private: bool
    platform: str


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
    """平台搜索基类。

    子类只需：
      1. 覆盖类属性（platform_key / platform_name / profile_dir / home_url / save_btn_color）
      2. 实现 ``_do_search(keyword)`` —— 平台专属的爬虫逻辑
    其余（浏览器启停 / 导航重试 / 登录按钮注入 / 等待登录 / 搜索重试）均由基类提供。
    """

    platform_key: str = ""
    platform_name: str = ""
    profile_dir: str = ""
    home_url: str = ""
    save_btn_color: str = "linear-gradient(135deg,#4f8ff7,#764ba2)"

    # 各平台的 [_do_search] 返回 0 条时，基类自动重试几次
    SEARCH_MAX_RETRIES: int = 2  # 总共跑 3 次（0/1/2）

    # 登录等待最长 10 分钟
    LOGIN_MAX_WAIT_SECONDS: int = 600

    def __init__(self):
        self._bm = get_browser_manager()
        self._ctx: Any = None
        self._page: Any = None

    # ============================================================
    # 抽象方法
    # ============================================================

    @abstractmethod
    async def _do_search(self, keyword: str) -> SearchResult:
        """执行平台搜索并返回结构化结果（不含重试包装，由基类 search() 统一处理）。"""
        ...

    # ============================================================
    # 浏览器生命周期
    # ============================================================

    async def _ensure_browser(self, headless: bool | None = None) -> None:
        """确保浏览器已启动且可用。"""
        browser_ok = False
        if self._ctx is not None:
            try:
                _ = self._ctx.pages
                browser_ok = True
            except Exception:
                browser_ok = False

        need_relaunch = (
            self._ctx is None
            or not browser_ok
            or (headless is not None and self._bm._headless != headless)
        )

        if need_relaunch:
            self._ctx, self._page = await self._bm.ensure_page(
                self.profile_dir, headless=headless
            )
        elif self._page is None:
            if not self._ctx.pages:
                self._page = await self._ctx.new_page()
            else:
                self._page = self._ctx.pages[0]

    async def close(self) -> None:
        """关闭浏览器，释放引用计数。"""
        self._ctx = None
        self._page = None
        try:
            await self._bm.release()
        except Exception:
            pass
        try:
            await self._bm.shutdown()
        except Exception:
            pass

    # ============================================================
    # 导航重试
    # ============================================================

    async def _goto_with_retry(self, url: str, retries: int = 2, timeout: int = 30000) -> bool:
        """带重试的导航：失败时只创建新 page，不关闭整个浏览器。"""
        for attempt in range(retries + 1):
            try:
                await self._page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                return True
            except Exception as goto_err:
                err_str = str(goto_err)
                print(
                    f"    [{self.platform_name}导航] 第 {attempt + 1} 次失败 ({url[:60]}...): {err_str[:120]}",
                    flush=True,
                )
                if attempt < retries:
                    page_ok = False
                    if self._ctx is not None and self._bm.is_alive():
                        try:
                            _ = self._ctx.pages
                            self._page = await self._ctx.new_page()
                            page_ok = True
                        except Exception:
                            page_ok = False
                    if not page_ok:
                        await self._bm.shutdown()
                        await self._ensure_browser()
                    print(f"    [{self.platform_name}导航] 新建 page 完成，准备重试…", flush=True)
                else:
                    print(f"    [{self.platform_name}导航] 重试耗尽，放弃", flush=True)
                    return False
        return False

    # ============================================================
    # 登录按钮注入 + 登录状态检测 + 登录等待
    # ============================================================

    async def _inject_save_button(self) -> None:
        """注入悬浮保存按钮到当前页面。"""
        await self._page.evaluate(
            """(args) => {
                if (document.getElementById('__cloak_save_btn')) return;
                var btn = document.createElement('div');
                btn.id = '__cloak_save_btn';
                btn.textContent = '[SAVE] Save Login';
                btn.style.cssText = 'position:fixed;top:20px;right:20px;z-index:99999;'
                    + 'padding:14px 24px;background:' + args.color + ';'
                    + 'color:#fff;border-radius:10px;cursor:pointer;font-size:16px;'
                    + 'font-weight:bold;box-shadow:0 4px 20px rgba(0,0,0,0.4);'
                    + 'transition:transform 0.15s;user-select:none;';
                btn.onmouseover = function(){ this.style.transform='scale(1.05)'; };
                btn.onmouseout = function(){ this.style.transform='scale(1)'; };
                btn.onclick = function(){
                    this.textContent = '✅ 已保存!';
                    this.style.background = 'linear-gradient(135deg,#34d399,#10b981)';
                    window.__cloak_saved = true;
                };
                document.body.appendChild(btn);
                window.__cloak_saved = false;
            }""",
            {"color": self.save_btn_color},
        )

    async def check_login_status(self) -> dict:
        """轻量检测：profile 目录存在即视为已登录。"""
        logged = bool(self.profile_dir) and Path(self.profile_dir).exists()
        return {
            "platform": self.platform_key,
            "platform_name": self.platform_name,
            "isLoggedIn": logged,
            "note": "已登录" if logged else f"profile 目录不存在（请先登录）: {self.profile_dir}",
        }

    async def login(self) -> bool:
        """打开有头浏览器，等待用户手动登录后点击保存按钮。"""
        await self._ensure_browser(headless=False)
        await self._page.goto(self.home_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        await self._inject_save_button()

        print(
            f"    [{self.platform_name} Login] Browser opened, finish login and click [SAVE] in top-right corner",
            flush=True,
        )

        max_wait = self.LOGIN_MAX_WAIT_SECONDS
        elapsed = 0
        eval_fail_streak = 0
        while elapsed < max_wait:
            await asyncio.sleep(2)
            elapsed += 2
            if self._page is None or self._page.is_closed() or not self._bm.is_alive():
                print(f"    [{self.platform_name}登录] 检测到浏览器/页面已关闭，结束等待", flush=True)
                await self.close()
                return False
            try:
                saved = await self._page.evaluate("() => window.__cloak_saved || false")
                if saved:
                    await asyncio.sleep(1)
                    print(f"    [{self.platform_name}登录] Cookie已保存！关闭浏览器…", flush=True)
                    await self.close()
                    return True
                eval_fail_streak = 0
            except Exception as eval_err:
                eval_fail_streak += 1
                if eval_fail_streak >= 2:
                    print(
                        f"    [{self.platform_name}登录] 浏览器无响应（连续失败 {eval_fail_streak} 次）: {str(eval_err)[:80]}",
                        flush=True,
                    )
                    await self.close()
                    return False
                try:
                    await asyncio.sleep(2)
                    await self._inject_save_button()
                except Exception:
                    pass
        await self.close()
        return False

    # ============================================================
    # 搜索入口（统一重试框架）
    # ============================================================

    async def search(self, keyword: str) -> SearchResult:
        """搜索入口：结果为空则最多重试 SEARCH_MAX_RETRIES + 1 次。

        子类无需重写 —— 它只实现 ``_do_search``。
        """
        for attempt in range(self.SEARCH_MAX_RETRIES + 1):
            try:
                result = await self._do_search(keyword)
            except Exception as e:
                result = {
                    "brand": keyword,
                    "platform": self.platform_key,
                    "platform_name": self.platform_name,
                    "search_url": "",
                    "total_found": 0,
                    "users": [],
                    "error": str(e),
                }
            if result.get("total_found", 0) > 0:
                if attempt > 0:
                    print(
                        f"    [{self.platform_name}搜索] 第 {attempt + 1} 次尝试成功，获得 {result.get('total_found', 0)} 条数据",
                        flush=True,
                    )
                return result
            print(
                f"    [{self.platform_name}搜索] 第 {attempt + 1} 次结果为空（{result.get('error', '未知')[:60]}），",
                flush=True,
                end="",
            )
            if attempt < self.SEARCH_MAX_RETRIES:
                print("重试…", flush=True)
                try:
                    await self._bm.shutdown()
                except Exception:
                    pass
                self._ctx = None
                self._page = None
                await self._ensure_browser(headless=False)
            else:
                print("重试耗尽，返回空结果", flush=True)
        return {
            "brand": keyword,
            "platform": self.platform_key,
            "platform_name": self.platform_name,
            "search_url": "",
            "total_found": 0,
            "users": [],
            "error": f"重试{self.SEARCH_MAX_RETRIES + 1}次后仍无结果",
        }