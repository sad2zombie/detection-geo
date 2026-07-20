# -*- coding: utf-8 -*-
"""博查 AI 搜索适配器。"""

from __future__ import annotations

import logging

import httpx

import config

logger = logging.getLogger(__name__)

async def _search_bocha(query: str, max_results: int = 5) -> list[dict]:
    """博查 AI 搜索 API（https://open.bochaai.com），中文搜索质量最佳。"""
    if not config.BOCHA_API_KEY:
        return [{"title": "配置错误", "url": "", "snippet": "BOCHA_API_KEY 未配置"}]

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(
                "https://api.bochaai.com/v1/web-search",
                headers={
                    "Authorization": f"Bearer {config.BOCHA_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "query": query,
                    "freshness": "noLimit",
                    "summary": True,
                    "count": min(max_results, 10),
                },
            )
            resp.raise_for_status()
            body = resp.json()

            # 兼容两种格式：结果在顶层 webPages 或 data.webPages
            data = body.get("data", body) if isinstance(body, dict) else body
            results = []
            for item in data.get("webPages", {}).get("value", [])[:max_results]:
                results.append({
                    "title": item.get("name", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("summary", "") or item.get("snippet", ""),
                })
            logger.info(f"[Bocha] 查询: {query}, 解析到 {len(results)} 条结果")
            return results
        except Exception as e:
            logger.error(f"[Bocha] 请求异常: {type(e).__name__}: {e}")
            return [{"title": "搜索错误", "url": "", "snippet": f"博查搜索失败: {e}"}]
