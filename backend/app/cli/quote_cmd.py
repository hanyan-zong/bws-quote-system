"""bws quote — 报价单查询与计价."""
from __future__ import annotations

import argparse
from pathlib import Path

from ._common import print_table

# 业务友好的导出列: (DB 列名, 中文表头). 默认导出这些;
# 加 --all 则 dump Quote 表全部原始列 (与 data export 的 JSON 一致).
EXPORT_COLUMNS: list[tuple[str, str]] = [
    ("id", "id"),
    ("quote_no", "报价单号"),
    ("agency_name", "旅行社"),
    ("customer_name", "客户"),
    ("pax_adult", "成人"),
    ("pax_child", "儿童"),
    ("pax_senior", "长者"),
    ("total_days", "天数"),
    ("free_days", "自由天"),
    ("start_date", "开始"),
    ("end_date", "结束"),
    ("destination_codes", "目的地"),
    ("season", "季节"),
    ("cost_idr_total", "成本_IDR"),
    ("cost_cny_total", "成本_CNY"),
    ("profit_cny_per_pax", "人均利润_CNY"),
    ("gamble_cny_per_pax", "赌自费摊销_CNY"),
    ("price_cny_per_pax", "人均报价_CNY"),
    ("price_cny_total", "总报价_CNY"),
    ("feasibility_status", "可行性"),
]


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("quote", help="报价单查询与计价")
    sub = p.add_subparsers(dest="action", metavar="<action>", required=True)

    p_list = sub.add_parser("list", help="列出最近的报价单")
    p_list.add_argument("-n", "--limit", type=int, default=20)
    p_list.add_argument("--agency", help="按旅行社名模糊筛选")
    p_list.set_defaults(_handler=_cmd_list)

    p_export = sub.add_parser("export", help="导出报价单为 CSV / Excel(xlsx)")
    p_export.add_argument("path", type=Path, help="输出文件; 扩展名 .csv / .xlsx 自动判定格式")
    p_export.add_argument(
        "--format", choices=("csv", "xlsx"), help="强制格式; 默认按文件扩展名 (.csv/.xlsx)"
    )
    p_export.add_argument("-n", "--limit", type=int, help="最多导出条数 (默认全部)")
    p_export.add_argument("--agency", help="按旅行社名模糊筛选")
    p_export.add_argument("--season", help="按季节精确筛选 (如 low/high)")
    p_export.add_argument("--all", action="store_true", help="导出全部原始列 (不用中文表头)")
    p_export.add_argument("--json", action="store_true", help="输出结构化 JSON 汇总")
    p_export.set_defaults(_handler=_cmd_export)

    p_show = sub.add_parser("show", help="查看某报价单详情")
    p_show.add_argument("quote_id", type=int, help="报价单 id 或 quote_no")
    p_show.set_defaults(_handler=_cmd_show)

    p_calc = sub.add_parser("calc", help="重算某报价单成本")
    p_calc.add_argument("quote_id", type=int)
    p_calc.add_argument("--save", action="store_true", help="把重算结果回写到 DB")
    p_calc.set_defaults(_handler=_cmd_calc)


def _cmd_list(args: argparse.Namespace) -> int:
    from .. import models
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        q = db.query(models.Quote).order_by(models.Quote.id.desc())
        if args.agency:
            q = q.filter(models.Quote.agency_name.like(f"%{args.agency}%"))
        rows = []
        for quote in q.limit(args.limit).all():
            rows.append((
                quote.id,
                quote.quote_no,
                quote.agency_name or "-",
                f"{quote.pax_adult}+{quote.pax_child}",
                quote.total_days,
                quote.season,
                f"{quote.cost_cny_total}",
            ))
        print_table(("id", "quote_no", "agency", "pax", "days", "season", "CNY"), rows)
    finally:
        db.close()
    return 0


def _resolve_format(args: argparse.Namespace) -> str:
    """确定导出格式: 显式 --format 优先, 否则按扩展名, 都没有时报用法错误."""
    from ._common import UsageError

    if args.format:
        return args.format
    suffix = args.path.suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix in (".xlsx", ".xlsm"):
        return "xlsx"
    raise UsageError(
        f"无法从扩展名 '{suffix or '(无)'}' 判定格式, 请用 --format csv|xlsx 或改文件名"
    )


def _query_quotes(args: argparse.Namespace, db):
    """按 --agency / --season / --limit 过滤, 与 list 的筛选语义一致 (按 id 升序导出)."""
    from .. import models

    q = db.query(models.Quote).order_by(models.Quote.id)
    if getattr(args, "agency", None):
        q = q.filter(models.Quote.agency_name.like(f"%{args.agency}%"))
    if getattr(args, "season", None):
        q = q.filter(models.Quote.season == args.season)
    if getattr(args, "limit", None):
        q = q.limit(args.limit)
    return q.all()


def _export_rows(quotes, dump_all: bool) -> tuple[list[str], list[list]]:
    """把 Quote 列表拍平成 (表头, 行). dump_all=True 导全部原始列."""
    from .. import models

    if dump_all:
        cols = [c.name for c in models.Quote.__table__.columns]
        headers = list(cols)
    else:
        cols = [c for c, _ in EXPORT_COLUMNS]
        headers = [h for _, h in EXPORT_COLUMNS]
    rows = [[getattr(q, c) for c in cols] for q in quotes]
    return headers, rows


