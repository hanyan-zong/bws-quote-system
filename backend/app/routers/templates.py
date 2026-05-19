"""一日游模板 API."""
from __future__ import annotations

import logging
import shutil
from datetime import datetime
from ..utils.time_utils import now_utc
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session, joinedload

from .. import models
from ..ai import parse_template_document
from ..config import settings
from ..database import get_db
from ..schemas import TemplateIn
from ..utils.permissions import require_role

router = APIRouter(prefix="/templates", tags=["templates"])
logger = logging.getLogger("bws.templates")

# v0.9.2: 模板写操作要 admin 角色
_admin_only = [Depends(require_role("super_admin", "ops_manager"))]


@router.get("")
def list_templates(destination_code: str | None = None, db: Session = Depends(get_db)):
    q = db.query(models.DayTripTemplate).options(
        joinedload(models.DayTripTemplate.attractions),
        joinedload(models.DayTripTemplate.restaurants),
    )
    if destination_code:
        d = db.query(models.Destination).filter_by(code=destination_code).first()
        if d:
            q = q.filter(models.DayTripTemplate.destination_id == d.id)
    out = []
    for t in q.all():
        out.append({
            "id": t.id,
            "destination_id": t.destination_id,
            "name_zh": t.name_zh,
            "name_en": t.name_en,
            "description": t.description,
            "total_minutes_estimate": t.total_minutes_estimate,
            "recommended_pax_min": t.recommended_pax_min,
            "recommended_pax_max": t.recommended_pax_max,
            "difficulty": t.difficulty,
            "attractions": [
                {"attraction_id": ta.attraction_id, "order_index": ta.order_index, "stay_minutes": ta.stay_minutes}
                for ta in t.attractions
            ],
            "restaurants": [
                {"restaurant_id": tr.restaurant_id, "meal_type": tr.meal_type}
                for tr in t.restaurants
            ],
        })
    return out


@router.post("", dependencies=_admin_only)
def upsert_template(payload: TemplateIn, db: Session = Depends(get_db)):
    if payload.id:
        t = db.get(models.DayTripTemplate, payload.id)
        if not t:
            raise HTTPException(404)
    else:
        t = models.DayTripTemplate()
        db.add(t)
    for f in [
        "destination_id", "name_zh", "name_en", "description",
        "total_minutes_estimate", "recommended_pax_min", "recommended_pax_max", "difficulty",
    ]:
        setattr(t, f, getattr(payload, f))
    db.flush()
    db.query(models.TemplateAttraction).filter_by(template_id=t.id).delete()
    db.query(models.TemplateRestaurant).filter_by(template_id=t.id).delete()
    for a in payload.attractions:
        db.add(models.TemplateAttraction(template_id=t.id, **a.model_dump()))
    for r in payload.restaurants:
        db.add(models.TemplateRestaurant(template_id=t.id, **r.model_dump()))
    db.commit()
    return {"id": t.id}


@router.get("/{tid}")
def get_template(tid: int, db: Session = Depends(get_db)):
    """模板详情 — 含景点/餐厅完整名称(供前端"查看"使用)."""
    t = (
        db.query(models.DayTripTemplate)
        .options(
            joinedload(models.DayTripTemplate.attractions),
            joinedload(models.DayTripTemplate.restaurants),
        )
        .filter(models.DayTripTemplate.id == tid)
        .first()
    )
    if not t:
        raise HTTPException(404)

    # 拉关联资源名
    attr_ids = [ta.attraction_id for ta in t.attractions]
    rest_ids = [tr.restaurant_id for tr in t.restaurants]
    attrs = {a.id: a for a in db.query(models.Attraction).filter(models.Attraction.id.in_(attr_ids)).all()} if attr_ids else {}
    rests = {r.id: r for r in db.query(models.Restaurant).filter(models.Restaurant.id.in_(rest_ids)).all()} if rest_ids else {}
    dest = db.get(models.Destination, t.destination_id)

    return {
        "id": t.id,
        "destination_id": t.destination_id,
        "destination_code": dest.code if dest else None,
        "destination_name": dest.name_zh if dest else None,
        "name_zh": t.name_zh,
        "name_en": t.name_en,
        "description": t.description,
        "total_minutes_estimate": t.total_minutes_estimate,
        "recommended_pax_min": t.recommended_pax_min,
        "recommended_pax_max": t.recommended_pax_max,
        "difficulty": t.difficulty,
        "attractions": [
            {
                "attraction_id": ta.attraction_id,
                "order_index": ta.order_index,
                "stay_minutes": ta.stay_minutes,
                "name_zh": attrs[ta.attraction_id].name_zh if ta.attraction_id in attrs else "(已删除)",
                "area": attrs[ta.attraction_id].area if ta.attraction_id in attrs else None,
                "ticket_idr_adult": float(attrs[ta.attraction_id].ticket_idr_adult) if ta.attraction_id in attrs else None,
            }
            for ta in sorted(t.attractions, key=lambda x: x.order_index)
        ],
        "restaurants": [
            {
                "restaurant_id": tr.restaurant_id,
                "meal_type": tr.meal_type,
                "name_zh": rests[tr.restaurant_id].name_zh if tr.restaurant_id in rests else "(已删除)",
                "cost_idr_per_person": float(rests[tr.restaurant_id].cost_idr_per_person) if tr.restaurant_id in rests else None,
            }
            for tr in t.restaurants
        ],
    }


