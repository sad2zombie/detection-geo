import os
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
    packed_chrome = '.cloakbrowser/chromium-146.0.7680.177.5/chrome.exe'
    if packed_chrome:
        full_chrome_path = os.path.join(bundle_dir, packed_chrome)
        if os.path.exists(full_chrome_path):
            os.environ["CLOAKBROWSER_BINARY_PATH"] = full_chrome_path
            # Disable auto-update checks inside the bundle so it doesn't try to phone home.
            os.environ.setdefault("CLOAKBROWSER_AUTO_UPDATE", "false")
        else:
            sys.stderr.write(
                f"[runtime_hook] WARNING: bundled chrome.exe not found at {full_chrome_path}\n"
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
