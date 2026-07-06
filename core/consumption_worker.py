# -*- coding: utf-8 -*-
"""消费任务轮询 — 从服务器拉取任务、执行检测、Kafka 回传结果并写日志。"""

from __future__ import annotations

import asyncio

import httpx

import config
from core.consumption_log import add_log
from core.kafka_producer import build_empty_result, send_result

_poll_lock = asyncio.Lock()


def _is_platform_busy(platform_key: str) -> bool:
    """指定平台是否忙碌（本地任务或正在检测）。"""
    from core.search_engine import is_platform_detect_busy
    from core.task_manager import has_active_local_task_for_platform

    return (
        has_active_local_task_for_platform(platform_key)
        or is_platform_detect_busy(platform_key)
    )


def _busy_platform_keys() -> list[str]:
    return [p for p in config.ENABLED_PLATFORM_KEYS if _is_platform_busy(p)]


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
            and config.TERMINAL_KEY
            and config.KAFKA_BOOTSTRAP_SERVERS
            and config.KAFKA_RESULT_TOPIC
        ),
        "kafka_configured": bool(
            config.KAFKA_BOOTSTRAP_SERVERS
            and config.KAFKA_RESULT_TOPIC
        ),
        "busy_platforms": _busy_platform_keys(),
        "local_busy": bool(_busy_platform_keys()),
        "poll_in_progress": is_poll_in_progress(),
    }


async def _fetch_task(client: httpx.AsyncClient, platform_key: str) -> dict | None:
    """向服务器拉取一条待处理任务。

    请求体：``{"terminalId": "...", "platform": "douyin"}``
    响应体::

        {"code": 0, "msg": "操作成功", "data": {"taskId": 1, "keyword": "...", "platform": "..."}}

    无任务时 ``code`` 非 0（如 ``500`` / ``没有可执行任务``），或 ``data`` 为空，返回 None。
    """
    from core.terminal_info import get_terminal_info

    terminal_id = get_terminal_info()["terminal_id"]
    url = config.CONSUMPTION_FETCH_URL
    resp = await client.post(
        url,
        json={"terminalId": terminal_id, "platform": platform_key},
        headers={
            "Content-Type": "application/json",
            "x-terminal-key": config.TERMINAL_KEY,
        },
    )
    if resp.status_code == 204:
        return None
    resp.raise_for_status()
    if not resp.content:
        return None
    body = resp.json()
    if not isinstance(body, dict) or not body:
        return None

    code = body.get("code")
    if str(code) != "0":
        return None

    data = body.get("data")
    if not isinstance(data, dict) or not data:
        return None

    task_id = str(data.get("taskId") or data.get("task_id") or "").strip()
    keyword = str(data.get("keyword") or "").strip()
    platform_raw = data.get("platform")
    if not task_id or not keyword or platform_raw in (None, "", []):
        return None
    try:
        platform = config.normalize_platform(platform_raw)
    except ValueError:
        return None
    if platform != platform_key:
        print(
            f"[Consumption] 服务器返回 platform={platform_raw!r} 与请求 {platform_key!r} 不一致，已忽略",
            flush=True,
        )
        return None
    return {
        "task_id": task_id,
        "keyword": keyword,
        "platform": platform,
    }


async def _wait_for_detect_idle() -> None:
    """等待其他平台检测结束（本机同时只跑一个检测）。"""
    from core.search_engine import is_detect_busy

    while is_detect_busy():
        await asyncio.sleep(0.5)


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
    keyword = str(task.get("keyword") or "").strip()
    platform_key = config.normalize_platform(task.get("platform"))

    if not keyword:
        raise ValueError("任务缺少 keyword")

    create_task(task_id, keyword, [platform_key])
    set_task_running(task_id)
    try:
        result = await detect_brand_async(keyword, platform_key, task_id=task_id)
        complete_task(task_id, result)
        return result
    except DetectBusyError as e:
        fail_task(task_id, str(e))
        raise
    except Exception as e:
        fail_task(task_id, str(e))
        raise


async def poll_once() -> dict:
    """按平台依次向服务器拉取任务：入库 → 检测 → Kafka 回传。"""
    if not config.CONSUMPTION_FETCH_URL:
        return {"ok": True, "fetched": False, "reason": "未配置 CONSUMPTION_FETCH_URL"}
    if not config.TERMINAL_KEY:
        return {"ok": True, "fetched": False, "reason": "未配置 TERMINAL_KEY"}
    if not config.KAFKA_BOOTSTRAP_SERVERS:
        return {"ok": True, "fetched": False, "reason": "未配置 KAFKA_BOOTSTRAP_SERVERS"}
    if not config.KAFKA_RESULT_TOPIC:
        return {"ok": True, "fetched": False, "reason": "未配置 KAFKA_RESULT_TOPIC"}

    if _poll_lock.locked():
        return {"ok": True, "fetched": False, "reason": "已有消费任务处理中，暂不再拉取"}

    async with _poll_lock:
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            task = None
            for platform_key in config.ENABLED_PLATFORM_KEYS:
                if _is_platform_busy(platform_key):
                    print(
                        f"[Consumption] 平台忙碌，跳过拉取 platform={platform_key}",
                        flush=True,
                    )
                    continue
                print(f"[Consumption] 拉取任务 platform={platform_key}", flush=True)
                task = await _fetch_task(client, platform_key)
                if task:
                    break

            if not task:
                return {"ok": True, "fetched": False, "reason": "暂无新任务"}

            task_id = str(task["task_id"]).strip()
            keyword = task["keyword"]
            platform_key = task["platform"]
            print(
                f"[Consumption] 收到任务 task_id={task_id} keyword={keyword} platform={platform_key}",
                flush=True,
            )
            add_log(task_id, "入库")

            try:
                await _wait_for_detect_idle()
                result = await _run_detect(task)
                await _publish_to_kafka(result)
                outcome = "成功" if result.get("status") == "succeed" else "失败"
                add_log(task_id, outcome)
                return {
                    "ok": True,
                    "fetched": True,
                    "task_id": task_id,
                    "platform": platform_key,
                    "outcome": outcome,
                }
            except Exception as e:
                err_msg = str(e)
                failed_result = build_empty_result(
                    keyword, platform_key, task_id=task_id, error=err_msg
                )
                try:
                    await _publish_to_kafka(failed_result)
                except Exception as kafka_err:
                    err_msg = f"{err_msg}; Kafka回传失败: {kafka_err}"
                add_log(task_id, "失败")
                return {
                    "ok": True,
                    "fetched": True,
                    "task_id": task_id,
                    "platform": platform_key,
                    "outcome": "失败",
                    "error": err_msg,
                }

