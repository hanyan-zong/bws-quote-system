"""bws dev — 一键启动: db init + alembic upgrade + uvicorn 前台.

取代 scripts/start.bat 的 step 2+3 (step 1 pip install 不归 CLI 管, 用户自己装环境).
"""
from __future__ import annotations

import argparse


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("dev", help="一键启动: init + migrate + uvicorn 前台")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--no-reload", action="store_true", help="关闭 --reload (生产模式)")
    p.add_argument("--no-seed", action="store_true", help="db init 时跳过样本数据")
    p.add_argument("--no-server", action="store_true",
                   help="只跑 init + migrate, 不起服务 (供测试 / CI 用)")
    p.set_defaults(_handler=_cmd_dev)


def _cmd_dev(args: argparse.Namespace) -> int:
    # 1) db init — 复用 db_cmd 的实现, 避免逻辑漂移
    print("[1/3] db init ...")
    init_args = argparse.Namespace(no_seed=args.no_seed)
    from . import db_cmd, server_cmd
    rc = db_cmd._cmd_init(init_args)
    if rc != 0:
        return rc

    # 2) alembic upgrade head
    print("[2/3] db migrate ...")
    migrate_args = argparse.Namespace(revision="head")
    rc = db_cmd._cmd_migrate(migrate_args)
    if rc != 0:
        return rc

    if args.no_server:
        print("[3/3] --no-server, 跳过 uvicorn 启动")
        return 0

    # 3) uvicorn 前台 — 阻塞, 用户 Ctrl+C 退出
    print(f"[3/3] uvicorn http://{args.host}:{args.port} ...")
    server_args = argparse.Namespace(host=args.host, port=args.port, no_reload=args.no_reload)
    return server_cmd._cmd_start(server_args)
