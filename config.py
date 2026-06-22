# -*- coding: utf-8 -*-
"""全局配置"""

import os
from pathlib import Path

# ----- 项目根目录 -----
ROOT_DIR = Path(__file__).parent

# ----- CloakBrowser 路径配置 -----
# cloakbrowser 已通过 pip install 安装，以下路径仅作备用（当 env var CLOAKBROWSER_DIR 设置时优先使用环境变量）。
# 正常情况下 config.py 所在项目无需修改此路径。
CLOAKBROWSER_DIR = Path(os.environ.get("CLOAKBROWSER_DIR",
    r"C:\Users\Administrator\PycharmProjects\CloakBrowser-main"))

# ----- 数据目录 -----
DATA_DIR = ROOT_DIR / "data"
COOKIE_DIR = DATA_DIR / "cookies"
RESULTS_DIR = DATA_DIR / "results"
REPORT_DIR = DATA_DIR / "reports"

# ----- 平台 Cookie 持久化目录 -----
DOUYIN_PROFILE = COOKIE_DIR / "douyin_profile"
BAIDU_PROFILE = COOKIE_DIR / "baidu_profile"
XHS_PROFILE = COOKIE_DIR / "xiaohongshu_profile"
TAOBAO_PROFILE = COOKIE_DIR / "taobao_profile"
JD_PROFILE = COOKIE_DIR / "jd_profile"

# ----- 阿里百炼 API 配置 -----
BAILIAN_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
BAILIAN_MODEL = "qwen3.7-plus"  # 分析用模型

# ----- 支持的平台列表 -----
PLATFORMS = {
    "douyin": {
        "name": "抖音",
        "icon": "🎵",
        "enabled": True,
    },
    "baidu": {
        "name": "百度",
        "icon": "🔍",
        "enabled": True,
    },
    "xiaohongshu": {
        "name": "小红书",
        "icon": "📕",
        "enabled": True,
    },
    "taobao": {
        "name": "淘宝",
        "icon": "🛒",
        "enabled": True,
    },
    "jd": {
        "name": "京东",
        "icon": "📦",
        "enabled": True,
    },
}

# ----- 认证类型标签 -----
VERIFICATION_LABELS = {
    "blue_v": "🔵 蓝V(企业认证)",
    "yellow_v": "🟡 黄V(个人认证)",
    "official": "✅ 官方认证",
    "verified": "✓ 已认证",
    "none": "❌ 无认证",
    "unknown": "❓ 未知",
}

# ----- 浏览器配置 -----
# BROWSER_HEADLESS: 默认无头模式（不弹出窗口），适合服务端自动化检测。
# 设为 False 可切换到有头调试模式（用户登录场景必须用有头）。
# 优先级：环境变量 BROWSER_HEADLESS > 这里的默认值。
_BROWSER_HEADLESS_ENV = os.environ.get("BROWSER_HEADLESS", "").strip().lower()
if _BROWSER_HEADLESS_ENV in ("0", "false", "no", "off"):
    BROWSER_HEADLESS = False
elif _BROWSER_HEADLESS_ENV in ("1", "true", "yes", "on"):
    BROWSER_HEADLESS = True
else:
    # 兼容旧行为：默认无头
    BROWSER_HEADLESS = True
# BROWSER_LAUNCH_TIMEOUT: 浏览器启动超时时间（秒）
BROWSER_LAUNCH_TIMEOUT = 30
# BROWSER_IDLE_TIMEOUT: 浏览器空闲超时（秒），无任务时自动关闭
BROWSER_IDLE_TIMEOUT = 300
# BROWSER_LAUNCH_RETRIES: 启动失败时自动重试次数（清理锁文件后重试）
BROWSER_LAUNCH_RETRIES = 1

BAILIAN_API_KEY = "sk-e87fc55a6d7343fa9bfd83d8be1724be"