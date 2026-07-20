# -*- coding: utf-8 -*-
"""检测忙锁 — 保证同一时刻只有一个 detect 流程在跑。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator


class DetectBusyError(Exception):
    """已有 detect 任务在执行，拒绝并发请求。"""


_detect_running = False
_detect_current_platform: str | None = None
_detect_state_lock: asyncio.Lock | None = None


def _get_detect_state_lock() -> asyncio.Lock:
    global _detect_state_lock
    if _detect_state_lock is None:
        _detect_state_lock = asyncio.Lock()
    return _detect_state_lock


def is_detect_busy() -> bool:
    """是否有检测流程正在执行（/api/detect、任务管理、消费拉取共用）。"""
    return _detect_running


def get_detect_current_platform() -> str | None:
    """当前正在检测的平台 key；无检测时为 None。"""
    return _detect_current_platform


def is_platform_detect_busy(platform_key: str) -> bool:
    """指定平台是否正在执行检测。"""
    return _detect_running and _detect_current_platform == platform_key


async def begin_detect(platform_key: str) -> None:
    """占用检测槽；已有任务时抛 DetectBusyError。"""
    global _detect_running, _detect_current_platform
    async with _get_detect_state_lock():
        if _detect_running:
            raise DetectBusyError()
        _detect_running = True
        _detect_current_platform = platform_key


async def end_detect() -> None:
    """释放检测槽。"""
    global _detect_running, _detect_current_platform
    async with _get_detect_state_lock():
        _detect_running = False
        _detect_current_platform = None


@asynccontextmanager
async def detect_slot(platform_key: str) -> AsyncIterator[None]:
    """检测忙锁上下文：进入时占用，离开时释放。"""
    await begin_detect(platform_key)
    try:
        yield
    finally:
        await end_detect()
