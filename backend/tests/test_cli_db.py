"""bws db 命令测试 — 使用临时 SQLite, 不污染主库."""
from __future__ import annotations


def test_db_init_no_seed_creates_tables(bws):
    r = bws("db", "init", "--no-seed")
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert "已建表" in r.stdout

    # 建表后 stats 应当能跑且至少看到几张核心表
    r2 = bws("db", "stats")
    assert r2.returncode == 0, f"stderr={r2.stderr}"
    assert "quotes" in r2.stdout
    assert "users" in r2.stdout


def test_db_query_select(bws):
    bws("db", "init", "--no-seed")
    r = bws("db", "query", "SELECT COUNT(*) AS n FROM users")
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert "n" in r.stdout  # 表头存在


def test_db_query_rejects_write(bws):
    """写操作 = 用法错误, 退码 2 (Step 4 起统一)."""
    bws("db", "init", "--no-seed")
    r = bws("db", "query", "INSERT INTO users (username) VALUES ('x')")
    assert r.returncode == 2, f"got {r.returncode}; stderr={r.stderr}"
    assert "拒绝" in r.stderr
    assert "UsageError" in r.stderr


def test_db_migrate_runs_alembic_upgrade(bws, tmp_db_url):
    """`bws db migrate` 真跑 alembic upgrade head 后, alembic_version 表应有一条 baseline."""
    import sqlite3

    bws("db", "init", "--no-seed")
    r = bws("db", "migrate")
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert "已升级到 head" in r.stdout

    # 直查 alembic_version 表
    db_path = tmp_db_url.replace("sqlite:///", "")
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT version_num FROM alembic_version").fetchall()
    finally:
        conn.close()
    assert rows == [("0000_baseline",)], f"unexpected alembic_version rows: {rows}"


def test_db_migrate_idempotent(bws):
    """重复跑 migrate 应当幂等 (head 不变, 不报错)."""
    bws("db", "init", "--no-seed")
    r1 = bws("db", "migrate")
    assert r1.returncode == 0
    r2 = bws("db", "migrate")
    assert r2.returncode == 0, f"second migrate failed: {r2.stderr}"
