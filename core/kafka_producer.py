# -*- coding: utf-8 -*-
"""Kafka 结果回传 — 任务结束后发送一条消息到结果 topic。"""

from __future__ import annotations

import json

import config

_producer = None


def build_empty_results(brand: str) -> list[dict]:
    """4 平台空结果结构（异常时兜底）。"""
    return [
        {
            "platform": "official_website",
            "brand_name": brand,
            "website": "",
            "description": "",
        },
        {"platform": "douyin", "users": []},
        {"platform": "xiaohongshu", "users": []},
        {"platform": "baidu", "score": 0, "assessment_grade": ""},
    ]


def _format_platform_result(r: dict) -> dict | None:
    platform = r.get("platform")
    if platform == "official_website":
        return {
            "platform": "official_website",
            "brand_name": r.get("brand_name", ""),
            "website": r.get("website", ""),
            "description": r.get("description", ""),
        }
    if platform == "douyin":
        return {
            "platform": "douyin",
            "users": [
                {
                    "name": u.get("name", ""),
                    "profile_url": u.get("profile_url", ""),
                    "douyin_id": u.get("douyin_id", ""),
                }
                for u in (r.get("users") or [])
            ],
        }
    if platform == "xiaohongshu":
        return {
            "platform": "xiaohongshu",
            "users": [
                {
                    "name": u.get("name", ""),
                    "profile_url": u.get("profile_url", ""),
                    "xhs_id": u.get("xhs_id", ""),
                }
                for u in (r.get("users") or [])
            ],
        }
    if platform == "baidu":
        score = r.get("score", 0)
        if score == "" or score is None:
            score = 0
        return {
            "platform": "baidu",
            "score": int(score),
            "assessment_grade": r.get("assessment_grade", ""),
        }
    return None


def prepare_kafka_payload(result: dict) -> dict:
    """将 detect 结果格式化为 Kafka 出站契约。"""
    errors = result.get("errors") or []
    raw_status = result.get("status", "")
    status = "succeed" if raw_status == "succeed" and not errors else "failed"

    by_platform: dict[str, dict] = {}
    for r in result.get("results") or []:
        formatted = _format_platform_result(r)
        if formatted:
            by_platform[formatted["platform"]] = formatted

    brand = result.get("brand", "")
    results_out = []
    for p in config.ENABLED_PLATFORM_KEYS:
        if p in by_platform:
            results_out.append(by_platform[p])
        elif p == "official_website":
            results_out.append({
                "platform": "official_website",
                "brand_name": brand,
                "website": "",
                "description": "",
            })
        elif p == "douyin":
            results_out.append({"platform": "douyin", "users": []})
        elif p == "xiaohongshu":
            results_out.append({"platform": "xiaohongshu", "users": []})
        elif p == "baidu":
            results_out.append({"platform": "baidu", "score": 0, "assessment_grade": ""})

    return {
        "task_id": result.get("task_id", ""),
        "brand": brand,
        "status": status,
        "results": results_out,
        "errors": errors,
    }


async def _get_producer():
    global _producer
    if _producer is None:
        from aiokafka import AIOKafkaProducer

        _producer = AIOKafkaProducer(
            bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
        )
        await _producer.start()
    return _producer


async def send_result(result: dict) -> None:
    """发送检测结果到 Kafka 结果 topic。"""
    if not config.KAFKA_RESULT_TOPIC:
        raise ValueError("未配置 KAFKA_RESULT_TOPIC")
    if not config.KAFKA_BOOTSTRAP_SERVERS:
        raise ValueError("未配置 KAFKA_BOOTSTRAP_SERVERS")

    payload = prepare_kafka_payload(result)
    producer = await _get_producer()
    await producer.send_and_wait(config.KAFKA_RESULT_TOPIC, payload)
    print(
        f"[Kafka] 已发送 task_id={payload.get('task_id')} status={payload.get('status')} "
        f"topic={config.KAFKA_RESULT_TOPIC}",
        flush=True,
    )


async def shutdown_producer() -> None:
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None
