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

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).parent))

# 创建必要的数据目录
from config import DATA_DIR, COOKIE_DIR, RESULTS_DIR
for d in [DATA_DIR, COOKIE_DIR, RESULTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# 注册进程退出清理（双保险）
from core.browser_manager import _shutdown_browser_manager
atexit.register(_shutdown_browser_manager)


if __name__ == "__main__":
    import uvicorn
    from web.server import app
    print("=" * 50)
    print("  品牌认证检测系统")
    print("  打开浏览器访问: http://127.0.0.1:8000")
    print("=" * 50)
    uvicorn.run(app, host="127.0.0.1", port=8000)
