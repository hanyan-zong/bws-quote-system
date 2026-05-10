"""ERP 同步钩子 v0.4 — 仅写事件队列, 不实际推送.

设计:
- 业务代码调 enqueue_erp_event() 写入 erp_sync_events (status=pending)
- 不在钩子里 commit, 由外层业务事务统一提交(保证原子性)
- ERP 配置 enabled=False 时直接 return, 不写队列(避免数据膨胀)
- v0.5 上 worker 才真正推送; 当前队列只是审计与未来回放素材
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from .. import models

logger = logging.getLogger("bws.erp_hook")


def _load_erp_config(db: Session) -> models.ErpConfig:
    cfg = db.query(models.ErpConfig).first()
    if cfg:
        return cfg
    return models.ErpConfig(enabled=False)


def enqueue_erp_event(
    db: Session,
    event_type: str,
    entity_type: str,
    entity_id: int,
    payload: dict[str, Any],
    correlation_id: str | None = None,
) -> models.ErpSyncEvent | None:
    """统一入口 — 检查启用状态后写事件队列.

    重要:
      - 不调 db.commit(), 由外层业务 commit 一起写
      - 业务回滚时事件也回滚, 保持一致性
    """
    cfg = _load_erp_config(db)
    if not cfg.enabled:
        return None  # 关闭时不写 — 避免数据膨胀

    try:
        ev = models.ErpSyncEvent(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=json.dumps(payload, ensure_ascii=False, default=str),
            status="pending",
            correlation_id=correlation_id,
        )
        db.add(ev)
        return ev
    except Exception:
        logger.exception("enqueue erp event failed: %s/%s", event_type, entity_id)
        return None


def quote_to_payload(quote: models.Quote) -> dict[str, Any]:
    """把 Quote 序列化成 ERP webhook payload."""
    return {
        "quote_no": quote.quote_no,
        "agency_id": quote.agency_id,
        "agency_name": quote.agency_name,
        "customer_name": quote.customer_name,
        "pax_adult": quote.pax_adult,
        "pax_child": quote.pax_child,
        "start_date": quote.start_date.isoformat() if quote.start_date else None,
        "end_date": quote.end_date.isoformat() if quote.end_date else None,
        "total_days": quote.total_days,
        "destination_codes": quote.destination_codes,
        "season": quote.season,
        "customer_type": quote.customer_type,
        "exchange_rate": float(quote.exchange_rate or 0),
        "cost_idr_total": float(quote.cost_idr_total or 0),
        "cost_cny_total": float(quote.cost_cny_total or 0),
        "profit_cny_per_pax": float(quote.profit_cny_per_pax or 0),
        "gamble_cny_per_pax": float(quote.gamble_cny_per_pax or 0),
        "price_cny_per_pax": float(quote.price_cny_per_pax or 0),
        "price_cny_total": float(quote.price_cny_total or 0),
        "feasibility_status": quote.feasibility_status,
        "created_by_user_id": quote.created_by_user_id,
        "days": [
            {
                "day_index": d.day_index,
                "date": d.date.isoformat() if d.date else None,
                "is_free": d.is_free,
                "free_hours": d.free_hours,
                "hotel_id": d.hotel_id,
                "hotel_room_id": d.hotel_room_id,
                "vehicle_id": d.vehicle_id,
                "guide_id": d.guide_id,
                "lunch_restaurant_id": d.lunch_restaurant_id,
                "dinner_restaurant_id": d.dinner_restaurant_id,
                "spa_id": d.spa_id,
                "afternoon_tea_id": d.afternoon_tea_id,
                "water_activity_id": d.water_activity_id,
                "attractions": [
                    {"id": i.attraction_id, "order": i.order_index} for i in d.items
                ],
            }
            for d in quote.days
        ],
    }
