"""bws version — 版本号统一管理 + 自动重装.

根治本仓库反复踩的"改了 version 没 pip install -e ."漂移 (详见 [[project_bws_cli]]):

为什么必须自动重装:
    `pip install -e .` (editable) 把 version **烤进包元数据** (*.dist-info/METADATA),
    运行时 `importlib.metadata.version()` 读的是这份元数据, 不是 pyproject.toml.
    所以光改 pyproject 的 version, 不重跑 `pip install -e .`, 已装版本永远是旧的 ——
    doctor 的"版本同步"检查就会一直 WARN. 唯一根治 = 改完版本号自动重装.

为什么散落 8 处要统一改:
    版本号 (当前版) 散在 pyproject / app.__version__ / main.py(FastAPI title+health+label)
    / cli description / index.html(头+脚) 共 8 处. 手改容易漏一两处, 漏了没人报错.
    历史标记 (`# v0.9.3:` 注释 / migration 头 / few-shot 示例) 是"功能引入版本", **不能动**.

命令:
    bws version show              审计 8 处 canonical 位置 + 已装版本是否一致
    bws version bump <part|X.Y.Z> 改 8 处 → pip install -e . → 清 ~* 残骸 → 校验同步
        part = major | minor | patch
        --no-reinstall  只改字符串, 不跑 pip (调试用)
        --no-clean      跳过 site-packages ~* 残骸清理
        --dry-run       只打印将改什么, 不落盘不重装
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ._common import BusinessError, UsageError

_DIST_NAME = "bws-quote"
_SEMVER = r"(\d+\.\d+\.\d+)"


@dataclass
class _Target:
    """一处 canonical 版本位置. patterns 里每个正则必须恰好 1 个捕获组 = 语义版本号."""

    relpath: str
    label: str
    patterns: tuple[str, ...]


# canonical 位置 = "当前版本"标签, bump 时同步涨.
# 注意每个 pattern 都带足够上下文锚定, 不会误伤 `# v0.9.3:` 这类历史标记注释.
_TARGETS: list[_Target] = [
    _Target("pyproject.toml", "pyproject.project.version", (r'(?m)^version = "' + _SEMVER + r'"',)),
    _Target("backend/app/__init__.py", "app.__version__", (r'__version__ = "' + _SEMVER + r'"',)),
    _Target(
        "backend/app/main.py",
        "main.py (FastAPI title / health / label)",
        (
            r'version="' + _SEMVER + r'"',            # FastAPI(version="x")
            r'"version": "' + _SEMVER + r'"',          # health endpoint
            r'"version_label": "v' + _SEMVER,          # health label — 只替 vX.Y.Z, 后面描述不动
        ),
    ),
    _Target("backend/app/cli/__init__.py", "cli description", (r'命令行 \(v' + _SEMVER + r'\)',)),
    _Target(
        "frontend/index.html",
        "index.html (header + footer)",
        (
            r'<div class="sub">v' + _SEMVER,
            r'预报价系统 v' + _SEMVER,
        ),
    ),
]


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("version", help="版本号统一管理 + 自动重装 (根治漂移)")
    sub = p.add_subparsers(dest="action", metavar="<action>", required=True)

    sub.add_parser("show", help="审计 8 处 canonical 位置 + 已装版本是否一致").set_defaults(
        _handler=_cmd_show
    )

    pb = sub.add_parser("bump", help="改版本号 8 处 → pip install -e . → 清残骸 → 校验")
    pb.add_argument("part", help="major | minor | patch | 或显式 X.Y.Z")
    pb.add_argument("--no-reinstall", action="store_true", help="只改字符串, 不跑 pip install -e .")
    pb.add_argument("--no-clean", action="store_true", help="跳过 site-packages ~* 残骸清理")
    pb.add_argument("--dry-run", action="store_true", help="只打印将改什么, 不落盘不重装")
    pb.set_defaults(_handler=_cmd_bump)


# ---------------------------------------------------------------- show

def _cmd_show(args: argparse.Namespace) -> int:
    from ..config import PROJECT_ROOT

    declared = _declared_version()
    installed = _installed_version()

    print(f"pyproject 声明版本: {declared or '(读不到)'}")
    print(f"已装包版本       : {installed or '(未安装 / 半卸载残骸)'}")
    if declared and installed and declared != installed:
        print("  ⚠ 声明 != 已装 — 改了 version 没重装, 跑 `bws version bump <X.Y.Z> --no-reinstall` 后再 pip, 或直接 `pip install -e .`")
    print()
    print("canonical 位置审计:")

    all_versions: set[str] = set()
    any_missing = False
    for t in _TARGETS:
        hits = _scan_target(PROJECT_ROOT, t)
        if hits is None:
            print(f"  [缺文件] {t.label}: {t.relpath}")
            any_missing = True
            continue
        if not hits:
            print(f"  [无匹配] {t.label}: {t.relpath} — pattern 失配, 位置可能已改名")
            any_missing = True
            continue
        versions = {v for v, _ in hits}
        all_versions |= versions
        shown = ", ".join(sorted(versions))
        flag = "" if len(versions) == 1 else "  ⚠ 同文件内不一致"
        print(f"  [{len(hits):>2} 处] {t.label}: {shown}{flag}")

    print()
    if installed:
        all_versions.add(installed)
    if len(all_versions) == 1 and not any_missing:
        print(f"✓ 全部一致: {next(iter(all_versions))}")
        return 0
    print(f"⚠ 版本不统一, 出现: {', '.join(sorted(all_versions))} — 跑 `bws version bump <目标版本>` 一键对齐")
    return 1


# ---------------------------------------------------------------- bump

def _cmd_bump(args: argparse.Namespace) -> int:
    from ..config import PROJECT_ROOT

    current = _declared_version()
    if current is None:
        raise BusinessError("读不到 pyproject.toml 的 project.version, 无法确定当前版本")

    new = _compute_new_version(current, args.part)
    if new == current and args.part in {"major", "minor", "patch"}:
        raise BusinessError(f"算出的新版本与当前一致 ({current}), 不应发生")
    print(f"版本: {current} → {new}")
    if args.dry_run:
        print("(--dry-run: 以下为将改动的位置, 不落盘)")

    # 先全部算好新文本 + 留底原文, 不立刻落盘 —— 为重装失败时整体回滚做准备.
    # 半完成的 bump (字符串改了但没重装) 正是本命令要消灭的漂移, 所以 bump 必须原子.
    edits: list[tuple[Path, str, str]] = []  # (path, 原文, 新文)
    total = 0
    for t in _TARGETS:
        path = PROJECT_ROOT / t.relpath
        if not path.exists():
            print(f"  [缺文件] {t.label}: {t.relpath} — 跳过")
            continue
        text = _read_keep_eol(path)
        new_text, n = _replace_target(text, t, new)
        if n == 0:
            print(f"  [无匹配] {t.label}: {t.relpath} — pattern 失配, 没改 (人工核查!)")
            continue
        total += n
        edits.append((path, text, new_text))
        print(f"  [{n} 处] {t.label}: {t.relpath}")

    if total == 0:
        raise BusinessError("一处都没匹配到, 版本号格式可能变了 — 没动任何文件")

    if args.dry_run:
        print(f"\n--dry-run 结束: 共 {total} 处待改, 未落盘, 未重装.")
        return 0

    for path, _old, new_text in edits:
        _write_keep_eol(path, new_text)
    print(f"\n已改 {total} 处字符串.")

    if args.no_reinstall:
        print("--no-reinstall: 跳过 pip install -e . — ⚠ 已装版本仍是旧的, 记得手动重装!")
        return 0

    try:
        _reinstall(PROJECT_ROOT)
    except BusinessError:
        # 重装失败 → 回滚字符串改动, 保持仓库干净的旧版本 (不留半完成漂移)
        for path, old, _new in edits:
            _write_keep_eol(path, old)
        print(f"⚠ 重装失败, 已把 {total} 处字符串回滚到 {current} (仓库保持一致旧版本).")
        raise

    if not args.no_clean:
        _clean_residue()

    # 校验: 重装后 declared 应 == installed == new
    installed = _installed_version()
    if installed != new:
        raise BusinessError(
            f"重装后已装版本={installed} 仍 != 目标={new} — 重装可能没生效, 跑 `bws version show` 排查"
        )
    print(f"✓ 校验通过: pyproject == 已装 == {new}")
    return 0


def _reinstall(project_root: Path) -> None:
    """pip install -e . 刷新包元数据. 离线环境优先用本地 setuptools (--no-build-isolation)."""
    base = [sys.executable, "-m", "pip", "install", "-e", ".", "-q"]

    def _try(extra: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            base + extra,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    print("跑 pip install -e . (重装以刷新包元数据)...")
    proc = _try([])
    if proc.returncode != 0 and _looks_like_network_fail(proc):
        # build isolation 联网抓 setuptools 失败 → 退回用 venv 里已装的 (离线场景)
        print("  联网抓构建依赖失败, 改用本地构建后端 (--no-build-isolation) 重试...")
        proc = _try(["--no-build-isolation"])

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-12:]
        hint = ""
        if _looks_like_network_fail(proc):
            hint = (
                "\n提示: 连不上 pypi 且 venv 缺 setuptools/wheel. 联网后先 "
                "`pip install setuptools wheel`, 再重跑本命令."
            )
        raise BusinessError("pip install -e . 失败:\n" + "\n".join(tail) + hint)
    print("  pip 重装完成.")


def _looks_like_network_fail(proc: subprocess.CompletedProcess) -> bool:
    blob = (proc.stderr or "") + (proc.stdout or "")
    markers = ("ConnectTimeout", "Could not find a version", "No matching distribution",
               "Failed to build", "Connection to pypi", "Temporary failure in name resolution")
    return any(m in blob for m in markers)


def _clean_residue() -> None:
    import shutil

    from .doctor_cmd import _find_residue  # 复用 doctor 的残骸扫描, 单一实现

    residue = _find_residue()
    if not residue:
        print("site-packages 无 ~* 残骸.")
        return
    done: list[str] = []
    for p in residue:
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            done.append(p.name)
        except OSError as exc:
            done.append(f"{p.name}(失败:{exc})")
    print("清理 ~* 残骸: " + ", ".join(done))


# ---------------------------------------------------------------- helpers

def _read_keep_eol(path: Path) -> str:
    """读文件且**保留原始行尾** (newline="") —— 不让 \\r\\n 被翻译成 \\n.

    Path.write_text 在 Windows 会把 \\n 写成 \\r\\n; 若读时已把 \\r\\n 归一成 \\n,
    round-trip 就会污染行尾 (LF→CRLF). 用 newline="" 读写两端都不翻译, 字节级只改版本号.
    """
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def _write_keep_eol(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _declared_version() -> Optional[str]:
    """pyproject.toml 的 project.version — 复用 doctor 的实现, 单一来源."""
    from .doctor_cmd import _pyproject_version

    return _pyproject_version()


def _installed_version() -> Optional[str]:
    from importlib import metadata

    try:
        return metadata.version(_DIST_NAME)
    except metadata.PackageNotFoundError:
        return None


def _compute_new_version(current: str, part: str) -> str:
    m = re.fullmatch(_SEMVER, part)
    if m:  # 显式 X.Y.Z
        return part

    parts = current.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise UsageError(f"当前版本 {current!r} 不是 X.Y.Z 三段数字, 无法 {part} 递增 — 请显式传 X.Y.Z")
    major, minor, patch = (int(p) for p in parts)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise UsageError(f"part 只能是 major|minor|patch 或显式 X.Y.Z, 收到 {part!r}")


def _scan_target(root: Path, t: _Target) -> Optional[list[tuple[str, str]]]:
    """返回 [(version, 整段匹配文本), ...]; 文件不存在返回 None."""
    path = root / t.relpath
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    hits: list[tuple[str, str]] = []
    for pat in t.patterns:
        for m in re.finditer(pat, text):
            hits.append((m.group(1), m.group(0)))
    return hits


def _replace_target(text: str, t: _Target, new: str) -> tuple[str, int]:
    """把 t 的每个 pattern 捕获到的语义版本号替换成 new. 返回 (新文本, 替换处数)."""
    count = 0

    def _sub(m: re.Match) -> str:
        nonlocal count
        count += 1
        whole = m.group(0)
        old_ver = m.group(1)
        # 只替换捕获组那段版本号, 其余 (引号/前后描述) 原样保留
        start = m.start(1) - m.start(0)
        end = m.end(1) - m.start(0)
        return whole[:start] + new + whole[end:]

    for pat in t.patterns:
        text = re.sub(pat, _sub, text)
    return text, count
