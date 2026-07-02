# -*- coding: utf-8 -*-
"""运行时终端日志 — 将 stdout/stderr 同步写入文件（打包后无控制台时仍可查）。"""

from __future__ import annotations

import atexit
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from config import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
RUNTIME_LOG_FILE = LOG_DIR / "app.log"

_log_file = None
_initialized = False


class _TeeWriter:
    """同时写入原 stream 与日志文件。"""

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


def setup_runtime_log() -> Path:
    """初始化运行时日志文件，并接管 stdout/stderr。"""
    global _log_file, _initialized
    if _initialized:
        return RUNTIME_LOG_FILE

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _log_file = open(RUNTIME_LOG_FILE, "a", encoding="utf-8", buffering=1)

    started = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    _log_file.write(f"\n{'=' * 60}\n[{started}] 进程启动\n")
    _log_file.flush()

    sys.stdout = _TeeWriter(sys.stdout, _log_file)
    sys.stderr = _TeeWriter(sys.stderr, _log_file)

    handler = logging.FileHandler(RUNTIME_LOG_FILE, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    atexit.register(_close_log_file)
    _initialized = True
    return RUNTIME_LOG_FILE
