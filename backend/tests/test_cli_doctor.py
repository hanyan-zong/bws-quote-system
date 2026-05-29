"""bws doctor 测试 — 子进程黑盒跑整条体检 + 残骸逻辑的 in-process 单测."""
from __future__ import annotations

from pathlib import Path


def test_doctor_runs_against_fresh_db(bws):
    """空 tmp 库 + 真 venv: 各项最多 WARN, 不该有 FAIL → 退码 0."""
    r = bws("doctor")
    assert r.returncode == 0, f"stderr={r.stderr}\nstdout={r.stdout}"
    assert "Python 版本" in r.stdout
    assert "Alembic" in r.stdout
    assert "体检完成" in r.stdout


def test_doctor_healthy_after_init_migrate(bws):
    """init + migrate 后, 数据库 + alembic 两项应当 OK."""
    bws("db", "init", "--no-seed")
    rm = bws("db", "migrate")
    assert rm.returncode == 0, f"migrate failed: {rm.stderr}"

    r = bws("doctor")
    assert r.returncode == 0, f"stderr={r.stderr}\nstdout={r.stdout}"
    # alembic 跟到 head
    assert "已是最新" in r.stdout, r.stdout
    # 数据库行应当是 OK (有核心表)
    assert "[ OK ]  数据库" in r.stdout, r.stdout


def test_doctor_fix_flag_accepted(bws):
    """--fix 能解析且整条跑通 (不断言删了真 venv 的东西, 那是真实副作用)."""
    r = bws("doctor", "--fix")
    assert r.returncode in (0, 1), f"stderr={r.stderr}"
    assert "体检完成" in r.stdout


# ---- in-process 单测: 残骸发现 + --fix 删除, 用 tmp 目录避免碰真 venv ----

def test_find_residue_and_fix(tmp_path: Path, monkeypatch):
    from app.cli import doctor_cmd

    junk_dir = tmp_path / "~ws_quote-0.8.4.dist-info"
    junk_dir.mkdir()
    (junk_dir / "RECORD").write_text("stale", encoding="utf-8")
    good_dir = tmp_path / "app"
    good_dir.mkdir()

    monkeypatch.setattr(doctor_cmd, "_site_dirs", lambda: [tmp_path])

    check = doctor_cmd._check_residue()
    assert check.status == doctor_cmd.WARN
    assert "~ws_quote-0.8.4.dist-info" in check.detail
    assert check.fix is not None

    msg = check.fix()
    assert "~ws_quote-0.8.4.dist-info" in msg
    assert not junk_dir.exists(), "残骸应被删除"
    assert good_dir.exists(), "正常目录不该被动"


def test_no_residue_is_ok(tmp_path: Path, monkeypatch):
    from app.cli import doctor_cmd

    (tmp_path / "app").mkdir()
    monkeypatch.setattr(doctor_cmd, "_site_dirs", lambda: [tmp_path])

    check = doctor_cmd._check_residue()
    assert check.status == doctor_cmd.OK
    assert check.fix is None


def test_python_check_ok_on_312(monkeypatch):
    from app.cli import doctor_cmd

    fake = type("V", (), {"major": 3, "minor": 12, "micro": 9})()
    monkeypatch.setattr(doctor_cmd.sys, "version_info", fake)
    assert doctor_cmd._check_python().status == doctor_cmd.OK

    fake_old = type("V", (), {"major": 3, "minor": 11, "micro": 0})()
    monkeypatch.setattr(doctor_cmd.sys, "version_info", fake_old)
    assert doctor_cmd._check_python().status == doctor_cmd.FAIL

    fake_new = type("V", (), {"major": 3, "minor": 14, "micro": 0})()
    monkeypatch.setattr(doctor_cmd.sys, "version_info", fake_new)
    assert doctor_cmd._check_python().status == doctor_cmd.WARN


def test_pyproject_version_readable():
    from app.cli import doctor_cmd

    v = doctor_cmd._pyproject_version()
    assert v is not None and v.count(".") >= 1, f"got {v!r}"
