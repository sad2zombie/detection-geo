# -*- coding: utf-8 -*-
"""检测任务持久化 — JSON 文件存储，供 /api/detect 与任务管理页使用。"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from config import DATA_DIR

TASKS_DIR = DATA_DIR / "tasks"
TASK_LIST_LIMIT = 50

_ACTIVE_STATUSES = frozenset({"pending", "running"})


class TaskDuplicateError(Exception):
    """task_id 已存在或任务进行中。"""


class TaskDeleteError(Exception):
    """任务不可删除。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _task_path(task_id: str) -> Path:
    safe = re.sub(r'[^\w.\-]', "_", task_id.strip())
    if not safe:
        raise ValueError("task_id 无效")
    return TASKS_DIR / f"{safe}.json"


def _read_task(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _write_task(path: Path, data: dict) -> None:
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def create_task(task_id: str, keyword: str, platforms: list[str]) -> dict:
    """创建任务记录（pending）。进行中任务不可覆盖；已完成/失败任务可覆盖。"""
    path = _task_path(task_id)
    existing = _read_task(path)
    if existing:
        status = existing.get("status", "")
        if status in _ACTIVE_STATUSES:
            raise TaskDuplicateError("该任务正在执行中")

    task = {
        "task_id": task_id,
        "keyword": keyword,
        "platforms": platforms,
        "status": "pending",
        "created_at": _now_iso() if not existing else existing.get("created_at", _now_iso()),
        "started_at": "",
        "finished_at": "",
        "result": None,
        "error_message": "",
    }
    _write_task(path, task)
    return task


def set_task_running(task_id: str) -> dict:
    path = _task_path(task_id)
    task = _read_task(path)
    if not task:
        raise KeyError(f"任务不存在: {task_id}")
    task["status"] = "running"
    task["started_at"] = _now_iso()
    _write_task(path, task)
    return task


def complete_task(task_id: str, result: dict) -> dict:
    path = _task_path(task_id)
    task = _read_task(path)
    if not task:
        raise KeyError(f"任务不存在: {task_id}")
    task["status"] = result.get("status", "succeed")
    task["finished_at"] = _now_iso()
    task["result"] = result
    task["error_message"] = ""
    _write_task(path, task)
    return task


def fail_task(task_id: str, message: str, status: str = "failed") -> dict:
    path = _task_path(task_id)
    task = _read_task(path)
    if not task:
        raise KeyError(f"任务不存在: {task_id}")
    task["status"] = status
    task["finished_at"] = _now_iso()
    task["error_message"] = message
    _write_task(path, task)
    return task


def get_task(task_id: str) -> dict | None:
    return _read_task(_task_path(task_id))


def delete_task(task_id: str) -> None:
    """删除任务记录。进行中的任务不可删除。"""
    path = _task_path(task_id)
    task = _read_task(path)
    if not task:
        raise KeyError(f"任务不存在: {task_id}")
    if task.get("status") in _ACTIVE_STATUSES:
        raise TaskDeleteError("进行中的任务不可删除")
    path.unlink(missing_ok=True)


def has_active_local_task() -> bool:
    """是否存在进行中的本地任务（pending / running）。"""
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    for path in TASKS_DIR.glob("*.json"):
        if path.name.endswith(".tmp"):
            continue
        task = _read_task(path)
        if task and task.get("status") in _ACTIVE_STATUSES:
            return True
    return False


def list_tasks(
    task_id: str | None = None,
    keyword: str | None = None,
    limit: int = TASK_LIST_LIMIT,
) -> list[dict]:
    """任务列表摘要。task_id 精确匹配；keyword 为品牌名包含匹配；两者同时传时为 AND 合并筛选。"""
    TASKS_DIR.mkdir(parents=True, exist_ok=True)

    tid = (task_id or "").strip()
    kw = (keyword or "").strip()

    if not tid and not kw:
        files = sorted(TASKS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        items: list[dict] = []
        for path in files:
            if path.name.endswith(".tmp"):
                continue
            task = _read_task(path)
            if task:
                items.append(_task_summary(task))
            if len(items) >= limit:
                break
        return items

    if tid and not kw:
        task = get_task(tid)
        if not task:
            return []
        return [_task_summary(task)]

    files = sorted(TASKS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    items: list[dict] = []
    for path in files:
        if path.name.endswith(".tmp"):
            continue
        task = _read_task(path)
        if not task:
            continue
        if tid and str(task.get("task_id", "")).strip() != tid:
            continue
        if kw and kw not in str(task.get("keyword", "")):
            continue
        items.append(_task_summary(task))
        if len(items) >= limit:
            break
    return items


def _task_summary(task: dict) -> dict:
    return {
        "task_id": task.get("task_id", ""),
        "keyword": task.get("keyword", ""),
        "status": task.get("status", ""),
        "created_at": task.get("created_at", ""),
    }
