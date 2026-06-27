# -*- coding: utf-8 -*-
"""全局配置"""

import os
import sys
from pathlib import Path

# ----- 项目根目录 -----
ROOT_DIR = Path(__file__).parent

# ----- CloakBrowser 路径配置 -----
# 优先从环境变量 CLOAKBROWSER_DIR 读取；未设置时默认找项目根目录下的 cloakbrowser/ 子目录
CLOAKBROWSER_DIR = Path(os.environ.get(
    "CLOAKBROWSER_DIR",
    ROOT_DIR / "cloakbrowser"
))

# ----- 数据目录 -----
# 优先使用环境变量 DETECTION_DATA_DIR（Electron 启动时设置，指向 %APPDATA%/detection/data/）
# 未设置时回退到项目根目录的 data/（开发环境用）
_DETECTION_DATA_DIR_ENV = os.environ.get("DETECTION_DATA_DIR", "").strip()
if _DETECTION_DATA_DIR_ENV:
    DATA_DIR = Path(_DETECTION_DATA_DIR_ENV)
else:
    DATA_DIR = ROOT_DIR / "data"
COOKIE_DIR = DATA_DIR / "cookies"
RESULTS_DIR = DATA_DIR / "results"

# ----- 平台 Cookie 持久化目录 -----
DOUYIN_PROFILE = COOKIE_DIR / "douyin_profile"
BAIDU_PROFILE = COOKIE_DIR / "baidu_profile"
XHS_PROFILE = COOKIE_DIR / "xiaohongshu_profile"
TAOBAO_PROFILE = COOKIE_DIR / "taobao_profile"
JD_PROFILE = COOKIE_DIR / "jd_profile"

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
BROWSER_LAUNCH_RETRIES = 1