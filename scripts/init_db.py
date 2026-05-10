#!/usr/bin/env python3
"""一键初始化数据库 + 写样本数据."""
import sys
from pathlib import Path

# 把 backend 加入 sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.seed import seed_all

if __name__ == "__main__":
    seed_all()
