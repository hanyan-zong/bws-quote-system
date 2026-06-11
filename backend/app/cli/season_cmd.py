"""bws season — 季节日历管理 (节日档自动生成).

业务背景: v0.9.4 季节多档定价的 holiday 档原来要管理员逐条手填日期区间.
`bws season suggest` 用 holidays 库自动生成 CN/ID 节日区间, 默认只预览,
`--save` 才写库 (按 名称+起止日期 幂等去重, 重复跑不会插重复行).
"""
from __future__ import annotations

import argparse
import json


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("season", help="季节日历管理 (节日档自动生成)")
    sub = p.add_subparsers(dest="action", metavar="<action>", required=True)

    p_sug = sub.add_parser("suggest", help="自动生成某年的节日档区间 (默认只预览, --save 才写库)")
    p_sug.add_argument("year", type=int, help="目标年份, 如 2026")
    p_sug.add_argument("--country", default="CN,ID", help="国家代码, 逗号分隔 (默认 CN,ID)")
    p_sug.add_argument("--pad", type=int, default=0, help="区间前后各扩 N 天 (节前出行/节后返程也是高价日)")
    p_sug.add_argument("--save", action="store_true", help="写入 season_calendars (幂等, 已存在的跳过)")
    p_sug.add_argument("--json", action="store_true", dest="as_json", help="输出 JSON")
    p_sug.set_defaults(_handler=_cmd_suggest)


def _cmd_suggest(args: argparse.Namespace) -> int:
    from ._common import BusinessError, UsageError, print_table

    if not 2000 <= args.year <= 2100:
        raise UsageError(f"年份超出范围 (2000-2100): {args.year}")
    if args.pad < 0:
        raise UsageError(f"--pad 不能为负: {args.pad}")
    countries = [c.strip().upper() for c in args.country.split(",") if c.strip()]
    if not countries:
        raise UsageError("--country 不能为空")
    for c in countries:
        if not (2 <= len(c) <= 3 and c.isalpha()):
            raise UsageError(f"国家代码格式错 (ISO 两三位字母): {c}")

    try:
        from ..utils.holiday_autogen import suggest_holiday_ranges
        ranges = suggest_holiday_ranges(args.year, countries=countries, pad_days=args.pad)
    except ImportError:
        raise BusinessError(
            "缺少 holidays 库. 安装: .venv\\Scripts\\python.exe -m pip install holidays"
        ) from None
    except NotImplementedError as exc:
        raise UsageError(f"holidays 库不支持该国家代码: {exc}") from exc

    if not ranges:
        print(f"{args.year} 年 {','.join(countries)} 无节日数据")
        return 0

    if args.save:
        inserted, skipped = _save_ranges(ranges)
        summary = {"year": args.year, "total": len(ranges), "inserted": inserted, "skipped": skipped}
        if args.as_json:
            print(json.dumps({**summary, "ranges": _jsonable(ranges)}, ensure_ascii=False, indent=2))
        else:
            _print_ranges(ranges, print_table)
            print(f"\n已写入 season_calendars: 新增 {inserted} 条, 跳过已存在 {skipped} 条")
        return 0

    if args.as_json:
        print(json.dumps(_jsonable(ranges), ensure_ascii=False, indent=2))
    else:
        _print_ranges(ranges, print_table)
        print(f"\n共 {len(ranges)} 条 (预览, 未写库; 加 --save 写入)")
    return 0


def _save_ranges(ranges: list[dict]) -> tuple[int, int]:
    from sqlalchemy.exc import OperationalError

    from ..database import session_scope
    from ..models import SeasonCalendar
    from ._common import BusinessError

    inserted = skipped = 0
    try:
        with session_scope() as db:
            existing = {
                (r.name, r.date_from, r.date_to)
                for r in db.query(SeasonCalendar.name, SeasonCalendar.date_from, SeasonCalendar.date_to)
            }
            for r in ranges:
                if (r["name"], r["date_from"], r["date_to"]) in existing:
                    skipped += 1
                    continue
                db.add(SeasonCalendar(**r))
                inserted += 1
    except OperationalError as exc:
        raise BusinessError(f"写库失败 (表不存在? 先跑 bws db init): {exc}") from exc
    return inserted, skipped


def _print_ranges(ranges: list[dict], print_table) -> None:
    rows = [
        (r["name"], str(r["date_from"]), str(r["date_to"]), (r["date_to"] - r["date_from"]).days + 1)
        for r in ranges
    ]
    print_table(("名称", "起", "止", "天数"), rows)


def _jsonable(ranges: list[dict]) -> list[dict]:
    return [
        {**r, "date_from": r["date_from"].isoformat(), "date_to": r["date_to"].isoformat()}
        for r in ranges
    ]
