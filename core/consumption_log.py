# -*- coding: utf-8 -*-
"""消费日志 — 记录任务拉取、回传结果等状态。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from config import DATA_DIR

LOG_FILE = DATA_DIR / "consumption_logs.json"
LOG_LIMIT = 500

VALID_STATUSES = frozenset({"入库", "成功", "失败"})


def _now_str() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _read_all() -> list[dict]:
    if not LOG_FILE.is_file():
        return []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write_all(entries: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LOG_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    tmp.replace(LOG_FILE)


def add_log(task_id: str, status: str) -> dict:
    """追加一条消费日志。"""
    tid = (task_id or "").strip()
    st = (status or "").strip()
    if not tid:
        raise ValueError("task_id 不能为空")
    if st not in VALID_STATUSES:
        raise ValueError(f"无效状态: {status}")

    entries = _read_all()
    next_id = 1
    if entries:
        next_id = max(int(e.get("id") or 0) for e in entries) + 1

    row = {
        "id": next_id,
        "time": _now_str(),
        "task_id": tid,
        "status": st,
    }
    entries.append(row)
    if len(entries) > LOG_LIMIT:
        entries = entries[-LOG_LIMIT:]
    _write_all(entries)
    return row


def list_logs(task_id: str | None = None, limit: int = 200) -> list[dict]:
    """按时间倒序返回日志；可选 task_id 筛选。"""
    entries = _read_all()
    tid = (task_id or "").strip()
    if tid:
        entries = [e for e in entries if str(e.get("task_id", "")) == tid]
    entries = sorted(entries, key=lambda e: int(e.get("id") or 0), reverse=True)
    return entries[: max(1, min(limit, LOG_LIMIT))]
