"""CLI 共用工具."""
from __future__ import annotations

from typing import Iterable, Sequence


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
