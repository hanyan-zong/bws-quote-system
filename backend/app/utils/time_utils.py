"""时间工具 — datetime.utcnow() 的非废弃替代.

2026-05-19: Python 3.12+ deprecate `datetime.utcnow()`, 但本项目 SQLAlchemy
DateTime column 都是 naive (timezone=False), 所有比较也都是 naive vs naive.
直接换 `datetime.now(UTC)` 会得到 aware datetime, 跟现有 naive 比较 TypeError.

所以:`now_utc()` 返回 **naive UTC** datetime — 语义跟 utcnow() 完全等价,
只是消除 DeprecationWarning. 全项目用这个替代 datetime.utcnow().
"""
from __future__ import annotations

from datetime import UTC, datetime


def now_utc() -> datetime:
    """Naive UTC datetime — utcnow() 的非废弃替代品."""
    return datetime.now(UTC).replace(tzinfo=None)
