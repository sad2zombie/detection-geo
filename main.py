# -*- coding: utf-8 -*-
"""品牌检测系统入口"""

import atexit
import sys
from pathlib import Path

# Windows 下让 print/日志输出正常显示中文
# 方式：直接写 sys.stdout.buffer（绕过 TextIOWrapper 的 GBK 编码层），内容保持 UTF-8
if sys.platform == 'win32':
    class _Utf8Writer:
        def __init__(self, raw_stream):
            self._raw = raw_stream

        def write(self, text):
            if text:
                self._raw.write(text.encode('utf-8', errors='replace'))
                self._raw.flush()

        def flush(self):
            self._raw.flush()

        def isatty(self):
            return self._raw.isatty()

        def fileno(self):
            return self._raw.fileno()

    sys.stdout = _Utf8Writer(sys.stdout.buffer)
    sys.stderr = _Utf8Writer(sys.stderr.buffer)

# ── 单例限制：Windows 命名互斥锁，防止重复启动 ──
if sys.platform == 'win32':
    import ctypes
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, True, "Global\\DetectionApp_Singleton")
    _last_error = ctypes.windll.kernel32.GetLastError()
    if _last_error == 183:  # ERROR_ALREADY_EXISTS
        import ctypes.wintypes
        ctypes.windll.user32.MessageBoxW(
            0, "检测程序已在运行中，请勿重复打开。", "提示", 0x40
        )
        sys.exit(0)

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).parent))

# ── 加载 .env 配置文件（优先级：APPDATA > 项目根目录）──
# 打包后用户只需编辑 %APPDATA%/detection/.env 即可配置 LLM API Key 等参数
import os
from dotenv import load_dotenv

_project_root = Path(__file__).parent
_appdata_env = Path(os.environ.get("APPDATA", "")) / "detection" / ".env"

if _appdata_env.is_file():
    load_dotenv(_appdata_env)
elif (_project_root / ".env").is_file():
    load_dotenv(_project_root / ".env")

# 创建必要的数据目录
from config import DATA_DIR, COOKIE_DIR, RESULTS_DIR
from core.task_manager import TASKS_DIR
for d in [DATA_DIR, COOKIE_DIR, RESULTS_DIR, TASKS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# 运行时终端日志落盘（打包后 console=False 时可在 data/logs/app.log 查看）
from core.runtime_log import setup_runtime_log, RUNTIME_LOG_FILE
_log_path = setup_runtime_log()

# 注册进程退出清理（双保险）
from core.browser_manager import _shutdown_browser_manager
atexit.register(_shutdown_browser_manager)


if __name__ == "__main__":
    import uvicorn
    from web.server import app
    print("=" * 50)
    print("  品牌认证检测系统")
    print("  打开浏览器访问: http://127.0.0.1:8000")
    print(f"  运行日志: {RUNTIME_LOG_FILE}")
    print("=" * 50)
    uvicorn.run(app, host="127.0.0.1", port=8000)
