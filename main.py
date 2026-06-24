# -*- coding: utf-8 -*-
"""品牌检测系统入口"""

import atexit
import sys
from pathlib import Path

# Windows 下包装 stdout，避免 emoji 导致 gbk 编码错误
# 中文保留，emoji 等超出 GBK 范围的字符自动丢弃
if sys.platform == 'win32':
    class _GBKSafeWriter:
        def __init__(self, raw_stream):
            self._raw = raw_stream

        def write(self, text):
            if text:
                safe = text.encode('gbk', errors='replace')
                self._raw.write(safe)
                self._raw.flush()

        def flush(self):
            self._raw.flush()

        def isatty(self):
            return self._raw.isatty()

        def fileno(self):
            return self._raw.fileno()

    sys.stdout = _GBKSafeWriter(sys.stdout.buffer)
    sys.stderr = _GBKSafeWriter(sys.stderr.buffer)

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
