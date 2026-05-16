"""bws quote — 报价单查询与计价."""
from __future__ import annotations

import argparse

from ._common import print_table


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("quote", help="报价单查询与计价")
    sub = p.add_subparsers(dest="action", metavar="<action>", required=True)

    p_list = sub.add_parser("list", help="列出最近的报价单")
    p_list.add_argument("-n", "--limit", type=int, default=20)
    p_list.add_argument("--agency", help="按旅行社名模糊筛选")
    p_list.set_defaults(_handler=_cmd_list)

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