def _resolve_attraction_id(name_zh: str, db: Session, destination_id: int | None) -> int | None:
    """按中文名 substring/精确 匹配现有 Attraction;优先同目的地."""
    if not name_zh:
        return None
    q = db.query(models.Attraction)
    if destination_id:
        q = q.filter(models.Attraction.destination_id == destination_id)
    # 精确
    exact = q.filter(models.Attraction.name_zh == name_zh).first()
    if exact:
        return exact.id
    # substring 模糊
    like = q.filter(models.Attraction.name_zh.like(f"%{name_zh}%")).first()
    return like.id if like else None


def _resolve_restaurant_id(name_zh: str, db: Session, destination_id: int | None) -> int | None:
    if not name_zh:
        return None
    q = db.query(models.Restaurant)
    if destination_id:
        q = q.filter(models.Restaurant.destination_id == destination_id)
    exact = q.filter(models.Restaurant.name_zh == name_zh).first()
    if exact:
        return exact.id
    like = q.filter(models.Restaurant.name_zh.like(f"%{name_zh}%")).first()
    return like.id if like else None


@router.post("/parse-document", dependencies=_admin_only)
async def parse_template_upload(
    file: UploadFile = File(...),
    hint: str | None = Form(None),
    destination_code: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """上传一日游文档,AI 抽取模板骨架 + 解析景点/餐厅名为现有资源 ID."""
    sub = settings.upload_dir / "templates" / now_utc().strftime("%Y%m%d")
    sub.mkdir(parents=True, exist_ok=True)
    safe_name = f"{now_utc().strftime('%H%M%S')}_{file.filename}"
    target = sub / safe_name
    with target.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        result = parse_template_document(target, hint=hint)
    except Exception as exc:
        logger.exception("模板解析失败")
        raise HTTPException(500, f"解析失败: {exc}")

    # 决定目的地
    dest_code = destination_code or result.get("destination_code") or "DPS"
    dest = db.query(models.Destination).filter_by(code=dest_code).first()
    destination_id = dest.id if dest else None

    # 解析景点/餐厅名 → ID
    unmatched_attractions: list[str] = []
    resolved_attractions = []
    for i, a in enumerate(result.get("attractions") or [], start=1):
        name = a.get("name_zh") or a.get("name") or ""
        aid = _resolve_attraction_id(name, db, destination_id)
        if aid:
            resolved_attractions.append({
                "attraction_id": aid,
                "name_zh": name,
                "stay_minutes": a.get("stay_minutes"),
                "order_index": a.get("order_index") or i,
            })
        else:
            unmatched_attractions.append(name)

    unmatched_restaurants: list[str] = []
    resolved_restaurants = []
    for r in result.get("restaurants") or []:
        name = r.get("name_zh") or r.get("name") or ""
        rid = _resolve_restaurant_id(name, db, destination_id)
        if rid:
            resolved_restaurants.append({
                "restaurant_id": rid,
                "name_zh": name,
                "meal_type": r.get("meal_type") or "lunch",
            })
        else:
            unmatched_restaurants.append(name)

    return {
        "ok": True,
        "destination_id": destination_id,
        "destination_code": dest_code,
        "name_zh": result.get("name_zh") or "",
        "name_en": result.get("name_en"),
        "description": result.get("description"),
        "total_minutes_estimate": result.get("total_minutes_estimate") or 480,
        "difficulty": result.get("difficulty") or "easy",
        "attractions": resolved_attractions,
        "restaurants": resolved_restaurants,
        "unmatched_attractions": unmatched_attractions,
        "unmatched_restaurants": unmatched_restaurants,
        "warnings": result.get("warnings") or [],
        "_mock": result.get("_mock", False),
    }


@router.delete("/{tid}", dependencies=_admin_only)
def delete_template(tid: int, db: Session = Depends(get_db)):
    t = db.get(models.DayTripTemplate, tid)
    if not t:
        raise HTTPException(404)
    db.delete(t)
    db.commit()
    return {"ok": True}
