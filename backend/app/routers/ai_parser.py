"""AI 文档解析 API."""
from __future__ import annotations

import json
import logging
import shutil
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from .. import models
from ..ai import parse_document
from ..ai.document_parser import parse_itinerary_intent
from ..config import settings
from ..database import get_db
from ..schemas import ConfirmExtractionIn
from ..utils.feature_permissions import consume_quota
from ..utils.itinerary_matcher import detect_missing_fields, match_itinerary_to_resources
from .auth import get_current_user

router = APIRouter(prefix="/ai", tags=["ai"])
logger = logging.getLogger("bws.ai.api")


@router.post("/parse")
async def parse_upload(
    request: Request,
    file: UploadFile = File(...),
    hint: str | None = Form(None),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    consume_quota(db, user, "ai_parse_resource", meta={"file": file.filename})

    sub = settings.upload_dir / datetime.utcnow().strftime("%Y%m%d")
    sub.mkdir(parents=True, exist_ok=True)
    safe_name = f"{datetime.utcnow().strftime('%H%M%S')}_{file.filename}"
    target = sub / safe_name
    with target.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        result = parse_document(target, hint=hint)
    except Exception as exc:
        logger.exception("解析失败")
        raise HTTPException(500, f"解析失败: {exc}")

    avg_confidence = None
    confidences = [r.get("confidence") for r in result.get("resources", []) if r.get("confidence") is not None]
    if confidences:
        avg_confidence = sum(confidences) / len(confidences)

    rec = models.AiExtraction(
        file_name=file.filename or safe_name,
        file_type=result.get("file_type", "unknown"),
        file_path=str(target.relative_to(settings.upload_dir.parent)),
        hint=hint,
        extraction_summary=result.get("extraction_summary"),
        extracted_json=json.dumps(result, ensure_ascii=False),
        confidence_avg=avg_confidence,
        warnings=json.dumps(result.get("warnings", []), ensure_ascii=False),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    result["extraction_id"] = rec.id
    return result


@router.get("/extractions")
def list_extractions(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(models.AiExtraction).order_by(models.AiExtraction.id.desc())
    if status:
        q = q.filter(models.AiExtraction.status == status)
    rows = q.limit(200).all()
    return [
        {
            "id": r.id,
            "file_name": r.file_name,
            "file_type": r.file_type,
            "extraction_summary": r.extraction_summary,
            "status": r.status,
            "confidence_avg": r.confidence_avg,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/extractions/{eid}")
def get_extraction(eid: int, db: Session = Depends(get_db)):
    r = db.get(models.AiExtraction, eid)
    if not r:
        raise HTTPException(404)
    return {
        "id": r.id,
        "file_name": r.file_name,
        "extracted_json": json.loads(r.extracted_json) if r.extracted_json else None,
        "confirmed_json": json.loads(r.confirmed_json) if r.confirmed_json else None,
        "status": r.status,
    }


@router.post("/extractions/{eid}/confirm")
def confirm_extraction(eid: int, payload: ConfirmExtractionIn, db: Session = Depends(get_db)):
    rec = db.get(models.AiExtraction, eid)
    if not rec:
        raise HTTPException(404)

    inserted: list[dict] = []
    notes_dropped: list[str] = []
    for resource in payload.confirmed_resources:
        rtype = resource.get("resource_type")
        data = resource.get("data") or {}
        if rtype in _TYPES_WITHOUT_NOTE and data.get("note"):
            notes_dropped.append(rtype)
        try:
            new_id = _insert_resource(rtype, data, db)
            db.flush()
            inserted.append({"resource_type": rtype, "id": new_id})
        except Exception as exc:
            # 单条失败不能污染整个 session,回滚再继续下一条
            db.rollback()
            logger.exception("入库失败 rtype=%s", rtype)
            inserted.append({"resource_type": rtype, "error": str(exc)})

    # 写修正反馈
    for c in payload.corrections or []:
        db.add(
            models.AiCorrection(
                extraction_id=rec.id,
                resource_type=c.get("resource_type", ""),
                field_name=c.get("field_name", ""),
                ai_value=str(c.get("ai_value")),
                user_value=str(c.get("user_value")),
                reason=c.get("reason"),
            )
        )

    rec.confirmed_json = json.dumps(payload.confirmed_resources, ensure_ascii=False)
    rec.status = "confirmed"
    rec.confirmed_at = datetime.utcnow()
    db.commit()

    # 写文件日志, 持续优化用
    log_path = settings.log_dir / "ai_corrections.jsonl"
    with log_path.open("a", encoding="utf-8") as f:
        for c in payload.corrections or []:
            f.write(json.dumps({"ts": datetime.utcnow().isoformat(), "extraction_id": rec.id, **c}, ensure_ascii=False) + "\n")

    return {
        "ok": True,
        "inserted": inserted,
        "notes_dropped": notes_dropped,  # 这些类型没有备注列,前端可提示
    }


def _to_date(v):
    """字符串/None/date → date|None.接受 'YYYY-MM-DD' 或 ISO 格式."""
    if v is None or v == "":
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


# 各资源类型的"备注"实际列名(model 不一致)
_NOTE_COLUMN = {
    "hotel_room": "note",                # HotelRoom.note (Text)
    "attraction": "restrictions",        # Attraction.restrictions (Text) — 用于"周日闭馆/限身高"等
    "vehicle":    "terrain_note",        # Vehicle.terrain_note (String 200)
    "guide":      "availability_note",   # Guide.availability_note (String 120)
    "spa":        "includes",            # SpaPackage.includes (Text)
}
# 这些类型的模型没有任何可放备注的列,note 会被丢弃,前端会收到 notes_dropped 提示
_TYPES_WITHOUT_NOTE = {"restaurant", "water_activity", "afternoon_tea", "optional_tour"}


def _apply_user_note(obj, rtype: str, note: str | None):
    if not note:
        return
    col = _NOTE_COLUMN.get(rtype)
    if col and hasattr(obj, col):
        setattr(obj, col, note)


def _insert_resource(rtype: str, data: dict, db: Session) -> int:
    """根据 resource_type 把 data 插入对应表."""
    dest_code = data.pop("destination_code", None)
    user_note = data.pop("note", None) if rtype != "hotel_room" else None  # hotel_room 自带 note 字段
    destination_id = None
    if dest_code:
        dest = db.query(models.Destination).filter_by(code=dest_code).first()
        if dest:
            destination_id = dest.id
    if destination_id is None:
        # 默认 DPS
        d = db.query(models.Destination).filter_by(code="DPS").first()
        if d:
            destination_id = d.id

    if rtype == "hotel_room":
        # 找/建酒店
        hotel = db.query(models.Hotel).filter_by(name_zh=data.get("hotel_name_zh")).first()
        if not hotel:
            hotel = models.Hotel(
                destination_id=destination_id,
                name_zh=data.get("hotel_name_zh") or "未命名酒店",
                name_en=data.get("hotel_name_en"),
                area=data.get("area"),
                star=data.get("star"),
            )
            db.add(hotel)
            db.flush()
        room = models.HotelRoom(
            hotel_id=hotel.id,
            room_type=data.get("room_type") or "Standard",
            max_occupancy=data.get("max_occupancy") or 2,
            breakfast_included=bool(data.get("breakfast_included")),
            cost_idr_low=data.get("cost_idr_low") or 0,
            cost_idr_high=data.get("cost_idr_high") or data.get("cost_idr_low") or 0,
            valid_from=_to_date(data.get("valid_from")),
            valid_to=_to_date(data.get("valid_to")),
            supplier=data.get("supplier"),
            note=data.get("note"),
        )
        db.add(room)
        db.flush()
        return room.id

    if rtype == "attraction":
        a = models.Attraction(destination_id=destination_id, **{k: v for k, v in data.items() if hasattr(models.Attraction, k)})
        _apply_user_note(a, rtype, user_note)
        db.add(a)
        db.flush()
        return a.id

    if rtype == "restaurant":
        # restaurant 没有 note 列但有 area;data.note 已在前面 pop 掉
        r = models.Restaurant(destination_id=destination_id, **{k: v for k, v in data.items() if hasattr(models.Restaurant, k)})
        db.add(r)
        db.flush()
        return r.id

    if rtype == "vehicle":
        v = models.Vehicle(destination_id=destination_id, **{k: v for k, v in data.items() if hasattr(models.Vehicle, k)})
        _apply_user_note(v, rtype, user_note)
        db.add(v)
        db.flush()
        return v.id

    if rtype == "guide":
        g = models.Guide(destination_id=destination_id, **{k: v for k, v in data.items() if hasattr(models.Guide, k)})
        _apply_user_note(g, rtype, user_note)
        db.add(g)
        db.flush()
        return g.id

    if rtype == "spa":
        s = models.SpaPackage(destination_id=destination_id, **{k: v for k, v in data.items() if hasattr(models.SpaPackage, k)})
        _apply_user_note(s, rtype, user_note)
        db.add(s)
        db.flush()
        return s.id

    if rtype == "water_activity":
        w = models.WaterActivity(destination_id=destination_id, **{k: v for k, v in data.items() if hasattr(models.WaterActivity, k)})
        db.add(w)
        db.flush()
        return w.id

    if rtype == "afternoon_tea":
        t = models.AfternoonTea(destination_id=destination_id, **{k: v for k, v in data.items() if hasattr(models.AfternoonTea, k)})
        db.add(t)
        db.flush()
        return t.id

    if rtype == "optional_tour":
        ot = models.OptionalTour(destination_id=destination_id, **{k: v for k, v in data.items() if hasattr(models.OptionalTour, k)})
        db.add(ot)
        db.flush()
        return ot.id

    raise ValueError(f"未知资源类型: {rtype}")


# ============================================================
#  v0.6 — 客户行程意向上传 → 直接生成 quote draft + 缺失字段
# ============================================================
@router.post("/parse-itinerary")
async def parse_customer_itinerary(
    request: Request,
    file: UploadFile = File(...),
    hint: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """B 端业务员把客户的"行程意向"(PDF/Word/Excel/图片) 上传 →
    AI 抽出 quote_draft → 后端做资源匹配 → 检测缺失字段 → 返回完整结果.

    前端拿到后:
      1. 弹"补漏表单"(missing_fields) 让用户补完
      2. 用户提交 → POST /quotes 创建 → POST /quotes/{id}/calculate 一键算价
    """
    user = get_current_user(request, db)
    # v0.7: 配额 + 权限 (会自动按周期重置, 超额抛 429)
    consume_quota(db, user, "ai_parse_itinerary", meta={"file": file.filename, "hint": hint})

    # 1) 落盘
    sub = settings.upload_dir / datetime.utcnow().strftime("%Y%m%d")
    sub.mkdir(parents=True, exist_ok=True)
    safe_name = f"itin_{datetime.utcnow().strftime('%H%M%S')}_{file.filename}"
    target = sub / safe_name
    with target.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    # 2) AI 解析 → quote_draft
    try:
        ai_result = parse_itinerary_intent(target, hint=hint)
    except Exception as exc:
        logger.exception("行程意向解析失败")
        raise HTTPException(500, f"解析失败: {exc}")

    quote_draft = ai_result.get("quote_draft") or {}

    # 3) 资源匹配 (酒店/景点/餐厅/车辆名 → 真实 ID)
    resolved_draft, match_log = match_itinerary_to_resources(quote_draft, db)

    # 4) 缺失字段检测
    ai_missing = ai_result.get("missing_fields") or []
    backend_missing = detect_missing_fields(resolved_draft, match_log)
    # 合并 AI 提示的 + 后端检测的, 去重
    seen = set()
    final_missing = []
    for m in backend_missing:
        seen.add(m["field"])
        final_missing.append(m)
    for f in ai_missing:
        if f not in seen:
            final_missing.append({
                "field": f, "label": f"AI 提示缺失: {f}",
                "type": "string", "default": None, "current": None, "required": False,
            })

    return {
        "success": True,
        "extraction_summary": ai_result.get("extraction_summary"),
        "ai_confidence": ai_result.get("confidence"),
        "quote_draft": resolved_draft,
        "match_log": match_log,
        "missing_fields": final_missing,
        "warnings": ai_result.get("warnings", []),
        "file_name": file.filename,
        "file_type": ai_result.get("file_type"),
    }


@router.post("/quote-from-itinerary")
def create_quote_from_itinerary(payload: dict, request: Request, db: Session = Depends(get_db)):
    """v0.6 — 接收前端补漏后的 quote_draft, 创建 Quote + 一键 calculate.

    Body: { "quote_draft": {...} }  ← 已经是合法 QuoteIn 结构
    返回: { "quote_id", "quote_no", "calculate": {...} }
    """
    from .quotes import _generate_quote_no, _persist_days
    from ..schemas import QuoteIn

    user = get_current_user(request, db)
    consume_quota(db, user, "create_quote", meta={"source": "ai_itinerary"})

    raw = payload.get("quote_draft") or payload
    try:
        qin = QuoteIn(**raw)
    except Exception as exc:
        raise HTTPException(400, f"quote_draft 校验失败: {exc}")

    quote = models.Quote(quote_no=_generate_quote_no())
    db.add(quote)
    if user:
        quote.created_by_user_id = user.id
        quote.agency_id = user.agency_id
        quote.created_by = user.username
    quote.agency_name = qin.agency_name
    quote.agency_contact = qin.agency_contact
    quote.customer_name = qin.customer_name
    quote.pax_adult = qin.pax_adult
    quote.pax_child = qin.pax_child
    quote.pax_senior = getattr(qin, "pax_senior", 0) or 0
    quote.start_date = qin.start_date
    quote.end_date = qin.end_date
    quote.destination_codes = ",".join(qin.destination_codes or [])
    quote.season = qin.season
    quote.customer_type = qin.customer_type
    quote.is_first_time_agency = qin.is_first_time_agency
    quote.notes = qin.notes
    if qin.exchange_rate is not None:
        quote.exchange_rate = qin.exchange_rate
    quote.total_days = len(qin.days) or qin.total_days or 1
    quote.free_days = sum(1 for d in qin.days if d.is_free or (d.free_hours or 0) >= 8)
    db.flush()
    _persist_days(quote, qin, db)
    db.commit()
    db.refresh(quote)

    # 立即算价
    from .quotes import calculate_quote
    calc = calculate_quote(quote.id, db)

    return {
        "ok": True,
        "quote_id": quote.id,
        "quote_no": quote.quote_no,
        "calculate": calc,
    }
