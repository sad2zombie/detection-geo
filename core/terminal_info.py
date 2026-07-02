# -*- coding: utf-8 -*-
"""本机终端信息 — 终端 ID、设备名称、版本号。"""

from __future__ import annotations

import json
import socket
import uuid
from pathlib import Path

from config import APP_VERSION, DATA_DIR

TERMINAL_FILE = DATA_DIR / "terminal.json"
_DEVICE_NAME_MAX_LEN = 64


def _default_device_name() -> str:
    try:
        return socket.gethostname() or "本机"
    except OSError:
        return "本机"


def _read_raw() -> dict:
    if not TERMINAL_FILE.is_file():
        return {}
    try:
        with open(TERMINAL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_raw(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = TERMINAL_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(TERMINAL_FILE)


def get_terminal_info() -> dict:
    """返回终端 ID、设备名称、应用版本。"""
    data = _read_raw()
    changed = False

    if not str(data.get("terminal_id") or "").strip():
        data["terminal_id"] = str(uuid.uuid4())
        changed = True
    if not str(data.get("device_name") or "").strip():
        data["device_name"] = _default_device_name()
        changed = True

    if changed:
        _write_raw(data)

    return {
        "terminal_id": data["terminal_id"],
        "device_name": data["device_name"],
        "version": APP_VERSION,
    }


def update_device_name(name: str) -> dict:
    """更新设备名称（前端可自定义）。"""
    cleaned = (name or "").strip()
    if not cleaned:
        raise ValueError("设备名称不能为空")
    if len(cleaned) > _DEVICE_NAME_MAX_LEN:
        raise ValueError(f"设备名称不能超过 {_DEVICE_NAME_MAX_LEN} 个字符")

    data = _read_raw()
    if not str(data.get("terminal_id") or "").strip():
        data["terminal_id"] = str(uuid.uuid4())
    data["device_name"] = cleaned
    _write_raw(data)
    return get_terminal_info()
