"""bws dev 命令 — 用 --no-server 跳过 uvicorn 阻塞."""
from __future__ import annotations

import sqlite3


def test_dev_no_server_runs_init_and_migrate(bws, tmp_db_url):
    r = bws("dev", "--no-server", "--no-seed", timeout=60)
    assert r.returncode == 0, f"stderr={r.stderr}; stdout={r.stdout}"
    assert "[1/3] db init" in r.stdout
    assert "[2/3] db migrate" in r.stdout
    assert "[3/3] --no-server" in r.stdout

    # 验证两步都真做了: 表建好 + alembic_version 写入
    db_path = tmp_db_url.replace("sqlite:///", "")
    conn = sqlite3.connect(db_path)
    try:
        # init 建表
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "quotes" in tables
        assert "alembic_version" in tables
        # migrate 写 baseline
        rows = conn.execute("SELECT version_num FROM alembic_version").fetchall()
        assert len(rows) == 1 and rows[0][0].startswith("0")
    finally:
        conn.close()


def test_dev_help_lists_in_top_level(bws):
    r = bws("--help")
    assert r.returncode == 0
    assert "dev" in r.stdout
