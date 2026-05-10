"""全局配置 — 通过环境变量覆盖默认值."""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
UPLOAD_DIR = PROJECT_ROOT / "uploads"
LOG_DIR = PROJECT_ROOT / "logs"
DATA_DIR = BACKEND_DIR / "data"

for d in (UPLOAD_DIR, LOG_DIR, DATA_DIR):
    d.mkdir(parents=True, exist_ok=True)


class Settings:
    """运行期配置. 通过环境变量调整."""

    # ---- DB ----
    database_url: str = os.getenv(
        "BWS_DATABASE_URL",
        f"sqlite:///{DATA_DIR / 'bws_quote.db'}",
    )

    # ---- 登录账号 + 口令 (v0.8 起强制启用; 留空也用 admin/admin123 兜底)
    auth_username: str = os.getenv("BWS_AUTH_USERNAME", "") or "admin"
    auth_password: str = os.getenv("BWS_AUTH_PASSWORD", "") or "admin123"
    auth_secret: str = os.getenv("BWS_AUTH_SECRET", "bali-default-secret")
    auth_cookie_name: str = "bws_session"
    auth_session_days: int = 7

    # ---- AI ----
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    anthropic_model: str = os.getenv("BWS_AI_MODEL", "claude-sonnet-4-6")
    ai_max_tokens: int = int(os.getenv("BWS_AI_MAX_TOKENS", "4096"))
    ai_request_timeout_seconds: float = float(os.getenv("BWS_AI_TIMEOUT", "60"))

    # ---- 业务默认值 ----
    default_exchange_rate: float = float(os.getenv("BWS_DEFAULT_RATE", "2300"))  # 1 CNY = 2300 IDR
    default_max_drive_minutes: int = int(os.getenv("BWS_MAX_DRIVE_MIN", "300"))
    default_max_drive_warn_minutes: int = int(os.getenv("BWS_MAX_DRIVE_WARN", "240"))
    default_safety_ratio: float = float(os.getenv("BWS_GAMBLE_SAFETY", "0.7"))
    default_max_loss_ratio: float = float(os.getenv("BWS_MAX_LOSS_RATIO", "0.25"))
    enable_gambling: bool = os.getenv("BWS_ENABLE_GAMBLING", "true").lower() == "true"

    # ---- 路径 ----
    upload_dir: Path = UPLOAD_DIR
    log_dir: Path = LOG_DIR
    frontend_dir: Path = FRONTEND_DIR

    # ---- 服务 ----
    # 含 cookie 的请求需要明确域名,不能用 "*"
    cors_origins: list[str] = [
        o.strip() for o in os.getenv(
            "BWS_CORS_ORIGINS",
            "http://localhost:8000,http://127.0.0.1:8000",
        ).split(",") if o.strip()
    ]
    api_prefix: str = "/api/v1"

    @property
    def ai_available(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def auth_required(self) -> bool:
        # v0.8 起永远 True. 用户系统是必须的, 不再支持"关闭口令门"
        return True


settings = Settings()
