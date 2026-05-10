"""报价单 PDF 导出 — Jinja2 渲染 HTML, WeasyPrint 转 PDF.

字体: 系统已装 fonts-noto-cjk + fonts-droid-fallback (见 Dockerfile).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape


_TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


def render_html(ctx: dict[str, Any]) -> str:
    tmpl = _env.get_template("quote_pdf.html.j2")
    # 模板用 q / days / meta / show_costs / gamble / feasibility 5 个顶层变量
    return tmpl.render(
        q=ctx["quote"],
        days=ctx["days"],
        meta=ctx["meta"],
        show_costs=ctx["show_costs"],
        gamble=ctx.get("gamble", {}),
        feasibility=ctx.get("feasibility", {}),
    )


def build_pdf(ctx: dict[str, Any]) -> bytes:
    """渲染并返回 PDF bytes."""
    # 延迟 import — weasyprint 启动有点重, 避免 worker 启动时拖慢
    from weasyprint import HTML

    html_str = render_html(ctx)
    return HTML(string=html_str).write_pdf()
