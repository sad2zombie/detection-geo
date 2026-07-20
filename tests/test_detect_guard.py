# -*- coding: utf-8 -*-
import asyncio

import pytest

from core import detect_guard
from core.detect_guard import (
    DetectBusyError,
    begin_detect,
    detect_slot,
    end_detect,
    get_detect_current_platform,
    is_detect_busy,
    is_platform_detect_busy,
)


@pytest.fixture(autouse=True)
def _reset_detect_guard_state():
    """每个用例前后清空忙锁全局状态，避免互相污染。"""
    detect_guard._detect_running = False
    detect_guard._detect_current_platform = None
    yield
    detect_guard._detect_running = False
    detect_guard._detect_current_platform = None


def test_detect_slot_sets_and_clears_busy():
    async def _run():
        assert is_detect_busy() is False
        async with detect_slot("baidu"):
            assert is_detect_busy() is True
            assert get_detect_current_platform() == "baidu"
            assert is_platform_detect_busy("baidu") is True
            assert is_platform_detect_busy("douyin") is False
        assert is_detect_busy() is False
        assert get_detect_current_platform() is None

    asyncio.run(_run())


def test_second_begin_raises_busy():
    async def _run():
        await begin_detect("douyin")
        with pytest.raises(DetectBusyError):
            await begin_detect("baidu")
        await end_detect()
        assert is_detect_busy() is False

    asyncio.run(_run())


def test_detect_slot_releases_on_exception():
    async def _run():
        with pytest.raises(RuntimeError):
            async with detect_slot("xiaohongshu"):
                raise RuntimeError("boom")
        assert is_detect_busy() is False

    asyncio.run(_run())


def test_search_engine_reexports_guard_symbols():
    from core.search_engine import (
        DetectBusyError as SEBusy,
        get_detect_current_platform as se_plat,
        is_detect_busy as se_busy,
        is_platform_detect_busy as se_plat_busy,
    )

    assert SEBusy is DetectBusyError
    assert se_busy is is_detect_busy
    assert se_plat is get_detect_current_platform
    assert se_plat_busy is is_platform_detect_busy
