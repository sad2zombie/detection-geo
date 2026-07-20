# -*- coding: utf-8 -*-
"""llm_client enable_search 合并语义。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.parametrize(
    "extra_body,expected",
    [
        (None, True),
        ({}, True),
        ({"enable_search": True}, True),
        ({"enable_search": False}, False),
    ],
)
def test_enable_search_respects_explicit_value(extra_body, expected):
    captured = {}

    async def _fake_post(url, json=None, headers=None):
        captured["payload"] = json
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {},
        }
        return resp

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        post = AsyncMock(side_effect=_fake_post)

    async def _run():
        with patch("core.llm_client.httpx.AsyncClient", _FakeClient), patch(
            "core.llm_client.config"
        ) as cfg:
            cfg.LLM_API_BASE = "https://example.com/v1"
            cfg.LLM_MODEL = "test-model"
            cfg.LLM_API_KEY = "k"
            from core.llm_client import llm_chat

            await llm_chat([{"role": "user", "content": "hi"}], extra_body=extra_body)

    import asyncio

    asyncio.run(_run())
    assert captured["payload"]["enable_search"] is expected
