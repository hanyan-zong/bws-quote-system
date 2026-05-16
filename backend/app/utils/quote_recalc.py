"""报价单完整重算 — router 与 CLI 共用入口.

抽取自 routers/quotes.py:calculate_quote 的 1~5 步, 保证 router 与 CLI
对同一个报价单的重算结果完全一致 (v0.9.0 修复 CLI 漂移).

调用方负责 commit (router 走 db.commit, CLI 走 session_scope).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from . import feasibility_engine, gambling_engine, pricing_engine


_DEFAULT_PROFIT_BY_CUSTOMER_TYPE: dict[str, Decimal] = {
    "honeymoon": Decimal("400"),
    "family_kids": Decimal("300"),
    "young": Decimal("250"),
    "family": Decimal("250"),
    "senior": Decimal("200"),
    "mice": Decimal("500"),
    "wedding": Decimal("600"),
}
_DEFAULT_PROFIT_FALLBACK = Decimal("250")


@dataclass
class RecalcResult:
    breakdown: Any
    fea_report: Any
    gamble: Any


def recalc_quote(quote: models.Quote, db: Session) -> RecalcResult:
    """完整重算 quote 各字段 (不 commit). router 与 CLI 共用."""
    breakdown = pricing_engine.calculate(quote, db)
    quote.cost_idr_total = breakdown.cost_idr_total
    quote.cost_cny_total = breakdown.cost_cny_total

    pax_total = max(quote.pax_adult + quote.pax_child, 1)
    cost_per_pax = breakdown.per_pax_cny

    fea_report = feasibility_engine.check_quote(quote, db, run_ai_review=False)
    quote.feasibility_status = (
        "fail" if not fea_report.overall_feasible
        else ("warning" if any(d.warnings for d in fea_report.days) else "pass")
    )
    quote.feasibility_report = json.dumps(fea_report.to_dict(), ensure_ascii=False)

    gamble = gambling_engine.recommend(quote, db)
    quote.gamble_cny_per_pax = gamble.recommended_cny

    default_profit_per_pax = _DEFAULT_PROFIT_BY_CUSTOMER_TYPE.get(
        quote.customer_type, _DEFAULT_PROFIT_FALLBACK,
    )
    extra_profit = getattr(gamble, "extra_profit_cny_per_pax", Decimal(0)) or Decimal(0)
    quote.profit_cny_per_pax = (default_profit_per_pax + extra_profit).quantize(Decimal("0.01"))

    price_per_pax = cost_per_pax + default_profit_per_pax + extra_profit - gamble.recommended_cny
    quote.price_cny_per_pax = price_per_pax.quantize(Decimal("0.01"))
    quote.price_cny_total = (quote.price_cny_per_pax * pax_total).quantize(Decimal("0.01"))

    strategy_id = None
    if gamble.skip_rule and isinstance(gamble.skip_rule, dict):
        strategy_id = gamble.skip_rule.get("id")
    db.add(
        models.GambleHistory(
            quote_id=quote.id,
            recommended_cny=gamble.recommended_cny,
            applied_cny=gamble.recommended_cny,
            ai_confidence=gamble.ai_confidence,
            reasoning=gamble.reasoning,
            won_or_lost="pending",
            strategy_id=strategy_id,
        )
    )

    return RecalcResult(breakdown=breakdown, fea_report=fea_report, gamble=gamble)
