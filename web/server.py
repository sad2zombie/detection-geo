# -*- coding: utf-8 -*-
"""FastAPI Web 服务 — 页面路由 + API（异步版本）"""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
from core.auth_manager import AuthManager


# ---------- 启动时自动检测所有平台登录态（方案 A：失败静默） ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """服务启动后，**后台异步**对所有启用平台跑一次 check_status。"""
    enabled = [k for k, v in config.PLATFORMS.items() if v.get("enabled")]
    if enabled:
        print(f"[启动] 自动检测 {len(enabled)} 个平台登录状态…", flush=True)
        asyncio.create_task(_initial_auth_check(enabled))
    yield
    # 退出由 atexit._shutdown_browser_manager 兜底


async def _initial_auth_check(platforms):
    from web.server import auth_manager
    for key in platforms:
        try:
            await auth_manager.check_status(key)
        except Exception as e:
            print(f"[启动] {key} 检测失败（已忽略）: {e}", flush=True)


app = FastAPI(title="品牌检测系统", version="0.1.0", lifespan=lifespan)

# 静态文件 + 模板
BASE_DIR = Path(__file__).parent.parent
web_dir = BASE_DIR / "web"
# 禁止静态文件缓存（Electron 浏览器缓存比较顽固，必须服务端强制禁用）
class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return response

app.mount("/static", NoCacheStaticFiles(directory=str(web_dir / "static")), name="static")
templates = Jinja2Templates(directory=str(web_dir / "templates"))

auth_manager = AuthManager()


# ---------- 页面路由 ----------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "platforms": config.PLATFORMS,
    })


# ---------- API: 登录状态 ----------
@app.get("/api/auth/status")
async def api_auth_status(refresh: bool = False):
    """检查所有平台登录状态。

    - 默认 (refresh=False)：**只读 lifespan 缓存**，不启浏览器
    - refresh=True：强制重新检测并写回缓存（前端手动 🔄 按钮用）
    """
    if not refresh:
        cached = auth_manager.get_cached_status()
        if cached:
            return JSONResponse(cached)
    results = await auth_manager.check_all_status()
    return JSONResponse(results)


@app.get("/api/auth/status/{platform_key}")
async def api_auth_status_single(platform_key: str, refresh: bool = False):
    """检查单个平台登录状态（异步）。"""
    if not refresh:
        cached = auth_manager.get_cached_status(platform_key)
        if cached is not None:
            return JSONResponse(cached)
    result = await auth_manager.check_status(platform_key)
    return JSONResponse(result)


@app.post("/api/auth/login/{platform_key}")
async def api_auth_login(platform_key: str, request: Request):
    """打开浏览器等待用户登录（异步）。

    body 可选 `{"url": "https://..."}`：传入则用同 BM 启浏览器 + 独立 newPage 打开 url。
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    url = (body.get("url") or "").strip() or None
    if url:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return JSONResponse({"ok": False, "error": "url 必须以 http(s):// 开头"}, status_code=400)
    result = await auth_manager.login_platform(platform_key, url=url)
    if url and result.get("success"):
        result["ok"] = True
    return JSONResponse(result)


# ---------- API: 搜索 ----------
@app.post("/api/search")
async def api_search(request: Request, body: dict):
    """执行搜索：打开浏览器 → 注入cookie → 各平台搜索 → 返回结果。"""
    keyword = body.get("keyword", "").strip()
    platform_keys = body.get("platforms", [])

    if not keyword:
        return JSONResponse({"error": "关键词不能为空"}, status_code=400)
    if not platform_keys:
        platform_keys = [k for k, v in config.PLATFORMS.items() if v.get("enabled")]

    from core.search_engine import search_platforms_async
    results = await search_platforms_async(keyword, platform_keys)
    return JSONResponse(results)


# ---------- API: 品牌匹配分析 ----------
@app.get("/api/analyze_brand")
async def api_get_analysis():
    """查询已暂存的分析结果，返回统一结构。"""
    from core.search_engine import get_aggregated_analysis
    return JSONResponse(get_aggregated_analysis())


# ---------- API: 品牌官网查询（一级信源，可独立调用）----------
@app.post("/api/brand-website")
async def api_brand_website(request: Request):
    """独立品牌官网查询接口（不依赖平台搜索）。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    brand_name = (body.get("brand_name") or "").strip()
    if not brand_name:
        return JSONResponse({"error": "品牌名称不能为空"}, status_code=400)

    from core.brand_search import search_brand
    result = await search_brand(brand_name)
    return JSONResponse(result)


# ---------- API: 平台列表 ----------
@app.get("/api/platforms")
async def api_platforms():
    return JSONResponse(config.PLATFORMS)


# ---------- 入口 ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)