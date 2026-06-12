"""FastAPI 入口."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import init_db
from .routers import (
    admin as admin_router,
    ai_parser,
    auth as auth_router,
    exports as exports_router,
    feasibility,
    gamble,
    quotes,
    resources,
    settings as settings_router,
    templates,
)
from .routers.auth import is_authenticated

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("bws.main")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """启动 / 关闭钩子 (替代废弃的 on_event)."""
    init_db()
    logger.info(
        "BWS 预报价系统已启动 | DB=%s | AI=%s",
        settings.database_url,
        "real" if settings.ai_available else "MOCK",
    )
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="BWS 预报价系统 · B 端",
        version="0.10.0",
        description="面向同业旅行社的智能预报价系统 — 强制账号系统 + 多步注册向导 + 自助审核 + 5 角色权限 + 功能配额 + AI 一键上传行程报价 + 资源库 + 行程组合 + 合理性校验 + 赌自费(铁律+5维度) + 三件套导出 + 反馈回写",
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 关闭浏览器对前端文件的缓存(避免改了 CSS/JS 用户看不到)
    @app.middleware("http")
    async def no_cache_static(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/static/") or path == "/mindmap":
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    # 口令门:除白名单外全部需要登录 cookie
    auth_public_prefixes = (
        "/static",
        "/api/v1/auth/",
        "/api/v1/health",
    )
    auth_public_exact = {"/", "/favicon.ico"}

    @app.middleware("http")
    async def auth_gate(request: Request, call_next):
        if not settings.auth_required:
            return await call_next(request)
        path = request.url.path
        if path in auth_public_exact or any(path.startswith(p) for p in auth_public_prefixes):
            return await call_next(request)
        if is_authenticated(request):
            return await call_next(request)
        return JSONResponse(status_code=401, content={"detail": "未登录"})

    # ---- API ----
    api_prefix = settings.api_prefix
    app.include_router(auth_router.router, prefix=api_prefix)
    app.include_router(resources.router, prefix=api_prefix)
    app.include_router(templates.router, prefix=api_prefix)
    app.include_router(quotes.router, prefix=api_prefix)
    app.include_router(exports_router.router, prefix=api_prefix)  # v0.5: PDF/Excel/Word 导出
    app.include_router(ai_parser.router, prefix=api_prefix)
    app.include_router(feasibility.router, prefix=api_prefix)
    app.include_router(gamble.router, prefix=api_prefix)
    app.include_router(settings_router.router, prefix=api_prefix)
    app.include_router(admin_router.router, prefix=api_prefix)  # v0.4: agencies/users/invitations/erp-sync

    @app.get(api_prefix + "/health")
    def health():
        return {
            "ok": True,
            "version": "0.10.0",
            "version_label": "v0.10.0 · APP 双 token 认证 + quotes 分页 + 房型季节价矩阵",
            "ai_available": settings.ai_available,
            "ai_model": settings.anthropic_model if settings.ai_available else "mock",
        }

    # ---- 静态前端 ----
    frontend_dir = Path(settings.frontend_dir)
    if frontend_dir.exists():
        app.mount("/static", StaticFiles(directory=str(frontend_dir / "static")), name="static")

        @app.get("/")
        def index():
            return FileResponse(frontend_dir / "index.html")

        @app.get("/mindmap")
        def mindmap():
            mm = Path(settings.frontend_dir).parent / "docs" / "思维导图.html"
            if mm.exists():
                return FileResponse(mm)
            return {"error": "mindmap not found"}

    return app


app = create_app()