def _write_csv(path: Path, headers: list[str], rows: list[list]) -> None:
    import csv

    # utf-8-sig: 带 BOM, Excel 双击直接正确显示中文 (见 CLAUDE.md 编码避坑)
    # newline="": 避免 Windows 下 csv 模块写出多余空行
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(["" if v is None else v for v in row])


def _write_xlsx(path: Path, headers: list[str], rows: list[list]) -> None:
    from ._common import BusinessError

    try:
        from openpyxl import Workbook
    except ImportError as exc:  # 可选依赖, 不进 CLI 核心依赖
        raise BusinessError(
            "导出 xlsx 需要 openpyxl, 请先装: pip install openpyxl  "
            "(或改用 .csv 扩展名, CSV 无需任何依赖)"
        ) from exc

    wb = Workbook()
    ws = wb.active
    ws.title = "quotes"
    ws.append(headers)
    for row in rows:
        # openpyxl 不接受 date 以外的复杂对象, 这里都是标量/None, 安全
        ws.append(["" if v is None else v for v in row])
    wb.save(path)


def _cmd_export(args: argparse.Namespace) -> int:
    import json

    from ..database import SessionLocal

    fmt = _resolve_format(args)  # 先校验格式, 避免查完库才报用法错
    db = SessionLocal()
    try:
        quotes = _query_quotes(args, db)
        headers, rows = _export_rows(quotes, args.all)
    finally:
        db.close()

    if fmt == "csv":
        _write_csv(args.path, headers, rows)
    else:
        _write_xlsx(args.path, headers, rows)

    summary = {"exported": len(rows), "format": fmt, "dest": str(args.path), "columns": len(headers)}
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"导出 {len(rows)} 条报价单 → {args.path}  ({fmt}, {len(headers)} 列)")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    from .. import models
    from ..database import SessionLocal
    from ._common import BusinessError

    db = SessionLocal()
    try:
        quote = db.get(models.Quote, args.quote_id)
        if not quote:
            raise BusinessError(f"找不到 quote id={args.quote_id}")
        _print_quote(quote)
    finally:
        db.close()
    return 0


def _cmd_calc(args: argparse.Namespace) -> int:
    from .. import models
    from ..database import session_scope
    from ..utils.pricing_engine import calculate
    from ..utils.quote_recalc import recalc_quote
    from ._common import BusinessError

    with session_scope() as db:
        quote = db.get(models.Quote, args.quote_id)
        if not quote:
            raise BusinessError(f"找不到 quote id={args.quote_id}")

        # --save 走完整 recalc (cost + feasibility + gamble + profit + price + GambleHistory),
        # 与 web 端 routers/quotes.py::calculate_quote 完全一致;
        # 不带 --save 只做 dry-run 计价拆解, 不改任何字段.
        if args.save:
            result = recalc_quote(quote, db)
            breakdown = result.breakdown
        else:
            breakdown = calculate(quote, db)

        print(f"报价单 {quote.quote_no}  ({quote.total_days} 天 · {quote.season})")
        print(f"  成本合计  : {breakdown.cost_idr_total} IDR  /  {breakdown.cost_cny_total} CNY")
        print(f"  人均成本  : {breakdown.per_pax_idr} IDR  /  {breakdown.per_pax_cny} CNY")
        print("  逐日明细:")
        for day in breakdown.per_day:
            free = " (自由活动)" if day["is_free"] else ""
            print(f"    Day {day['day_index']}{free}: {day['cost_idr']} IDR / {day['cost_cny']} CNY")
            for d in day["details"]:
                print(f"      · {d}")

        if args.save:
            print("  [已保存完整 recalc]")
            print(f"    cost_cny_total       : {quote.cost_cny_total}")
            print(f"    profit_cny_per_pax   : {quote.profit_cny_per_pax}")
            print(f"    gamble_cny_per_pax   : {quote.gamble_cny_per_pax}")
            print(f"    price_cny_per_pax    : {quote.price_cny_per_pax}")
            print(f"    price_cny_total      : {quote.price_cny_total}")
            print(f"    feasibility_status   : {quote.feasibility_status}")
    return 0


def _print_quote(quote) -> None:
    print(f"# 报价单 {quote.quote_no}  (id={quote.id})")
    print(f"  旅行社  : {quote.agency_name or '-'}  / 联系人: {quote.agency_contact or '-'}")
    print(f"  客户    : {quote.customer_name or '-'}")
    print(f"  人数    : 成人 {quote.pax_adult} · 儿童 {quote.pax_child} · 长者 {quote.pax_senior}")
    print(f"  日期    : {quote.start_date} → {quote.end_date}  (共 {quote.total_days} 天, 自由 {quote.free_days})")
    print(f"  目的地  : {quote.destination_codes}  季节: {quote.season}")
    print(f"  成本    : {quote.cost_idr_total} IDR  /  {quote.cost_cny_total} CNY")
    print(f"  人均利润: {quote.profit_cny_per_pax} CNY  · 赌自费摊销: {quote.gamble_cny_per_pax} CNY")
    if quote.days:
        print(f"  共 {len(quote.days)} 天明细 (用 bws quote calc {quote.id} 看成本拆解)")
