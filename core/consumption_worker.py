# -*- coding: utf-8 -*-
"""消费任务轮询 — 从服务器拉取任务、执行检测、Kafka 回传结果并写日志。"""

from __future__ import annotations

import asyncio

import httpx

import config
from core.consumption_log import add_log
from core.kafka_producer import build_empty_results, send_result
from core.terminal_info import get_terminal_info

_poll_lock = asyncio.Lock()


def _is_local_busy() -> bool:
    """本地检测或任务进行中时，不可向服务器拉取新任务。"""
    from core.search_engine import is_detect_busy
    from core.task_manager import has_active_local_task

    return is_detect_busy() or has_active_local_task()


def is_poll_in_progress() -> bool:
    """是否已有消费任务在处理中（已拉取，直至回传结束）。"""
    return _poll_lock.locked()


def get_poll_status() -> dict:
    """返回轮询配置与运行状态摘要（供前端展示）。"""
    return {
        "fetch_url": config.CONSUMPTION_FETCH_URL or "",
        "kafka_bootstrap": config.KAFKA_BOOTSTRAP_SERVERS or "",
        "kafka_result_topic": config.KAFKA_RESULT_TOPIC or "",
        "poll_interval": config.CONSUMPTION_POLL_INTERVAL,
        "poll_enabled": config.CONSUMPTION_POLL_ENABLED,
        "configured": bool(
            config.CONSUMPTION_FETCH_URL
            and config.KAFKA_BOOTSTRAP_SERVERS
            and config.KAFKA_RESULT_TOPIC
        ),
        "local_busy": _is_local_busy(),
        "poll_in_progress": is_poll_in_progress(),
    }


async def _fetch_task(client: httpx.AsyncClient, terminal_id: str) -> dict | None:
    """向服务器拉取一条待处理任务。无任务时返回 None。"""
    url = config.CONSUMPTION_FETCH_URL
    resp = await client.get(url, params={"terminal_id": terminal_id})
    if resp.status_code == 204:
        return None
    resp.raise_for_status()
    if not resp.content:
        return None
    data = resp.json()
    if not data:
        return None
    if isinstance(data, dict) and data.get("empty"):
        return None
    task = data.get("task") if isinstance(data, dict) and "task" in data else data
    if not isinstance(task, dict):
        return None
    task_id = str(task.get("task_id") or "").strip()
    if not task_id:
        return None
    return task


async def _publish_to_kafka(result: dict) -> None:
    await send_result(result)


async def _run_detect(task: dict) -> dict:
    """执行品牌检测（与 /api/detect 相同流程）。"""
    from core.search_engine import DetectBusyError, detect_brand_async
    from core.task_manager import (
        create_task,
        complete_task,
        fail_task,
        set_task_running,
    )

    task_id = str(task.get("task_id") or "").strip()
    keyword = str(task.get("keyword") or task.get("brand") or "").strip()
    platform_keys = config.filter_platform_keys(task.get("platforms") or [])

    if not keyword:
        raise ValueError("任务缺少 keyword")

    create_task(task_id, keyword, platform_keys)
    set_task_running(task_id)
    try:
        result = await detect_brand_async(keyword, platform_keys, task_id=task_id)
        complete_task(task_id, result)
        return result
    except DetectBusyError as e:
        fail_task(task_id, str(e))
        raise
    except Exception as e:
        fail_task(task_id, str(e))
        raise


async def poll_once() -> dict:
    """拉取一条任务：入库 → 检测 → Kafka 回传。持锁期间不再向服务器拉取。"""
    if not config.CONSUMPTION_FETCH_URL:
        return {"ok": True, "fetched": False, "reason": "未配置 CONSUMPTION_FETCH_URL"}
    if not config.KAFKA_BOOTSTRAP_SERVERS:
        return {"ok": True, "fetched": False, "reason": "未配置 KAFKA_BOOTSTRAP_SERVERS"}
    if not config.KAFKA_RESULT_TOPIC:
        return {"ok": True, "fetched": False, "reason": "未配置 KAFKA_RESULT_TOPIC"}

    if _poll_lock.locked():
        return {"ok": True, "fetched": False, "reason": "已有消费任务处理中，暂不再拉取"}

    if _is_local_busy():
        return {"ok": True, "fetched": False, "reason": "本地任务执行中，暂不从服务器拉取"}

    async with _poll_lock:
        if _is_local_busy():
            return {"ok": True, "fetched": False, "reason": "本地任务执行中，暂不从服务器拉取"}

        terminal_id = get_terminal_info()["terminal_id"]
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            task = await _fetch_task(client, terminal_id)
            if not task:
                return {"ok": True, "fetched": False, "reason": "暂无新任务"}

            task_id = str(task["task_id"]).strip()
            keyword = str(task.get("keyword") or task.get("brand") or "").strip()
            add_log(task_id, "入库")

            try:
                result = await _run_detect(task)
                await _publish_to_kafka(result)
                outcome = "成功" if result.get("status") == "succeed" else "失败"
                add_log(task_id, outcome)
                return {"ok": True, "fetched": True, "task_id": task_id, "outcome": outcome}
            except Exception as e:
                err_msg = str(e)
                failed_result = {
                    "task_id": task_id,
                    "brand": keyword,
                    "status": "failed",
                    "results": build_empty_results(keyword),
                    "errors": [{"platform": "_global", "message": err_msg}],
                }
                try:
                    await _publish_to_kafka(failed_result)
                except Exception as kafka_err:
                    err_msg = f"{err_msg}; Kafka回传失败: {kafka_err}"
                add_log(task_id, "失败")
                return {
                    "ok": True,
                    "fetched": True,
                    "task_id": task_id,
                    "outcome": "失败",
                    "error": err_msg,
                }
