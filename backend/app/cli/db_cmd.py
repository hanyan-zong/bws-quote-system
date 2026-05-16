"""bws db — 数据库初始化/查询/统计."""
from __future__ import annotations

import argparse


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("db", help="数据库管理")
    sub = p.add_subparsers(dest="action", metavar="<action>", required=True)

    p_init = sub.add_parser("init", help="建表 + 写样本数据 (等价 scripts/init_db.py)")
    p_init.add_argument("--no-seed", action="store_true", help="只建表, 不写样本数据")
    p_init.set_defaults(_handler=_cmd_init)

    p_mig = sub.add_parser("migrate", help="跑 alembic upgrade head — 真升级 schema")
    p_mig.add_argument("--revision", default="head", help="目标版本 (默认 head)")
    p_mig.set_defaults(_handler=_cmd_migrate)

    p_query = sub.add_parser("query", help="执行只读 SQL")
    p_query.add_argument("sql", help="SELECT 语句 (危险写操作会被拒绝)")
    p_query.add_argument("-n", "--limit", type=int, default=50)
    p_query.set_defaults(_handler=_cmd_query)

    p_stats = sub.add_parser("stats", help="列出各表行数")
    p_stats.set_defaults(_handler=_cmd_stats)


def _cmd_init(args: argparse.Namespace) -> int:
    from ..database import init_db

    if args.no_seed:
        init_db()
        print("已建表 (跳过样本数据)")
    else:
        from ..seed import seed_all
        seed_all()
        print("已建表 + 写样本数据")
    return 0


def _cmd_migrate(args: argparse.Namespace) -> int:
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    from ..config import BACKEND_DIR
    from ._common import BusinessError

    ini = BACKEND_DIR / "alembic.ini"
    if not ini.exists():
        raise BusinessError(f"找不到 alembic.ini: {ini}")
    cfg = Config(str(ini))
    # 让 env.py 里 `Path(__file__).resolve().parent.parent` 指对位置
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    try:
        command.upgrade(cfg, args.revision)
    except Exception as exc:
        raise BusinessError(f"alembic upgrade 失败: {exc}") from exc
    print(f"已升级到 {args.revision}")
    return 0


def _cmd_query(args: argparse.Namespace) -> int:
    from sqlalchemy import text

    from ..database import SessionLocal
    from ._common import print_table

    sql_stripped = args.sql.strip().lower()
    write_verbs = ("insert", "update", "delete", "drop", "alter", "create", "truncate", "replace")
    if any(sql_stripped.startswith(v) for v in write_verbs):
        from ._common import UsageError
        verb = sql_stripped.split()[0]
        raise UsageError(
            f"拒绝执行写操作: {verb}. 如需写操作, 直接连 sqlite3 backend/data/bws_quote.db"
        )

    db = SessionLocal()
    try:
        result = db.execute(text(args.sql))
        headers = tuple(result.keys()) if result.returns_rows else ()
        if not headers:
            print(f"完成 (受影响行数: {result.rowcount})")
            return 0
        rows = result.fetchmany(args.limit)
        print_table(headers, rows)
        if len(rows) == args.limit:
            print(f"... (截断到 {args.limit} 行, 用 -n 调整)")
    finally:
        db.close()
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    from sqlalchemy import inspect, text

    from ..database import SessionLocal, engine
    from ._common import print_table

    insp = inspect(engine)
    table_names = sorted(insp.get_table_names())
    db = SessionLocal()
    try:
        rows = []
        for name in table_names:
            try:
                count = db.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar()
            except Exception as e:
                count = f"ERR: {e}"
            rows.append((name, count))
        print_table(("table", "rows"), rows)
    finally:
        db.close()
    return 0
