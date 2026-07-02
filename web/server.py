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


async def _consumption_poll_loop():
    """后台定时向服务器拉取消费任务。"""
    if not config.CONSUMPTION_POLL_ENABLED:
        return
    if not config.CONSUMPTION_FETCH_URL or not config.KAFKA_RESULT_TOPIC:
        return
    from core.consumption_worker import poll_once

    print(
        f"[消费轮询] 已启动，间隔 {config.CONSUMPTION_POLL_INTERVAL}s",
        flush=True,
    )
    while True:
        try:
            await poll_once()
        except Exception as e:
            print(f"[消费轮询] 异常: {e}", flush=True)
        await asyncio.sleep(config.CONSUMPTION_POLL_INTERVAL)


# ---------- 启动时自动检测所有平台登录态（方案 A：失败静默） ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """服务启动后，**后台异步**对所有启用平台跑一次 check_status。"""
    enabled = [k for k, v in config.PLATFORMS.items() if v.get("enabled")]
    if enabled:
        print(f"[启动] 自动检测 {len(enabled)} 个平台登录状态…", flush=True)
        asyncio.create_task(_initial_auth_check(enabled))
    asyncio.create_task(_consumption_poll_loop())
    yield
    from core.kafka_producer import shutdown_producer
    await shutdown_producer()


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
        "platforms": config.get_enabled_platforms(),
    })


@app.get("/tasks", response_class=HTMLResponse)
async def tasks_page(request: Request):
    return templates.TemplateResponse(request, "tasks.html", {})


@app.get("/consumption", response_class=HTMLResponse)
async def consumption_page(request: Request):
    return templates.TemplateResponse(request, "consumption.html", {})


@app.get("/terminal", response_class=HTMLResponse)
async def terminal_page(request: Request):
    return templates.TemplateResponse(request, "terminal.html", {})


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


# ---------- API: 对外 detect（同步，固定启用平台全量返回）----------
@app.post("/api/detect")
async def api_detect(request: Request, body: dict):
    """品牌检测统一入口：搜索完成后一次性返回聚合结果。

    请求体::
        {"task_id": "...", "keyword": "西屋", "platforms": [...]}  # platforms 可选

    响应体::
        {"task_id", "brand", "status", "results": [固定4平台], "errors": []}
    """
    task_id = (body.get("task_id") or "").strip()
    keyword = body.get("keyword", "").strip()
    platform_keys = config.filter_platform_keys(body.get("platforms") or [])

    if not task_id:
        return JSONResponse({"error": "task_id 不能为空"}, status_code=400)
    if not keyword:
        return JSONResponse({"error": "关键词不能为空"}, status_code=400)

    from core.task_manager import (
        TaskDuplicateError,
        complete_task,
        create_task,
        fail_task,
        set_task_running,
    )
    from core.search_engine import detect_brand_async, DetectBusyError

    try:
        create_task(task_id, keyword, platform_keys)
    except TaskDuplicateError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    set_task_running(task_id)
    try:
        result = await detect_brand_async(keyword, platform_keys, task_id=task_id)
        complete_task(task_id, result)
        return JSONResponse(result)
    except DetectBusyError:
        fail_task(task_id, "检测任务进行中，请稍后再试")
        return JSONResponse(
            {"error": "检测任务进行中，请稍后再试"},
            status_code=409,
        )
    except Exception as e:
        fail_task(task_id, str(e))
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------- API: 任务管理 ----------
@app.get("/api/tasks")
async def api_tasks_list(task_id: str = "", keyword: str = ""):
    """任务列表；task_id 精确匹配，keyword 品牌名包含匹配，可同时传合并筛选。"""
    from core.task_manager import list_tasks

    items = list_tasks(task_id.strip() or None, keyword.strip() or None)
    return JSONResponse({"list": items, "total": len(items)})


@app.get("/api/tasks/{task_id}")
async def api_task_detail(task_id: str):
    """单任务详情（含完整 result）。"""
    from core.task_manager import get_task

    task = get_task(task_id)
    if not task:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    return JSONResponse(task)


@app.delete("/api/tasks/{task_id}")
async def api_task_delete(task_id: str):
    """删除任务记录。"""
    from core.task_manager import TaskDeleteError, delete_task

    try:
        delete_task(task_id)
        return JSONResponse({"ok": True})
    except KeyError:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    except TaskDeleteError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ---------- API: 消费日志 ----------
@app.get("/api/consumption/logs")
async def api_consumption_logs(task_id: str = "", limit: int = 200):
    """消费日志列表（时间、任务 ID、状态）。"""
    from core.consumption_log import list_logs

    items = list_logs(task_id.strip() or None, limit=limit)
    return JSONResponse({"list": items, "total": len(items)})


@app.get("/api/consumption/status")
async def api_consumption_status():
    """轮询配置状态。"""
    from core.consumption_worker import get_poll_status

    return JSONResponse(get_poll_status())


@app.post("/api/consumption/poll")
async def api_consumption_poll():
    """手动触发一次拉取（与后台轮询逻辑相同）。"""
    from core.consumption_worker import poll_once

    result = await poll_once()
    return JSONResponse(result)


# ---------- API: 终端信息 ----------
@app.get("/api/terminal")
async def api_terminal_info():
    """本机终端 ID、设备名称、版本号。"""
    from core.terminal_info import get_terminal_info

    return JSONResponse(get_terminal_info())


@app.put("/api/terminal")
async def api_terminal_update(request: Request):
    """更新设备名称。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    device_name = (body.get("device_name") or "").strip()

    from core.terminal_info import update_device_name

    try:
        return JSONResponse(update_device_name(device_name))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ---------- API: 搜索 ----------
@app.post("/api/search")
async def api_search(request: Request, body: dict):
    """执行搜索：打开浏览器 → 注入cookie → 各平台搜索 → 返回结果。"""
    keyword = body.get("keyword", "").strip()
    platform_keys = body.get("platforms", [])

    if not keyword:
        return JSONResponse({"error": "关键词不能为空"}, status_code=400)
    if not platform_keys:
        platform_keys = list(config.ENABLED_PLATFORM_KEYS)
    else:
        platform_keys = config.filter_platform_keys(platform_keys)

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
    return JSONResponse(config.get_enabled_platforms())


# ---------- 入口 ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)