"""报价导出模块 (v0.5).

公共入口:
- build_export_context(quote, db, user) → dict (按角色裁剪后)
- build_excel(ctx) → bytes
- build_pdf(ctx) → bytes
- build_docx(ctx) → bytes

设计原则:
- agent / viewer 看不到 IDR 成本/利润/赌额(复用 permissions.filter_quote_dict 逻辑)
- 所有名称从 ORM 拉, 不依赖前端塞过来的 label
"""
from .context import build_export_context
from .excel_builder import build_excel
from .pdf_builder import build_pdf
from .docx_builder import build_docx

__all__ = [
    "build_export_context",
    "build_excel",
    "build_pdf",
    "build_docx",
]
