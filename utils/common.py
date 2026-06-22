# -*- coding: utf-8 -*-
"""公共工具函数"""

import json
import sys
from datetime import datetime
from pathlib import Path


def ensure_cloakbrowser():
    """确保 cloakbrowser 可导入"""
    from config import CLOAKBROWSER_DIR
    if str(CLOAKBROWSER_DIR) not in sys.path:
        sys.path.insert(0, str(CLOAKBROWSER_DIR))


def save_json(data, path: Path):
    """保存 JSON 文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(path: Path) -> dict:
    """加载 JSON 文件"""
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def now_str() -> str:
    """当前时间字符串"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_filename(text: str) -> str:
    """将文本转为安全文件名"""
    return "".join(c for c in text if c.isalnum() or c in "._- ").strip()[:50]