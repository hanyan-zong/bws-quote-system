"""资源库 CRUD — 酒店/景点/餐厅/车辆/导游/SPA/水上/下午茶/自费.

v0.4: list 端点根据当前用户角色裁剪 cost_idr_* 字段.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session, joinedload

from .. import models
from ..database import get_db
from ..utils.permissions import filter_resource_list, filter_hotel_with_rooms, require_role
from .auth import get_current_user

# v0.9.2: 写操作要 admin 角色 (super_admin 内部公司 OP) — agent/viewer 即使 curl 也拒
_admin_only = [Depends(require_role("super_admin", "ops_manager"))]
from ..schemas import (
    AttractionIn,
    AttractionOut,
    GuideIn,
    GuideOut,
    HotelIn,
    HotelOut,
    HotelRoomIn,
    OptionalTourIn,
    OptionalTourOut,
    RestaurantIn,
    RestaurantOut,
    SimpleResourceIn,
    VehicleIn,
    VehicleOut,
)

router = APIRouter(prefix="/resources", tags=["resources"])


# ============================================================
#  目的地
# ============================================================
@router.get("/destinations")
def list_destinations(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.query(models.Destination).order_by(models.Destination.id).all()
    return [{"id": r.id, "code": r.code, "name_zh": r.name_zh, "name_id": r.name_id} for r in rows]


# ============================================================
#  酒店
# ============================================================
@router.get("/hotels")
def list_hotels(
    request: Request,
    destination_code: str | None = Query(None),
    keyword: str | None = Query(None),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    user = get_current_user(request, db)
    q = db.query(models.Hotel).options(joinedload(models.Hotel.rooms))
    if destination_code:
        dest = db.query(models.Destination).filter_by(code=destination_code).first()
        if dest:
            q = q.filter(models.Hotel.destination_id == dest.id)
    if keyword:
        kw = f"%{keyword}%"
        q = q.filter((models.Hotel.name_zh.like(kw)) | (models.Hotel.name_en.like(kw)))
    out: list[dict[str, Any]] = []
    for h in q.all():
        out.append(
            {
                "id": h.id,
                "destination_id": h.destination_id,
                "name_zh": h.name_zh,
                "name_en": h.name_en,
                "star": h.star,
                "area": h.area,
                "latitude": h.latitude,
                "longitude": h.longitude,
                "airport_distance_min": h.airport_distance_min,
                "rooms": [
                    {
                        "id": r.id,
                        "room_type": r.room_type,
                        "max_occupancy": r.max_occupancy,
                        "breakfast_included": r.breakfast_included,
                        "cost_idr_low": float(r.cost_idr_low),
                        "cost_idr_high": float(r.cost_idr_high),
                        "valid_from": r.valid_from.isoformat() if r.valid_from else None,
                        "valid_to": r.valid_to.isoformat() if r.valid_to else None,
                        "supplier": r.supplier,
                        "note": r.note,
                    }
                    for r in h.rooms
                ],
            }
        )
    return filter_hotel_with_rooms(out, user)


@router.post("/hotels", dependencies=_admin_only)
def create_or_update_hotel(payload: HotelIn, db: Session = Depends(get_db)):
    if payload.id:
        hotel = db.get(models.Hotel, payload.id)
        if not hotel:
            raise HTTPException(404, "酒店不存在")
    else:
        hotel = models.Hotel()
        db.add(hotel)
    hotel.destination_id = payload.destination_id
    hotel.name_zh = payload.name_zh
    hotel.name_en = payload.name_en
    hotel.star = payload.star
    hotel.area = payload.area
    hotel.latitude = payload.latitude
    hotel.longitude = payload.longitude
    hotel.airport_distance_min = payload.airport_distance_min
    hotel.description = payload.description
    db.flush()

    # 房型 — 简化: 全删全建
    if payload.rooms is not None:
        db.query(models.HotelRoom).filter_by(hotel_id=hotel.id).delete()
        for r in payload.rooms:
            room = models.HotelRoom(
                hotel_id=hotel.id,
                room_type=r.room_type,
                max_occupancy=r.max_occupancy,
                breakfast_included=r.breakfast_included,
                cost_idr_low=r.cost_idr_low,
                cost_idr_high=r.cost_idr_high,
                valid_from=r.valid_from,
                valid_to=r.valid_to,
                supplier=r.supplier,
                note=r.note,
            )
            db.add(room)
    db.commit()
    return {"id": hotel.id, "message": "ok"}


@router.delete("/hotels/{hotel_id}", dependencies=_admin_only)
def delete_hotel(hotel_id: int, db: Session = Depends(get_db)):
    h = db.get(models.Hotel, hotel_id)
    if not h:
        raise HTTPException(404, "酒店不存在")
    db.delete(h)
    db.commit()
    return {"ok": True}


# ============================================================
#  景点
# ============================================================
@router.get("/attractions")
def list_attractions(
    request: Request,
    destination_code: str | None = Query(None),
    area: str | None = Query(None),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    q = db.query(models.Attraction)
    if destination_code:
        d = db.query(models.Destination).filter_by(code=destination_code).first()
        if d:
            q = q.filter(models.Attraction.destination_id == d.id)
    if area:
        q = q.filter(models.Attraction.area == area)
    rows = [
        {
            "id": a.id,
            "destination_id": a.destination_id,
            "name_zh": a.name_zh,
            "name_en": a.name_en,
            "area": a.area,
            "latitude": a.latitude,
            "longitude": a.longitude,
            "ticket_idr_adult": float(a.ticket_idr_adult),
            "ticket_idr_child": float(a.ticket_idr_child),
            "recommended_minutes": a.recommended_minutes,
            "open_time": a.open_time.isoformat() if a.open_time else None,
            "close_time": a.close_time.isoformat() if a.close_time else None,
            "has_guide_service": a.has_guide_service,
            "restrictions": a.restrictions,
        }
        for a in q.all()
    ]
    return filter_resource_list(rows, "attraction", user)


@router.post("/attractions", dependencies=_admin_only)
def upsert_attraction(payload: AttractionIn, db: Session = Depends(get_db)):
    if payload.id:
        a = db.get(models.Attraction, payload.id)
        if not a:
            raise HTTPException(404)
    else:
        a = models.Attraction()
        db.add(a)
    for f in [
        "destination_id", "name_zh", "name_en", "area",
        "latitude", "longitude", "ticket_idr_adult", "ticket_idr_child",
        "recommended_minutes", "open_time", "close_time",
        "has_guide_service", "restrictions",
    ]:
        setattr(a, f, getattr(payload, f))
    db.commit()
    db.refresh(a)
    return {"id": a.id}


@router.delete("/attractions/{aid}", dependencies=_admin_only)
def delete_attraction(aid: int, db: Session = Depends(get_db)):
    a = db.get(models.Attraction, aid)
    if not a:
        raise HTTPException(404)
    db.delete(a)
    db.commit()
    return {"ok": True}


# ============================================================
#  餐厅
# ============================================================
@router.get("/restaurants")
def list_restaurants(request: Request, destination_code: str | None = Query(None), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    q = db.query(models.Restaurant)
    if destination_code:
        d = db.query(models.Destination).filter_by(code=destination_code).first()
        if d:
            q = q.filter(models.Restaurant.destination_id == d.id)
    rows = [
        {
            "id": r.id,
            "destination_id": r.destination_id,
            "name_zh": r.name_zh,
            "cuisine": r.cuisine,
            "meal_type": r.meal_type,
            "area": r.area,
            "cost_idr_per_person": float(r.cost_idr_per_person),
            "min_pax": r.min_pax,
            "includes_drink": r.includes_drink,
            "recommended_minutes": r.recommended_minutes,
        }
        for r in q.all()
    ]
    return filter_resource_list(rows, "restaurant", user)


@router.post("/restaurants", dependencies=_admin_only)
def upsert_restaurant(payload: RestaurantIn, db: Session = Depends(get_db)):
    if payload.id:
        r = db.get(models.Restaurant, payload.id)
        if not r:
            raise HTTPException(404)
    else:
        r = models.Restaurant()
        db.add(r)
    for f in [
        "destination_id", "name_zh", "cuisine", "meal_type",
        "area", "latitude", "longitude", "cost_idr_per_person",
        "min_pax", "includes_drink", "recommended_minutes",
    ]:
        setattr(r, f, getattr(payload, f))
    db.commit()
    db.refresh(r)
    return {"id": r.id}


@router.delete("/restaurants/{rid}", dependencies=_admin_only)
def delete_restaurant(rid: int, db: Session = Depends(get_db)):
    r = db.get(models.Restaurant, rid)
    if not r:
        raise HTTPException(404)
    db.delete(r)
    db.commit()
    return {"ok": True}


# ============================================================
#  车辆
# ============================================================
@router.get("/vehicles")
def list_vehicles(request: Request, destination_code: str | None = Query(None), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    q = db.query(models.Vehicle)
    if destination_code:
        d = db.query(models.Destination).filter_by(code=destination_code).first()
        if d:
            q = q.filter(models.Vehicle.destination_id == d.id)
    rows = [
        {
            "id": v.id,
            "destination_id": v.destination_id,
            "seat_count": v.seat_count,
            "vehicle_type": v.vehicle_type,
            "cost_idr_per_day": float(v.cost_idr_per_day),
            "includes_fuel": v.includes_fuel,
            "includes_driver": v.includes_driver,
            "restrictions": v.restrictions,
            "max_single_leg_minutes": v.max_single_leg_minutes,
            "max_daily_minutes": v.max_daily_minutes,
            "terrain_note": v.terrain_note,
        }
        for v in q.all()
    ]
    # 注意: vehicle 列表的 return [...] 已在 list_vehicles 中, 把上面 [ 改为 rows = [
    return filter_resource_list(rows, "vehicle", user)


@router.post("/vehicles", dependencies=_admin_only)
def upsert_vehicle(payload: VehicleIn, db: Session = Depends(get_db)):
    if payload.id:
        v = db.get(models.Vehicle, payload.id)
        if not v:
            raise HTTPException(404)
    else:
        v = models.Vehicle()
        db.add(v)
    for f in [
        "destination_id", "seat_count", "vehicle_type", "cost_idr_per_day",
        "includes_fuel", "includes_driver", "restrictions",
        "max_single_leg_minutes", "max_daily_minutes", "terrain_note",
    ]:
        setattr(v, f, getattr(payload, f))
    db.commit()
    db.refresh(v)
    return {"id": v.id}


@router.delete("/vehicles/{vid}", dependencies=_admin_only)
def delete_vehicle(vid: int, db: Session = Depends(get_db)):
    v = db.get(models.Vehicle, vid)
    if not v:
        raise HTTPException(404)
    db.delete(v)
    db.commit()
    return {"ok": True}


# ============================================================
#  导游
# ============================================================
@router.get("/guides")
def list_guides(request: Request, destination_code: str | None = Query(None), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    q = db.query(models.Guide)
    if destination_code:
        d = db.query(models.Destination).filter_by(code=destination_code).first()
        if d:
            q = q.filter(models.Guide.destination_id == d.id)
    rows = [
        {
            "id": g.id,
            "destination_id": g.destination_id,
            "name_zh": g.name_zh,
            "language": g.language,
            "level": g.level,
            "cost_idr_per_day": float(g.cost_idr_per_day),
            "max_pax": g.max_pax,
            "availability_note": g.availability_note,
        }
        for g in q.all()
    ]
    return filter_resource_list(rows, "guide", user)


@router.post("/guides", dependencies=_admin_only)
def upsert_guide(payload: GuideIn, db: Session = Depends(get_db)):
    if payload.id:
        g = db.get(models.Guide, payload.id)
        if not g:
            raise HTTPException(404)
    else:
        g = models.Guide()
        db.add(g)
    for f in [
        "destination_id", "name_zh", "language", "level",
        "cost_idr_per_day", "max_pax", "availability_note",
    ]:
        setattr(g, f, getattr(payload, f))
    db.commit()
    db.refresh(g)
    return {"id": g.id}


@router.delete("/guides/{gid}", dependencies=_admin_only)
def delete_guide(gid: int, db: Session = Depends(get_db)):
    g = db.get(models.Guide, gid)
    if not g:
        raise HTTPException(404)
    db.delete(g)
    db.commit()
    return {"ok": True}


# ============================================================
#  自费
# ============================================================
@router.get("/optional-tours")
def list_optional_tours(request: Request, destination_code: str | None = Query(None), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    q = db.query(models.OptionalTour)
    if destination_code:
        d = db.query(models.Destination).filter_by(code=destination_code).first()
        if d:
            q = q.filter(models.OptionalTour.destination_id == d.id)
    rows = [
        {
            "id": ot.id,
            "destination_id": ot.destination_id,
            "name_zh": ot.name_zh,
            "sale_price_cny": float(ot.sale_price_cny),
            "cost_idr": float(ot.cost_idr),
            "margin_cny": float(ot.margin_cny),
            "historical_purchase_rate": ot.historical_purchase_rate,
            "target_audience": ot.target_audience,
            "best_time": ot.best_time,
            "category": ot.category,
            "overlap_attraction_ids": ot.overlap_attraction_ids,
            "overlap_restaurant_ids": ot.overlap_restaurant_ids,
            "overlap_spa_ids": ot.overlap_spa_ids,
            "overlap_water_ids": ot.overlap_water_ids,
        }
        for ot in q.all()
    ]
    return filter_resource_list(rows, "optional_tour", user)


@router.post("/optional-tours", dependencies=_admin_only)
def upsert_optional_tour(payload: OptionalTourIn, db: Session = Depends(get_db)):
    if payload.id:
        ot = db.get(models.OptionalTour, payload.id)
        if not ot:
            raise HTTPException(404)
    else:
        ot = models.OptionalTour()
        db.add(ot)
    for f in [
        "destination_id", "name_zh", "sale_price_cny", "cost_idr",
        "margin_cny", "historical_purchase_rate", "target_audience", "best_time",
        "category", "overlap_attraction_ids", "overlap_restaurant_ids",
        "overlap_spa_ids", "overlap_water_ids",
    ]:
        setattr(ot, f, getattr(payload, f))
    db.commit()
    db.refresh(ot)
    return {"id": ot.id}


@router.delete("/optional-tours/{oid}", dependencies=_admin_only)
def delete_optional_tour(oid: int, db: Session = Depends(get_db)):
    ot = db.get(models.OptionalTour, oid)
    if not ot:
        raise HTTPException(404)
    db.delete(ot)
    db.commit()
    return {"ok": True}


# ============================================================
#  SPA / 水上 / 下午茶 — 共用 SimpleResource
# ============================================================
SIMPLE_MODELS = {
    "spa": models.SpaPackage,
    "water": models.WaterActivity,
    "tea": models.AfternoonTea,
}


@router.get("/simple/{kind}")
def list_simple(kind: str, request: Request, destination_code: str | None = Query(None), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    Model = SIMPLE_MODELS.get(kind)
    if not Model:
        raise HTTPException(400, "kind 必须是 spa/water/tea")
    q = db.query(Model)
    if destination_code:
        d = db.query(models.Destination).filter_by(code=destination_code).first()
        if d:
            q = q.filter(Model.destination_id == d.id)
    rows = q.all()
    out = []
    for r in rows:
        item = {
            "id": r.id,
            "destination_id": r.destination_id,
            "name_zh": getattr(r, "name_zh", None) or getattr(r, "package_name", None),
            "cost_idr_per_person": float(getattr(r, "cost_idr_per_person", 0)),
            "duration_minutes": getattr(r, "duration_minutes", None) or getattr(r, "recommended_minutes", None),
            "min_pax": getattr(r, "min_pax", None),
            "max_pax": getattr(r, "max_pax", None),
            "area": getattr(r, "area", None),
            "venue": getattr(r, "venue", None),
            "location": getattr(r, "location", None),
            "brand": getattr(r, "brand", None),
            "package_name": getattr(r, "package_name", None),
            "includes": getattr(r, "includes", None),
            "age_limit": getattr(r, "age_limit", None),
        }
        out.append(item)
    rtype_map = {"spa": "spa", "water": "water_activity", "tea": "afternoon_tea"}
    return filter_resource_list(out, rtype_map.get(kind, kind), user)


@router.post("/simple/{kind}", dependencies=_admin_only)
def upsert_simple(kind: str, payload: dict, db: Session = Depends(get_db)):
    """统一新增/更新 SPA / 水上 / 下午茶."""
    Model = SIMPLE_MODELS.get(kind)
    if not Model:
        raise HTTPException(400, "kind 必须是 spa/water/tea")
    rid = payload.pop("id", None)
    if rid:
        obj = db.get(Model, rid)
        if not obj:
            raise HTTPException(404)
    else:
        obj = Model()
        db.add(obj)
    for k, v in payload.items():
        if hasattr(obj, k) and k != "id":
            setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return {"id": obj.id}


@router.delete("/simple/{kind}/{rid}", dependencies=_admin_only)
def delete_simple(kind: str, rid: int, db: Session = Depends(get_db)):
    Model = SIMPLE_MODELS.get(kind)
    if not Model:
        raise HTTPException(400, "kind 必须是 spa/water/tea")
    obj = db.get(Model, rid)
    if not obj:
        raise HTTPException(404)
    db.delete(obj)
    db.commit()
    return {"ok": True}
