# -*- coding: utf-8 -*-
"""运行时日志 — 控制台 + 文件双输出（替代业务 print）。"""

from __future__ import annotations

import atexit
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from config import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
RUNTIME_LOG_FILE = LOG_DIR / "app.log"

_log_file = None
_initialized = False


class _TeeWriter:
    """同时写入原 stream 与日志文件（兜底残留 print）。"""

    def __init__(self, stream, file_obj):
        self._stream = stream
        self._file = file_obj

    def write(self, text):
        if not text:
            return 0
        try:
            self._stream.write(text)
        except Exception:
            pass
        try:
            self._file.write(text)
            self._file.flush()
        except Exception:
            pass
        return len(text)

    def flush(self):
        try:
            self._stream.flush()
        except Exception:
            pass
        try:
            self._file.flush()
        except Exception:
            pass

    def isatty(self):
        try:
            return self._stream.isatty()
        except Exception:
            return False

    def fileno(self):
        return self._stream.fileno()


def _close_log_file() -> None:
    global _log_file
    if _log_file is not None:
        try:
            _log_file.flush()
            _log_file.close()
        except Exception:
            pass
        _log_file = None


def _resolve_level() -> int:
    """LOG_LEVEL 环境变量：DEBUG/INFO/WARNING/ERROR，默认 INFO。"""
    try:
        import config
        name = str(getattr(config, "LOG_LEVEL", "INFO") or "INFO").upper()
    except Exception:
        name = os.environ.get("LOG_LEVEL", "INFO").strip().upper() or "INFO"
    return getattr(logging, name, logging.INFO)


def setup_runtime_log() -> Path:
    """初始化运行时日志：文件 + 控制台；并 tee stdout/stderr 兜底残留 print。"""
    global _log_file, _initialized
    if _initialized:
        return RUNTIME_LOG_FILE

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _log_file = open(RUNTIME_LOG_FILE, "a", encoding="utf-8", buffering=1)

    started = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    _log_file.write(f"\n{'=' * 60}\n[{started}] 进程启动\n")
    _log_file.flush()

    # 先保留「真实」控制台流，再 tee（避免 logging StreamHandler 经 tee 导致文件重复写入）
    console_out = sys.stdout
    console_err = sys.stderr
    sys.stdout = _TeeWriter(console_out, _log_file)
    sys.stderr = _TeeWriter(console_err, _log_file)

    level = _resolve_level()
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = logging.FileHandler(RUNTIME_LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(level)
    sh = logging.StreamHandler(console_out)
    sh.setFormatter(fmt)
    sh.setLevel(level)
    root.addHandler(fh)
    root.addHandler(sh)

    # 降噪第三方库
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("aiokafka").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    atexit.register(_close_log_file)
    _initialized = True
    return RUNTIME_LOG_FILE
