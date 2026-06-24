# -*- coding: utf-8 -*-
"""FastAPI Web 服务 — 页面路由 + API（异步版本）"""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
from core.auth_manager import AuthManager


# ---------- 启动时自动检测所有平台登录态（方案 A：失败静默） ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """服务启动后，**后台异步**对所有启用平台跑一次 check_status。

    - 失败静默记日志（方案 A），不阻塞服务
    - 成功则直接更新 _instances 内部 cookie 状态，无需前端再做动作
    - 由前端首次 ``checkAuth()`` 拉取最新状态展示
    """
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
app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")
templates = Jinja2Templates(directory=str(web_dir / "templates"))

auth_manager = AuthManager()

# 全局分析缓存（内存中暂存各平台分析结果）
analysis_cache: dict[str, dict] = {}


def analyze_brand_result(brand: str, users: list[dict]) -> dict:
    """用 brand 对 users 中的 name 做子串匹配，计算得分和等级"""
    total = len(users)
    matched = sum(1 for u in users if brand in u.get("name", ""))
    score = round(matched / total * 100) if total > 0 else 0

    if score >= 90:
        grade = "高"
    elif score >= 75:
        grade = "中高"
    elif score >= 60:
        grade = "中"
    else:
        grade = "低"

    return {
        "platform": "baidu",
        "score": score,
        "assessment_grade": grade,
    }


# ---------- 页面路由 ----------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "platforms": config.PLATFORMS,
    })


@app.get("/results", response_class=HTMLResponse)
async def results_page(request: Request):
    return templates.TemplateResponse(request, "results.html")


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
    """检查单个平台登录状态（异步）。

    - 默认 (refresh=False)：缓存存在则读缓存，否则触发一次检测
    - refresh=True：强制重新检测
    """
    if not refresh:
        cached = auth_manager.get_cached_status(platform_key)
        if cached is not None:
            return JSONResponse(cached)
    result = await auth_manager.check_status(platform_key)
    return JSONResponse(result)


@app.post("/api/auth/login/{platform_key}")
async def api_auth_login(platform_key: str):
    """打开浏览器等待用户登录（异步）"""
    result = await auth_manager.login_platform(platform_key)
    return JSONResponse(result)


# ---------- API: 搜索 ----------
@app.post("/api/search")
async def api_search(request: Request, body: dict):
    """执行搜索：打开浏览器 → 注入cookie → 各平台搜索 → 返回结果"""
    keyword = body.get("keyword", "").strip()
    platform_keys = body.get("platforms", [])

    if not keyword:
        return JSONResponse({"error": "关键词不能为空"}, status_code=400)
    if not platform_keys:
        platform_keys = [k for k, v in config.PLATFORMS.items() if v.get("enabled")]

    from core.search_engine import search_platforms_async
    results = await search_platforms_async(keyword, platform_keys)

    for r in results:
        if r.get("platform") == "baidu" and not r.get("error") and r.get("users"):
            analysis = analyze_brand_result(r.get("brand", ""), r.get("users", []))
            analysis_cache["baidu"] = analysis
            print(f"[分析结果] 平台={analysis['platform']} 等级={analysis['assessment_grade']}")

    return JSONResponse(results)


# ---------- API: 历史结果 ----------
@app.get("/api/results")
async def api_list_all_results():
    """列出所有平台的历史搜索结果"""
    all_results = {}
    for platform_dir in config.RESULTS_DIR.iterdir():
        if platform_dir.is_dir():
            platform_key = platform_dir.name
            files = sorted(platform_dir.glob("*.json"), reverse=True)
            all_results[platform_key] = [
                {
                    "filename": f.name,
                    "size": f.stat().st_size,
                    "modified": f.stat().st_mtime,
                }
                for f in files
            ]
    return JSONResponse(all_results)


@app.get("/api/results/{platform_key}")
async def api_list_platform_results(platform_key: str):
    """列出指定平台的历史搜索结果"""
    platform_dir = config.RESULTS_DIR / platform_key
    if not platform_dir.exists():
        return JSONResponse({"error": "平台不存在或无历史记录"}, status_code=404)

    files = sorted(platform_dir.glob("*.json"), reverse=True)
    return JSONResponse([
        {
            "filename": f.name,
            "size": f.stat().st_size,
            "modified": f.stat().st_mtime,
        }
        for f in files
    ])


@app.get("/api/results/{platform_key}/{filename}")
async def api_get_result(platform_key: str, filename: str):
    """获取指定平台的某次搜索结果"""
    filepath = config.RESULTS_DIR / platform_key / filename
    if not filepath.exists():
        return JSONResponse({"error": "文件不存在"}, status_code=404)

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return JSONResponse(data)


# ---------- API: 品牌匹配分析 ----------
@app.get("/api/analyze_brand")
async def api_get_analysis():
    """查询已暂存的分析结果，返回统一结构"""
    from core.search_engine import preprocessed_cache, _last_keyword
    import uuid

    task_id = str(uuid.uuid4())[:8]
    brand = _last_keyword
    results: list = []
    errors: list = []

    # 抖音
    if "douyin" in preprocessed_cache:
        dy_data = preprocessed_cache["douyin"]
        results.append({
            "platform": "douyin",
            "users": dy_data if dy_data else [],
        })

    # 小红书
    if "xiaohongshu" in preprocessed_cache:
        xhs_data = preprocessed_cache["xiaohongshu"]
        results.append({
            "platform": "xiaohongshu",
            "users": xhs_data if xhs_data else [],
        })

    # 百度
    if "baidu" in analysis_cache:
        results.append({
            "platform": "baidu",
            "score": analysis_cache["baidu"].get("score", ""),
            "assessment_grade": analysis_cache["baidu"].get("assessment_grade", ""),
        })

    # 淘宝
    if "taobao" in preprocessed_cache:
        tb_data = preprocessed_cache["taobao"]
        if tb_data:
            results.append({
                "platform": "taobao",
                "name": tb_data.get("name", ""),
                "profile_url": tb_data.get("profile_url", ""),
            })
        else:
            results.append({
                "platform": "taobao",
                "name": "",
                "profile_url": "",
            })

    # 京东
    if "jd" in preprocessed_cache:
        jd_data = preprocessed_cache["jd"]
        if jd_data:
            results.append({
                "platform": "jd",
                "name": jd_data.get("name", ""),
                "profile_url": jd_data.get("profile_url", ""),
            })
        else:
            results.append({
                "platform": "jd",
                "name": "",
                "profile_url": "",
            })

    return JSONResponse({
        "task_id": task_id,
        "brand": brand,
        "status": "completed",
        "results": results,
        "errors": errors,
    })


# ---------- API: 平台列表 ----------
@app.get("/api/platforms")
async def api_platforms():
    return JSONResponse(config.PLATFORMS)


# ---------- 启动 / 关闭事件 ----------
@app.on_event("startup")
async def on_startup():
    """服务启动时初始化（如有需要）"""
    pass


@app.on_event("shutdown")
async def on_shutdown():
    """服务关闭时优雅关闭浏览器"""
    from core.browser_manager import _shutdown_browser_manager
    _shutdown_browser_manager()


# ---------- 入口 ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
