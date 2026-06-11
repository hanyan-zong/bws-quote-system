"""节日自动识别 → SeasonCalendar 候选区间 (vacanza/holidays 库, 2026-06-11).

业务背景: v0.9.4 季节多档定价的 holiday 档目前要管理员手填日期区间.
本模块用 holidays 库 (github.com/vacanza/holidays, 纯 Python 零重依赖) 自动生成:
  - CN 中国公共节日 (客源端: 春节/国庆等出行高峰 → 巴厘岛酒店涨价)
  - ID 印尼公共节日 + government 调休 (目的地端: Nyepi/开斋节 → 本地涨价)

输出与 SeasonCalendarIn schema 对齐, 管理员一键生成后可在 UI 微调.
"""
from __future__ import annotations

from datetime import date as _date, timedelta

# 国家配置: 语言 / 节日类别 / 中文前缀
COUNTRY_CONF: dict[str, dict] = {
    "CN": {"language": "zh_CN", "categories": ("public",), "label": "中国"},
    # government = cuti bersama 联合调休, 对酒店价格影响等同公共节日
    "ID": {"language": None, "categories": ("public", "government"), "label": "印尼"},
}

_MAX_NAME_LEN = 80


def suggest_holiday_ranges(
    year: int,
    countries: tuple[str, ...] | list[str] = ("CN", "ID"),
    pad_days: int = 0,
) -> list[dict]:
    """生成某年的节日区间建议 (连续/相邻日期合并为一条).

    pad_days: 区间前后各扩 N 天 (节前出行/节后返程通常也是高价日).
    返回 dict 列表, 字段与 SeasonCalendarIn 对齐 (date 为 date 对象).
    """
    import holidays as _hol  # 延迟 import, 未安装时只有调用方报错

    out: list[dict] = []
    for c in countries:
        conf = COUNTRY_CONF.get(c, {"language": None, "categories": ("public",), "label": c})
        try:
            cal = _hol.country_holidays(
                c, years=year, language=conf["language"], categories=conf["categories"]
            )
        except Exception:
            # 个别国家不支持指定 categories/language → 兜底默认 public
            cal = _hol.country_holidays(c, years=year)

        items = sorted(cal.items())
        if not items:
            continue

        # 每个节日日期先 ±pad, 再合并重叠/相邻区间
        ranges: list[list] = []  # [start, end, [names...]]
        for d, name in items:
            start = d - timedelta(days=pad_days)
            end = d + timedelta(days=pad_days)
            if ranges and (start - ranges[-1][1]).days <= 1:
                ranges[-1][1] = max(ranges[-1][1], end)
                if name not in ranges[-1][2]:
                    ranges[-1][2].append(name)
            else:
                ranges.append([start, end, [name]])

        for start, end, names in ranges:
            label = f"{conf['label']}·" + "+".join(names)
            if len(label) > _MAX_NAME_LEN:
                label = label[: _MAX_NAME_LEN - 1] + "…"
            out.append(
                {
                    "name": label,
                    "season_band": "holiday",
                    "date_from": start,
                    "date_to": end,
                    "priority": 100,  # holiday 档优先级最高, 压过手填的 high/peak 区间
                    "destination_code": None,
                    "note": f"自动生成: holidays 库 {c} {year} (pad={pad_days})",
                }
            )

    out.sort(key=lambda r: r["date_from"])
    return out
