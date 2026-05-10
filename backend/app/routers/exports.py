"""报价单导出端点 (v0.5).

GET /api/v1/quotes/{id}/export?format=xlsx|pdf|docx

权限: 任何已登录用户均可导出. 但导出文件中字段按角色裁剪:
- super_admin / agency_owner: 含 IDR 成本 / 利润 / 赌额
- agent / viewer: 仅客户成交价
"""
from __future__ import annotations

import logging
import urllib.parse
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload

from .. import models
from ..database import get_db
from ..utils.exports import build_docx, build_excel, build_export_context, build_pdf
from ..utils.feature_permissions import consume_quota
from .auth import get_current_user

router = APIRouter(prefix="/quotes", tags=["exports"])
logger = logging.getLogger("bws.exports")


_MIME = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf":  "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _safe_filenames(quote_no: str, customer_name: str | None, ext: str) -> tuple[str, str]:
    """返回 (ascii_fallback, utf8_full) — HTTP header 的两种文件名表示.

    HTTP header 的 latin-1 限制不能写中文, 因此 fallback 必须 ASCII;
    完整中文名通过 RFC 5987 filename* 传输.
    """
    utf8_full = f"BWS报价单_{quote_no}"
    ascii_fallback = f"BWS_Quote_{quote_no}"
    if customer_name:
        clean_full = "".join(c for c in customer_name if c.isalnum() or c in "_- ")
        if clean_full:
            utf8_full = f"{utf8_full}_{clean_full}"
        clean_ascii = "".join(
            c for c in customer_name if c.isascii() and (c.isalnum() or c in "_- ")
        ).strip()
        if clean_ascii:
            ascii_fallback = f"{ascii_fallback}_{clean_ascii}"
    return f"{ascii_fallback}.{ext}", f"{utf8_full}.{ext}"


@router.get("/{quote_id}/export")
def export_quote(
    quote_id: int,
    request: Request,
    format: Literal["xlsx", "pdf", "docx"] = Query("xlsx"),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    quote = (
        db.query(models.Quote)
        .options(joinedload(models.Quote.days).joinedload(models.QuoteDay.items))
        .options(joinedload(models.Quote.gamble_records))
        .filter_by(id=quote_id)
        .first()
    )
    if not quote:
        raise HTTPException(404, "报价不存在")

    # 权限校验 — 复用 quotes 路由的策略
    if user:
        if user.role == "agent" and quote.created_by_user_id != user.id:
            raise HTTPException(403, "无权导出他人报价")
        if user.role == "agency_owner" and quote.agency_id != user.agency_id:
            raise HTTPException(403, "无权导出其他旅行社的报价")

    # v0.7: 配额 + 权限 (按格式分别计) — 在生成前消耗
    feature_key = f"export_quote_{format}"
    consume_quota(db, user, feature_key, meta={"quote_id": quote_id, "quote_no": quote.quote_no})

    ctx = build_export_context(quote, db, user)

    try:
        if format == "xlsx":
            data = build_excel(ctx)
        elif format == "pdf":
            data = build_pdf(ctx)
        elif format == "docx":
            data = build_docx(ctx)
        else:
            raise HTTPException(400, f"不支持的格式 {format}")
    except Exception:
        logger.exception("导出失败 quote_id=%s format=%s", quote_id, format)
        raise HTTPException(500, f"导出 {format.upper()} 失败, 详见服务端日志")

    ascii_filename, utf8_filename = _safe_filenames(quote.quote_no, quote.customer_name, format)
    # filename 走 ASCII fallback (浏览器旧版兼容); filename* 走 RFC 5987 UTF-8
    headers = {
        "Content-Disposition": (
            f'attachment; filename="{ascii_filename}"; '
            f"filename*=UTF-8''{urllib.parse.quote(utf8_filename)}"
        ),
        "Content-Length": str(len(data)),
    }
    return Response(content=data, media_type=_MIME[format], headers=headers)
