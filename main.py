# -*- coding: utf-8 -*-
"""品牌检测系统入口"""

import atexit
import sys
from pathlib import Path

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
