"""bws version 测试.

子进程黑盒只跑**只读 / dry-run**路径 (show / bump --dry-run) —— 真 bump 会改真仓库
文件 + pip install -e ., 绝不在测试里跑. 替换逻辑的正确性 (尤其"不误伤历史标记注释")
用 in-process 纯函数单测覆盖, 喂样本文本.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------- 子进程黑盒 (只读 / dry-run)

def test_version_show_all_consistent(bws):
    """show 审计 8 处 canonical 位置, 当前仓库应全部一致 → 退码 0."""
    r = bws("version", "show")
    assert r.returncode == 0, f"stderr={r.stderr}\nstdout={r.stdout}"
    assert "canonical 位置审计" in r.stdout
    assert "全部一致" in r.stdout
    # 8 处来自 5 个 target 文件, label 都该出现
    for label in ("pyproject", "__version__", "main.py", "cli description", "index.html"):
        assert label in r.stdout, f"缺 {label}: {r.stdout}"


def test_version_bump_dry_run_does_not_write(bws):
    """dry-run 列出 8 处待改但不落盘 → 退码 0, 且再 show 仍一致 (没被改)."""
    before = bws("version", "show").stdout
    r = bws("version", "bump", "patch", "--dry-run")
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert "dry-run" in r.stdout
    assert "共 8 处待改" in r.stdout
    assert "未落盘" in r.stdout
    after = bws("version", "show").stdout
    assert before == after, "dry-run 不该改任何文件"


def test_version_bump_rejects_bad_part(bws):
    """既不是 major|minor|patch 也不是合法 X.Y.Z → UsageError 退码 2."""
    r = bws("version", "bump", "1.2", "--dry-run")
    assert r.returncode == 2, f"stdout={r.stdout} stderr={r.stderr}"
    assert "UsageError" in r.stderr


# ---------------------------------------------------------------- 纯函数单测: 版本递增

@pytest.mark.parametrize(
    "current,part,expected",
    [
        ("0.9.3", "patch", "0.9.4"),
        ("0.9.3", "minor", "0.10.0"),
        ("0.9.3", "major", "1.0.0"),
        ("1.2.3", "patch", "1.2.4"),
        ("0.9.3", "2.0.0", "2.0.0"),   # 显式
        ("0.9.3", "0.9.10", "0.9.10"),  # 显式跳号
    ],
)
def test_compute_new_version(current, part, expected):
    from app.cli import version_cmd

    assert version_cmd._compute_new_version(current, part) == expected


def test_compute_new_version_rejects_garbage():
    from app.cli import version_cmd
    from app.cli._common import UsageError

    with pytest.raises(UsageError):
        version_cmd._compute_new_version("0.9.3", "huge")
    with pytest.raises(UsageError):
        version_cmd._compute_new_version("0.9.3", "1.2")  # 不是三段


# ---------------------------------------------------------------- 纯函数单测: 替换不误伤历史标记

def test_replace_target_only_touches_canonical():
    """同一文件里 canonical 版本号要改, 但 `# v0.9.3:` 历史标记注释必须原样保留."""
    from app.cli import version_cmd

    # 模拟 main.py: FastAPI version + health + label 是 canonical; 注释里的 v0.9.3 是历史标记
    sample = (
        '    app = FastAPI(\n'
        '        version="0.9.3",\n'
        '        description="...",\n'
        '    )\n'
        '    # v0.9.3: 这是功能引入版本, 不该被改\n'
        '    return {\n'
        '        "version": "0.9.3",\n'
        '        "version_label": "v0.9.3 · day_type 4 类 + 复制天",\n'
        '    }\n'
    )
    target = next(t for t in version_cmd._TARGETS if t.relpath.endswith("main.py"))
    new_text, n = version_cmd._replace_target(sample, target, "0.9.4")

    assert n == 3, f"应改 3 处 canonical, 实际 {n}"
    assert 'version="0.9.4"' in new_text
    assert '"version": "0.9.4"' in new_text
    assert '"version_label": "v0.9.4 · day_type 4 类 + 复制天"' in new_text  # 描述保留
    assert "# v0.9.3: 这是功能引入版本" in new_text, "历史标记注释被误伤了"


def test_replace_target_pyproject_anchored():
    """pyproject 的 `version = "x"` 改, 但 build-system 的依赖串不该动."""
    from app.cli import version_cmd

    sample = (
        '[build-system]\n'
        'requires = ["setuptools>=68", "wheel"]\n'
        '[project]\n'
        'name = "bws-quote"\n'
        'version = "0.9.3"\n'
        'requires-python = ">=3.12"\n'
    )
    target = next(t for t in version_cmd._TARGETS if t.relpath == "pyproject.toml")
    new_text, n = version_cmd._replace_target(sample, target, "0.9.4")

    assert n == 1
    assert 'version = "0.9.4"' in new_text
    assert 'requires = ["setuptools>=68", "wheel"]' in new_text  # 没动
    assert 'requires-python = ">=3.12"' in new_text


def test_write_keep_eol_preserves_crlf(tmp_path):
    """回归: bump 改版本号不能污染行尾 (LF↔CRLF). 字节级只改版本那几位."""
    from app.cli import version_cmd

    f = tmp_path / "sample.txt"
    # 故意混用 CRLF, 字节写入
    f.write_bytes(b'version = "0.9.3"\r\nname = "x"\r\n')

    text = version_cmd._read_keep_eol(f)
    assert "\r\n" in text, "保真读应保留 CRLF"
    new_text = text.replace("0.9.3", "0.9.4")
    version_cmd._write_keep_eol(f, new_text)

    assert f.read_bytes() == b'version = "0.9.4"\r\nname = "x"\r\n', "除版本号外字节必须一致 (含 CRLF)"


def test_write_keep_eol_preserves_lf(tmp_path):
    """LF 文件 round-trip 后仍是 LF, 不被 Windows 文本模式翻成 CRLF."""
    from app.cli import version_cmd

    f = tmp_path / "sample.txt"
    f.write_bytes(b'__version__ = "0.9.3"\nx = 1\n')

    text = version_cmd._read_keep_eol(f)
    version_cmd._write_keep_eol(f, text.replace("0.9.3", "0.9.4"))

    assert f.read_bytes() == b'__version__ = "0.9.4"\nx = 1\n', "LF 不该被翻成 CRLF"


def test_scan_real_repo_finds_eight_canonical():
    """对真仓库扫描: 5 个 target 文件都在, 共 8 处, 且版本号自洽."""
    from app.config import PROJECT_ROOT
    from app.cli import version_cmd

    total = 0
    versions: set[str] = set()
    for t in version_cmd._TARGETS:
        hits = version_cmd._scan_target(PROJECT_ROOT, t)
        assert hits is not None, f"{t.relpath} 缺文件"
        assert hits, f"{t.label} pattern 全失配 — 位置可能改名了"
        total += len(hits)
        versions |= {v for v, _ in hits}

    assert total == 8, f"canonical 位置应有 8 处, 实际 {total}"
    assert len(versions) == 1, f"真仓库版本号应自洽, 出现多个: {versions}"
