import os
import sys

# Set Playwright browsers path for packaged executable
if getattr(sys, "frozen", False):
    bundle_dir = sys._MEIPASS
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(bundle_dir, "ms-playwright")
