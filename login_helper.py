# -*- coding: utf-8 -*-
"""手动登录辅助脚本 — 用有头模式打开浏览器，让用户能看见并完成登录

用法：
    python login_helper.py douyin
    python login_helper.py baidu
"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from platforms import get_platform


async def main(platform_key: str):
    if platform_key not in ("douyin", "baidu"):
        print(f"用法: python login_helper.py <douyin|baidu>")
        sys.exit(1)

    print(f"=== 启动有头浏览器，登录 {platform_key} ===", flush=True)
    print(f"=== 你将看到 Chromium 窗口弹出，请在里面完成登录 ===", flush=True)
    print(f"=== 登录完成后点击页面右上角「💾 保存登录」按钮 ===", flush=True)
    print(f"=== 等待 10 分钟内完成，否则超时 ===\n", flush=True)

    platform = get_platform(platform_key)
    success = await platform.login()
    if success:
        print(f"\n✅ {platform_key} 登录成功！Cookie 已保存到 profile 目录。", flush=True)
    else:
        print(f"\n❌ {platform_key} 登录超时或失败。", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python login_helper.py <douyin|baidu>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
