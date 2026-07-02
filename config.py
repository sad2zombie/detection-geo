# -*- coding: utf-8 -*-
"""全局配置"""

import os
import sys
from pathlib import Path

# ----- 项目根目录 -----
ROOT_DIR = Path(__file__).parent

# ----- CloakBrowser 路径配置 -----
# 业务侧用 CloakBrowser 的 stealth Chromium，不依赖 Playwright。
#
# 解析顺序：
#   1. 环境变量 CLOAKBROWSER_DIR（用户/部署环境显式指定）
#   2. frozen 环境：runtime_hook 会把 _MEIPASS/cloakbrowser 塞到 sys.path，这里返回空字符串
#      （_ensure_cloakbrowser 会从 sys 中已经注入的路径定位，不再硬性要求目录存在）
#   3. 开发环境：项目根目录下的 cloakbrowser/ 子目录
import os as _os
import sys as _sys

if getattr(_sys, "frozen", False):
    _BUNDLE_DIR = Path(getattr(_sys, "_MEIPASS", _os.path.dirname(_sys.executable)))
    # 在 frozen 环境下，runtime_hook 已把 _MEIPASS/cloakbrowser 加到 sys.path，
    # cloakbrowser 包作为数据文件在 _MEIPASS/cloakbrowser/ 下。这里返回一个无害的占位路径，
    # _ensure_cloakbrowser() 中的"目录存在性检查"会被跳过，因为它已经在 sys.path 中。
    CLOAKBROWSER_DIR = _BUNDLE_DIR / "cloakbrowser"
else:
    CLOAKBROWSER_DIR = Path(_os.environ.get(
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

# ----- 应用版本（打包时由 Electron 注入 DETECTION_APP_VERSION）-----
def _read_package_version() -> str:
    try:
        import json
        pkg = ROOT_DIR / "package.json"
        if pkg.is_file():
            with open(pkg, "r", encoding="utf-8") as f:
                return str(json.load(f).get("version") or "dev")
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return "dev"


APP_VERSION = os.environ.get("DETECTION_APP_VERSION", "").strip() or _read_package_version()
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
        "requires_login": True,
    },
    "baidu": {
        "name": "百度",
        "icon": "🔍",
        "enabled": True,
        "requires_login": False,
    },
    "xiaohongshu": {
        "name": "小红书",
        "icon": "📕",
        "enabled": True,
        "requires_login": True,
    },
    "taobao": {
        "name": "淘宝",
        "icon": "🛒",
        "enabled": False,
        "requires_login": True,
    },
    "jd": {
        "name": "京东",
        "icon": "📦",
        "enabled": False,
        "requires_login": True,
    },
    "official_website": {
        "name": "官网",
        "icon": "🏢",
        "enabled": True,
        "requires_login": False,
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

# ----- 对外 detect 接口超时（秒）-----
DETECT_TOTAL_TIMEOUT_SECONDS = int(os.environ.get("DETECT_TOTAL_TIMEOUT", "900"))      # 整次检测 15 分钟
DETECT_PLATFORM_TIMEOUT_SECONDS = int(os.environ.get("DETECT_PLATFORM_TIMEOUT", "180"))  # 单平台 3 分钟

# ----- 品牌官网检测（一级信源）配置 -----
# LLM API 配置（OpenAI 兼容接口）
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_API_BASE = os.environ.get("LLM_API_BASE", "https://api.openai.com/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o")

# 搜索引擎 API Key（可选，无 Key 时使用百度/Bing HTML 抓取）
BING_API_KEY = os.environ.get("BING_API_KEY", "")

# 博查 AI 搜索 API Key（可选，作为最终降级引擎）
BOCHA_API_KEY = os.environ.get("BOCHA_API_KEY", "")

# 品牌查询开关（设为 False 可跳过一级信源检测）
BRAND_SEARCH_ENABLED = os.environ.get("BRAND_SEARCH_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")

# ----- 启用平台顺序（对外 detect / Kafka 结果固定顺序）-----
PLATFORM_ORDER = (
    "official_website",
    "douyin",
    "xiaohongshu",
    "baidu",
    "taobao",
    "jd",
)
ENABLED_PLATFORM_KEYS = tuple(
    k for k in PLATFORM_ORDER if PLATFORMS.get(k, {}).get("enabled")
)


def filter_platform_keys(platform_keys: list | None) -> list[str]:
    """过滤为已启用平台；忽略 jd/taobao 等未启用项；空列表时返回全部启用平台。"""
    allowed = set(ENABLED_PLATFORM_KEYS)
    if not platform_keys:
        return list(ENABLED_PLATFORM_KEYS)
    filtered = [k for k in platform_keys if k in allowed]
    return filtered if filtered else list(ENABLED_PLATFORM_KEYS)


def get_enabled_platforms() -> dict:
    """返回已启用平台元数据（供前端展示与 /api/platforms）。"""
    return {k: PLATFORMS[k] for k in ENABLED_PLATFORM_KEYS}


# ----- 消费任务轮询（HTTP 拉取任务，Kafka 回传结果）-----
CONSUMPTION_FETCH_URL = os.environ.get("CONSUMPTION_FETCH_URL", "").strip()
CONSUMPTION_POLL_INTERVAL = max(3, int(os.environ.get("CONSUMPTION_POLL_INTERVAL", "10")))
_CONSUMPTION_POLL_ENV = os.environ.get("CONSUMPTION_POLL_ENABLED", "true").strip().lower()
CONSUMPTION_POLL_ENABLED = _CONSUMPTION_POLL_ENV in ("1", "true", "yes", "on")

# ----- Kafka 结果回传（明文，仅出站）-----
KAFKA_BOOTSTRAP_SERVERS = os.environ.get(
    "KAFKA_BOOTSTRAP_SERVERS", "8.129.48.181:9094,120.24.45.182:9094,47.112.155.69:9094"
).strip()
KAFKA_RESULT_TOPIC = os.environ.get("KAFKA_RESULT_TOPIC", "").strip()