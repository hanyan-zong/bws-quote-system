"""bws data 命令的退码测试 — 主要验 BusinessError → 1."""
from __future__ import annotations


def test_export_missing_db_is_business_error(bws):
    """tmp_db_url 指向尚未创建的 .db, export 应当报 BusinessError → 1."""
    r = bws("data", "export")
    assert r.returncode == 1, f"got {r.returncode}; stderr={r.stderr}"
    assert "BusinessError" in r.stderr
    assert "DB 不存在" in r.stderr


def test_backup_missing_db_is_business_error(bws):
    r = bws("data", "backup")
    assert r.returncode == 1, f"got {r.returncode}; stderr={r.stderr}"
    assert "BusinessError" in r.stderr


def test_restore_missing_file_is_business_error(bws):
    r = bws("data", "restore", "no_such_backup.db", "--yes")
    assert r.returncode == 1, f"got {r.returncode}; stderr={r.stderr}"
    assert "BusinessError" in r.stderr
    assert "备份文件不存在" in r.stderr
