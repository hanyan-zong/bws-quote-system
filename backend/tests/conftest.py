"""共用 fixtures: 隔离 SQLite + bws 子进程 runner.

每个测试拿到的 BWS_DATABASE_URL 都指向 tmp_path 下的全新 .db, 跑完即销.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent


@dataclass
class CliResult:
    returncode: int
    stdout: str
    stderr: str

    def ok(self) -> bool:
        return self.returncode == 0


@pytest.fixture
def tmp_db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'bws_test.db'}"


@pytest.fixture
def bws(tmp_db_url: str):
    """返回一个 callable: bws('db', 'init', '--no-seed') -> CliResult."""

    def _run(*argv: str, env_extra: dict[str, str] | None = None, timeout: float = 30.0) -> CliResult:
        env = os.environ.copy()
        env["BWS_DATABASE_URL"] = tmp_db_url
        env["PYTHONIOENCODING"] = "utf-8"
        env["BWS_CLI_DEBUG"] = ""
        if env_extra:
            env.update(env_extra)
        proc = subprocess.run(
            [sys.executable, "-m", "app.cli", *argv],
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return CliResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)

    return _run


@pytest.fixture
def seed_quote(bws, tmp_db_url: str):
    """在 tmp DB 塞一条最小 Quote, 返回它的 id.

    bws db init --no-seed 已建表 + 自举 admin; 再 subprocess 跑一段内联 ORM 塞 quote.
    """

    def _seed(quote_no: str = "TEST-CLI-001", **overrides: object) -> int:
        bws("db", "init", "--no-seed")
        # 字段全 ASCII 避免 powershell -c 中文编码坑
        kwargs = {"quote_no": quote_no, "agency_name": "TestAgency", "total_days": 3, "pax_adult": 2}
        kwargs.update(overrides)
        kwargs_repr = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
        code = (
            "from app.database import session_scope\n"
            "from app.models.quotes import Quote\n"
            "with session_scope() as db:\n"
            f"    q = Quote({kwargs_repr})\n"
            "    db.add(q)\n"
            "    db.flush()\n"
            "    print(q.id)\n"
        )
        env = os.environ.copy()
        env["BWS_DATABASE_URL"] = tmp_db_url
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"seed_quote failed: rc={proc.returncode}\nstderr={proc.stderr}")
        return int(proc.stdout.strip())

    return _seed
