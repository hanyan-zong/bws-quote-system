"""行程合理性校验 API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from .. import models
from ..database import get_db
from ..utils import feasibility_engine

router = APIRouter(prefix="/feasibility", tags=["feasibility"])


@router.post("/{quote_id}")
def run_check(quote_id: int, run_ai: bool = False, db: Session = Depends(get_db)):
    quote = (
        db.query(models.Quote)
        .options(joinedload(models.Quote.days).joinedload(models.QuoteDay.items))
        .filter_by(id=quote_id)
        .first()
    )
    if not quote:
        raise HTTPException(404)
    report = feasibility_engine.check_quote(quote, db, run_ai_review=run_ai)
    return report.to_dict()


@router.post("/distance")
def upsert_distance(payload: dict, db: Session = Depends(get_db)):
    rec = (
        db.query(models.Distance)
        .filter_by(
            from_type=payload["from_type"],
            from_id=payload["from_id"],
            to_type=payload["to_type"],
            to_id=payload["to_id"],
        )
        .first()
    )
    if not rec:
        rec = models.Distance(**payload)
        db.add(rec)
    else:
        for k, v in payload.items():
            setattr(rec, k, v)
    db.commit()
    db.refresh(rec)
    return {"id": rec.id}


@router.get("/distances")
def list_distances(from_type: str | None = None, from_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(models.Distance)
    if from_type:
        q = q.filter(models.Distance.from_type == from_type)
    if from_id:
        q = q.filter(models.Distance.from_id == from_id)
    return [
        {
            "id": r.id,
            "from_type": r.from_type,
            "from_id": r.from_id,
            "to_type": r.to_type,
            "to_id": r.to_id,
            "distance_km": r.distance_km,
            "normal_minutes": r.normal_minutes,
            "peak_minutes": r.peak_minutes,
            "holiday_minutes": r.holiday_minutes,
        }
        for r in q.limit(500).all()
    ]
