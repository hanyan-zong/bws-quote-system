"""bws season suggest — 节日档自动生成.

黑盒 subprocess (bws fixture) + holiday_autogen in-process 单测.
holidays 库纯离线 (规则内置), 测试不依赖网络.
"""
from __future__ import annotations

import json

YEAR = "2026"


# ---------- 黑盒: 预览 ----------

def test_season_suggest_preview_outputs_ranges_without_db(bws):
    res = bws("season", "suggest", YEAR)

    assert res.ok(), res.stderr
    assert "未写库" in res.stdout
    assert "中国" in res.stdout and "印尼" in res.stdout


def test_season_suggest_json_ranges_align_with_schema(bws):
    res = bws("season", "suggest", YEAR, "--pad", "1", "--json")

    assert res.ok(), res.stderr
    ranges = json.loads(res.stdout)
    assert len(ranges) > 0
    from app.schemas import SeasonCalendarIn  # 字段对齐的硬校验: 不对齐直接 ValidationError

    for r in ranges:
        parsed = SeasonCalendarIn(**r)
        assert parsed.season_band == "holiday"
        assert parsed.priority == 100
        assert parsed.date_from <= parsed.date_to


# ---------- 黑盒: --save 幂等 ----------

def test_season_suggest_save_is_idempotent(bws):
    bws("db", "init", "--no-seed")

    first = bws("season", "suggest", YEAR, "--save")
    second = bws("season", "suggest", YEAR, "--save")

    assert first.ok(), first.stderr
    assert second.ok(), second.stderr
    assert "新增 0 条" in second.stdout  # 重复跑不插重复行
    count = bws("db", "query", "SELECT COUNT(*) AS n FROM season_calendars")
    assert count.ok()
    n = int(count.stdout.splitlines()[-1].strip())
    assert n > 0
    assert f"新增 {n} 条" in first.stdout  # 首跑全部入库, 库里行数 == 首跑新增数


def test_season_suggest_save_without_tables_fails_with_hint(bws):
    res = bws("season", "suggest", YEAR, "--save")  # 没跑 db init

    assert res.returncode == 1
    assert "db init" in res.stderr


# ---------- 黑盒: 用法错误 (退码 2) ----------

def test_season_suggest_rejects_year_out_of_range(bws):
    res = bws("season", "suggest", "1800")

    assert res.returncode == 2


def test_season_suggest_rejects_malformed_country_code(bws):
    res = bws("season", "suggest", YEAR, "--country", "C3PO")

    assert res.returncode == 2


def test_season_suggest_rejects_unsupported_country(bws):
    res = bws("season", "suggest", YEAR, "--country", "XX")

    assert res.returncode == 2


# ---------- in-process: holiday_autogen 纯函数 ----------

def test_suggest_holiday_ranges_sorted_and_banded():
    from app.utils.holiday_autogen import suggest_holiday_ranges

    ranges = suggest_holiday_ranges(2026)

    assert ranges == sorted(ranges, key=lambda r: r["date_from"])
    assert all(r["season_band"] == "holiday" for r in ranges)
    assert all(r["date_from"] <= r["date_to"] for r in ranges)


def test_suggest_holiday_ranges_pad_widens_and_merges():
    from app.utils.holiday_autogen import suggest_holiday_ranges

    plain = suggest_holiday_ranges(2026, countries=("CN",), pad_days=0)
    padded = suggest_holiday_ranges(2026, countries=("CN",), pad_days=3)

    assert len(padded) <= len(plain)  # 相邻节日被合并
    days = lambda rs: sum((r["date_to"] - r["date_from"]).days + 1 for r in rs)
    assert days(padded) > days(plain)  # 覆盖天数变多


def test_suggest_holiday_ranges_empty_countries_returns_empty():
    from app.utils.holiday_autogen import suggest_holiday_ranges

    assert suggest_holiday_ranges(2026, countries=()) == []
