# -*- coding: utf-8 -*-
"""LLM 客户端 —— OpenAI 兼容 API + Function Calling（非流式）。

移植自 huoshangeo-master/app/services/llm_client.py，
删除流式分支，settings.* → config.*。
"""

import asyncio
import json
import httpx

import config


async def llm_chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    tool_choice: str = "auto",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: float = 120.0,
) -> dict:
    """
    调用 LLM Chat Completion API（非流式，支持 Function Calling）。

    Returns:
        { "content": str, "tool_calls": list, "finish_reason": str, "usage": dict }
    """
    api_base = config.LLM_API_BASE.rstrip("/")
    if not api_base.endswith("/v1"):
        api_base += "/v1"
    url = f"{api_base}/chat/completions"

    payload: dict = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice

    max_retries = 2
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {config.LLM_API_KEY}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            choice = data["choices"][0]
            finish_reason = choice.get("finish_reason", "stop")

            if choice["message"].get("tool_calls"):
                return {
                    "content": choice["message"].get("content") or "",
                    "tool_calls": _normalize_tool_calls(choice["message"]["tool_calls"]),
                    "finish_reason": finish_reason,
                    "usage": _extract_usage(data),
                }

            return {
                "content": choice["message"].get("content") or "",
                "tool_calls": [],
                "finish_reason": finish_reason,
                "usage": _extract_usage(data),
            }

        except Exception as e:
            last_error = e
            if attempt < max_retries and _is_transient_error(str(e)):
                await asyncio.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"LLM API 调用失败: {e}") from e

    raise RuntimeError(f"LLM API 调用失败（已重试 {max_retries} 次）: {last_error}")


def _normalize_tool_calls(tool_calls: list[dict]) -> list[dict]:
    """标准化 tool_calls 格式。"""
    result = []
    for tc in tool_calls:
        fn = tc.get("function", {})
        normalized = {
            "id": tc.get("id") or "",
            "type": "function",
            "function": {
                "name": fn.get("name") or "",
                "arguments": fn.get("arguments") or "",
            },
        }
        if "index" in tc:
            normalized["index"] = tc["index"]
        result.append(normalized)
    return result


def _extract_usage(data: dict) -> dict:
    """提取 token 用量信息。"""
    usage = data.get("usage", {})
    return {
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }


def _is_transient_error(err_str: str) -> bool:
    """判断是否瞬时错误（值得重试）。"""
    markers = [
        "429", "rate limit",
        "500", "502", "503", "504",
        "overloaded", "timeout", "timed out",
        "connection", "server error", "temporarily unavailable",
    ]
    err_lower = err_str.lower()
    return any(m in err_lower for m in markers)
