# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置 — 生成后端 exe

核心策略：
- 业务侧使用 CloakBrowser（stealth Chromium），不走 Playwright
- CloakBrowser 是独立第三方库：pip install 后运行时从 cloakbrowser.dev 下载二进制
- 本 spec 解决两个问题：
  1. CloakBrowser pip 包的源码作为数据文件打包（避免 collect_submodules 漏掉子模块）
  2. 本地已下载的 Chromium 二进制目录整体打包到 exe，运行时通过 CLOAKBROWSER_BINARY_PATH
     环境变量跳过在线下载，让服务器即使无网也能正常启动

打包完成后会：
- exe 大小约 550MB（150MB CloakBrowser 源码 + 400MB Chromium 二进制）
- 服务器无需访问 cloakbrowser.dev 即可启动浏览器
- 业务代码零改动
"""

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# 项目根目录
PROJECT_ROOT = Path(SPECPATH).resolve()

# 前端资源目录
WEB_DIR = PROJECT_ROOT / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

# ---------------------------------------------------------------------------
# 收集要打包的文件
# ---------------------------------------------------------------------------
datas = [
    (str(PROJECT_ROOT / "config.py"), "."),
]
if TEMPLATES_DIR.exists():
    datas.append((str(TEMPLATES_DIR), "web/templates"))
if STATIC_DIR.exists():
    datas.append((str(STATIC_DIR), "web/static"))

# 项目模块目录
for dir_name in ["core", "platforms", "utils", "ai"]:
    dir_path = PROJECT_ROOT / dir_name
    if dir_path.exists():
        datas.append((str(dir_path), dir_name))

# ---------------------------------------------------------------------------
# CloakBrowser：源码作为数据文件打包
# ---------------------------------------------------------------------------
# CloakBrowser 的源码不在 site-packages 的标准 .pth 路径中能被 PyInstaller 自动分析到，
# 这里直接把整个 pip 包目录打进 exe 的 cloakbrowser/ 子包路径。
# 这样运行时 from cloakbrowser import ... 时，PyInstaller 解压 _MEIPASS 后能找到。
import cloakbrowser as _cb  # 用来定位 pip 包路径
_cb_pkg_dir = Path(_cb.__file__).parent
datas.append((str(_cb_pkg_dir), "cloakbrowser"))
print(f"Including CloakBrowser source: {_cb_pkg_dir}")

# ---------------------------------------------------------------------------
# CloakBrowser 二进制：从本地 ~/.cloakbrowser 缓存目录打包已下载好的 chromium
# ---------------------------------------------------------------------------
# 运行时通过 CLOAKBROWSER_BINARY_PATH 直接指向打包进去的 chrome.exe，
# 完全跳过在线下载。服务器无需访问 cloakbrowser.dev。
#
# 注意：这里打包的是 CLOAKBROWSER_CACHE_DIR 下当前可用版本的完整 chromium 目录。
# 如果目录不存在，会跳过并打印警告 —— 运行时 fallback 到在线下载（需联网）。
cloakbrowser_cache = Path(os.path.expandvars(r"%USERPROFILE%")) / ".cloakbrowser"
chromium_in_cache = None
if cloakbrowser_cache.exists():
    # 优先取 .last_update_check / latest_version marker 指向的版本，否则取最大的目录
    candidates = [p for p in cloakbrowser_cache.iterdir()
                  if p.is_dir() and p.name.startswith("chromium-")]
    # 找真正含 chrome.exe 的
    candidates = [p for p in candidates if (p / "chrome.exe").exists()]
    if candidates:
        # 按目录名（版本号）排序，取最大的
        chromium_in_cache = sorted(candidates, key=lambda p: p.name, reverse=True)[0]
        datas.append((str(chromium_in_cache), ".cloakbrowser/" + chromium_in_cache.name))
        print(f"Including CloakBrowser Chromium binary: {chromium_in_cache}")
    else:
        print(f"WARNING: No chrome.exe found under {cloakbrowser_cache}")
        print("Run: python -c \"from cloakbrowser.download import ensure_binary; ensure_binary()\"")
else:
    print(f"WARNING: {cloakbrowser_cache} not found.")
    print("Run: python -c \"from cloakbrowser.download import ensure_binary; ensure_binary()\"")

# ---------------------------------------------------------------------------
# 收集隐藏导入
# ---------------------------------------------------------------------------
hiddenimports = [
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "starlette",
    "fastapi",
    "pydantic",
    "pydantic.main",
    "pydantic.fields",
    "jinja2",
    "jinja2.ext",
    "markupsafe",
    "itsdangerous",
    "python_multipart",
    "cloakbrowser",
    "config",
    "core.browser_manager",
    "core.auth_manager",
    "core.search_engine",
    "core.task_manager",
    "core.terminal_info",
    "core.consumption_log",
    "core.runtime_log",
    "core.consumption_worker",
    "platforms",
    "platforms.douyin",
    "platforms.baidu",
    "platforms.xiaohongshu",
    "platforms.taobao",
    "platforms.jd",
    "platforms.official_website",
    "core.web_search",
    "core.llm_client",
    "core.brand_search",
    "pypinyin",
    "dotenv",
    "httpx",
    "httpcore",
    "anyio",
    "websockets",
]

hiddenimports.extend(collect_submodules("cloakbrowser"))
hiddenimports.extend(collect_submodules("fastapi"))
hiddenimports.extend(collect_submodules("uvicorn"))
hiddenimports.extend(collect_submodules("pydantic"))

# ---------------------------------------------------------------------------
# 创建 runtime hook
# ---------------------------------------------------------------------------
# 关键职责：
# 1. 把 _MEIPASS 加到 sys.path 最前面，让 from cloakbrowser import ... 能找到数据文件
# 2. 设 CLOAKBROWSER_BINARY_PATH 直接指向打包的 chrome.exe（跳过在线下载）
# 3. 设 CLOAKBROWSER_CACHE_DIR 指向 %LOCALAPPDATA% 让 update check 等可写操作有地方落
# ---------------------------------------------------------------------------
# 注意：runtime hook 里的 chrome.exe 路径需要由 spec 动态注入。
# 我们在这里写一个模板字符串，spec 里用 f-string / str.replace 替换。
#
# 路径：_MEIPASS/.cloakbrowser/<chromium_dir_name>/chrome.exe
if chromium_in_cache:
    packed_chrome_relpath = f".cloakbrowser/{chromium_in_cache.name}/chrome.exe"
else:
    packed_chrome_relpath = ""  # 没有打包二进制时不设 binary path

runtime_hook_content = f'''import os
import sys

# CloakBrowser source was packaged as data files under _MEIPASS/cloakbrowser/.
# We need that on sys.path so `from cloakbrowser import ...` resolves correctly
# inside the frozen bundle.
if getattr(sys, "frozen", False):
    bundle_dir = sys._MEIPASS

    # 1. Put _MEIPASS/cloakbrowser on sys.path so the packaged source is importable.
    cb_src = os.path.join(bundle_dir, "cloakbrowser")
    if os.path.isdir(cb_src) and cb_src not in sys.path:
        sys.path.insert(0, cb_src)

    # 2. Point CloakBrowser directly at the bundled Chromium binary (skip online download).
    #    This makes the server fully self-contained — no network required at runtime.
    packed_chrome = {packed_chrome_relpath!r}
    if packed_chrome:
        full_chrome_path = os.path.join(bundle_dir, packed_chrome)
        if os.path.exists(full_chrome_path):
            os.environ["CLOAKBROWSER_BINARY_PATH"] = full_chrome_path
            # Disable auto-update checks inside the bundle so it doesn't try to phone home.
            os.environ.setdefault("CLOAKBROWSER_AUTO_UPDATE", "false")
        else:
            sys.stderr.write(
                f"[runtime_hook] WARNING: bundled chrome.exe not found at {{full_chrome_path}}\\n"
            )

    # 3. Set cache dir to %LOCALAPPDATA% so any write ops (welcome marker, update check
    #    timestamps) have a writable location. Only used as fallback if BINARY_PATH doesn't hit.
    local_app_data = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    cache_dir = os.path.join(local_app_data, "cloakbrowser-cache")
    try:
        os.makedirs(cache_dir, exist_ok=True)
        os.environ["CLOAKBROWSER_CACHE_DIR"] = cache_dir
    except Exception:
        pass
'''

runtime_hook_path = os.path.join(PROJECT_ROOT, "runtime_hook.py")
with open(runtime_hook_path, "w", encoding="utf-8") as f:
    f.write(runtime_hook_content)
print(f"Created runtime hook: {runtime_hook_path}")

# ---------------------------------------------------------------------------
# PyInstaller Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[runtime_hook_path],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="detection-backend-exe",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 无控制台窗口，后台运行
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)