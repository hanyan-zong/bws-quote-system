"""BWS 命令行入口.

子命令一览:
    bws quote   list|show|calc       报价单查询与计价
    bws data    import|export|backup|restore  数据迁移
    bws server  start|status|stop    后端服务运维
    bws db      init|migrate|query|stats  数据库管理
"""
from __future__ import annotations

import argparse
import os
import sys

from . import data_cmd, db_cmd, dev_cmd, quote_cmd, server_cmd
from ._common import CliError


def _ensure_utf8_stdio() -> None:
    if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("utf"):
        return
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bws",
        description="BWS 预报价系统命令行 (v0.8.4)",
    )
    parser.add_argument("--version", action="version", version="bws 0.1.0")
    subparsers = parser.add_subparsers(dest="group", metavar="<group>", required=True)

    quote_cmd.register(subparsers)
    data_cmd.register(subparsers)
    server_cmd.register(subparsers)
    db_cmd.register(subparsers)
    dev_cmd.register(subparsers)

    return parser


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdio()
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    parser = build_parser()
    args = parser.parse_args(argv)

    handler = getattr(args, "_handler", None)
    if handler is None:
        parser.print_help()
        return 2
    try:
        rc = handler(args)
    except KeyboardInterrupt:
        print("\n[中断]", file=sys.stderr)
        return 130
    except CliError as exc:
        print(f"[{type(exc).__name__}] {exc}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        print(f"[错误] {type(exc).__name__}: {exc}", file=sys.stderr)
        if os.environ.get("BWS_CLI_DEBUG"):
            raise
        return 1
    return int(rc or 0)
