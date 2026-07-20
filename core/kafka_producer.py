# -*- coding: utf-8 -*-
"""Kafka 结果回传 — 任务结束后发送一条消息到结果 topic。"""

from __future__ import annotations

import json

import config

_producer = None


def build_empty_result(brand: str, platform: str, task_id: str = "", error: str = "") -> dict:
    """单平台空结果（异常时兜底）。"""
    from core.detect_result import empty_platform_result, format_detect_errors

    return {
        "task_id": task_id,
        "brand": brand,
        "status": "failed",
        "results": empty_platform_result(platform, brand),
        "errors": format_detect_errors(
            [{"platform": platform, "message": error}] if error else []
        ),
    }


def prepare_kafka_payload(result: dict) -> dict:
    """将 detect 结果格式化为 Kafka 出站契约（单平台）。"""
    errors_raw = result.get("errors")
    if isinstance(errors_raw, list):
        from core.detect_result import format_detect_errors
        errors = format_detect_errors(errors_raw)
    else:
        errors = str(errors_raw or "")

    status = result.get("status", "")
    if status != "succeed" or errors:
        status = "failed"
    else:
        status = "succeed"

    results = result.get("results") or {}
    if isinstance(results, list):
        results = results[0] if results else {}

    return {
        "task_id": result.get("task_id", ""),
        "brand": result.get("brand", ""),
        "status": status,
        "results": results,
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
        f"[Kafka] 已发送 task_id={payload.get('task_id')} "
        f"platform={payload.get('results', {}).get('platform')} "
        f"status={payload.get('status')} topic={config.KAFKA_RESULT_TOPIC}",
        flush=True,
    )


async def shutdown_producer() -> None:
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None
