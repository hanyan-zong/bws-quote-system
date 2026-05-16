"""CLI 共用工具.

退码语义 (全 CLI 统一):
    0   成功
    1   业务错误 (找不到对象 / 文件不存在 / 远端不可达 / 操作被拒)
    2   用法错误 (参数缺失 / 类型错 / 不允许的输入, argparse 也用 2)
    130 用户 Ctrl+C 中断
"""
from __future__ import annotations

from typing import Iterable, Sequence


class CliError(Exception):
    """所有 CLI 退码异常的基类. handler 抛它会被 main() 翻成对应退码."""

    exit_code: int = 1


class BusinessError(CliError):
    """业务侧错误 — 退码 1. 用于: 找不到记录, 文件不存在, 远端 503 等."""

    exit_code = 1


class UsageError(CliError):
    """用法错误 — 退码 2. 用于: 用户传了不允许的参数 (比如写 SQL 给 db query)."""

    exit_code = 2


def print_table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> None:
    rows_list = [tuple(str(c) if c is not None else "" for c in row) for row in rows]
    if not rows_list:
        print(" · ".join(headers))
        print("(空)")
        return
    widths = [len(h) for h in headers]
    for row in rows_list:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], _display_width(cell))

    sep = "  "
    print(sep.join(_pad(h, widths[i]) for i, h in enumerate(headers)))
    print(sep.join("-" * widths[i] for i in range(len(headers))))
    for row in rows_list:
        print(sep.join(_pad(c, widths[i]) for i, c in enumerate(row)))


def _display_width(s: str) -> int:
    w = 0
    for ch in s:
        w += 2 if ord(ch) > 0x2E80 else 1
    return w


def _pad(s: str, target: int) -> str:
    pad = target - _display_width(s)
    return s + " " * max(0, pad)


def confirm(prompt: str, *, default: bool = False) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        ans = input(f"{prompt} {suffix} ").strip().lower()
    except EOFError:
        return default
    if not ans:
        return default
    return ans in {"y", "yes"}
