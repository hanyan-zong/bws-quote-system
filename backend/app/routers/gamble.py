"""赌自费 API."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from .. import models
from ..database import get_db
from ..schemas import GambleApplyIn, GambleFeedbackIn, GambleRecommendIn
from ..utils import gambling_engine
from ..utils.erp_hook import enqueue_erp_event

router = APIRouter(prefix="/gamble", tags=["gamble"])


@router.post("/recommend")
def recommend(payload: GambleRecommendIn, db: Session = Depends(get_db)):
    quote = (
        db.query(models.Quote)
        .options(joinedload(models.Quote.days))
        .filter_by(id=payload.quote_id)
        .first()
    )
    if not quote:
        raise HTTPException(404)
    res = gambling_engine.recommend(quote, db)
    return {
        "quote_id": quote.id,
        "recommended_cny": float(res.recommended_cny),
        "low_bound_cny": float(res.low_bound_cny),
        "high_bound_cny": float(res.high_bound_cny),
        "ai_confidence": res.ai_confidence,
        "reasoning": res.reasoning,
        "configured_optional_tours": res.configured_optional_tours,
        "excluded_optional_tours": res.excluded_optional_tours,
        "skip_rule": res.skip_rule,
        "enabled": res.enabled,
    }


@router.post("/apply")
def apply_gamble(payload: GambleApplyIn, db: Session = Depends(get_db)):
    quote = db.get(models.Quote, payload.quote_id)
    if not quote:
        raise HTTPException(404)
    quote.gamble_cny_per_pax = payload.applied_cny
    db.add(
        models.GambleHistory(
            quote_id=quote.id,
            recommended_cny=quote.gamble_cny_per_pax,
            applied_cny=payload.applied_cny,
            won_or_lost="pending",
        )
    )
    db.commit()
    return {"ok": True}


@router.post("/feedback")
def feedback(payload: GambleFeedbackIn, db: Session = Depends(get_db)):
    """成单后回写实际收益."""
    history = (
        db.query(models.GambleHistory)
        .filter_by(quote_id=payload.quote_id)
        .order_by(models.GambleHistory.id.desc())
        .first()
    )
    if not history:
        history = models.GambleHistory(quote_id=payload.quote_id)
        db.add(history)
    history.optional_tours_revenue_cny = payload.optional_tours_revenue_cny
    history.profit_actual_cny = payload.profit_actual_cny
    history.won_or_lost = payload.won_or_lost
    history.updated_at = datetime.utcnow()

    # ★ ERP 钩子: 自费实际数据回写事件
    quote = db.get(models.Quote, payload.quote_id)
    if quote:
        enqueue_erp_event(db, "gamble.feedback", "gamble_history", history.id, {
            "quote_no": quote.quote_no,
            "agency_id": quote.agency_id,
            "optional_tours_revenue_cny": float(payload.optional_tours_revenue_cny),
            "profit_actual_cny": float(payload.profit_actual_cny),
            "won_or_lost": payload.won_or_lost,
        })

    db.commit()
    return {"ok": True, "history_id": history.id}
