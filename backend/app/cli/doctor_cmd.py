"""bws doctor — 环境自检.

针对本仓库反复踩的坑做体检 (详见 [[project_bws_cli]]):
  - pip 半卸载在 site-packages 留 `~*` 残骸 → `bws.exe` 报 ModuleNotFoundError
  - 改 pyproject `version` 没重跑 `pip install -e .` → 装的包与代码版本漂移
  - alembic 落后 / DB 未初始化

默认只读, 不改环境. 加 `--fix` 才会删 `~*` 残骸 (唯一安全可逆的自动修复);
其余问题打印修复命令让用户自己跑 (pip / migrate 影响面大, 不替用户做).

退码: 任一项 FAIL → 1; 只有 WARN/OK → 0.
"""
from __future__ import annotations

import argparse
import shutil
import site
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"

_MARK = {OK: "[ OK ]", WARN: "[WARN]", FAIL: "[FAIL]"}
_DIST_NAME = "bws-quote"


@dataclass
class Check:
    status: str
    title: str
    detail: str = ""
    hint: str = ""  # 修复命令, 打印给用户
    fix: Optional[Callable[[], str]] = None  # 仅 --fix 时调用, 返回结果描述


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("doctor", help="环境自检 (entry-point / 残骸 / 版本 / alembic)")
    p.add_argument("--fix", action="store_true", help="自动删除 site-packages 的 ~* 残骸")
    p.set_defaults(_handler=_cmd_doctor)


def _cmd_doctor(args: argparse.Namespace) -> int:
    checks = [
        _check_python(),
        _check_install(),
        _check_version_sync(),
        _check_residue(),
        _check_db(),
        _check_alembic(),
    ]

    for c in checks:
        print(f"{_MARK[c.status]}  {c.title}: {c.detail}")
        if c.status != OK:
            if args.fix and c.fix is not None:
                print(f"        → 修复中: {c.fix()}")
            elif c.hint:
                print(f"        → 修复: {c.hint}")

    n_fail = sum(1 for c in checks if c.status == FAIL)
    n_warn = sum(1 for c in checks if c.status == WARN)
    print()
    print(f"体检完成: {len(checks) - n_fail - n_warn} OK / {n_warn} WARN / {n_fail} FAIL")
    return 1 if n_fail else 0


def _check_python() -> Check:
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    if v.major == 3 and v.minor == 12:
        return Check(OK, "Python 版本", ver)
    if v.major == 3 and v.minor < 12:
        return Check(FAIL, "Python 版本", f"{ver} — 低于 requires-python>=3.12")
    return Check(WARN, "Python 版本", f"{ver} — 推荐 3.12 (3.13+ 部分 wheel 兼容差)")


def _check_install() -> Check:
    from importlib import metadata

    try:
        dist = metadata.distribution(_DIST_NAME)
    except metadata.PackageNotFoundError:
        return Check(
            FAIL,
            f"包安装 ({_DIST_NAME})",
            "pip 元数据缺失 (未装 / 半卸载残骸)",
            hint=r".venv\Scripts\python.exe -m pip install -e .",
        )

    eps = dist.entry_points
    try:
        matches = list(eps.select(group="console_scripts", name="bws"))
    except AttributeError:  # 老 importlib.metadata 返回普通列表
        matches = [e for e in eps if e.group == "console_scripts" and e.name == "bws"]

    if not matches:
        return Check(
            WARN,
            f"包安装 ({_DIST_NAME})",
            f"v{dist.version} 已装, 但缺 console_scripts:bws (bws.exe 会缺失)",
            hint=r".venv\Scripts\python.exe -m pip install -e .",
        )
    return Check(OK, f"包安装 ({_DIST_NAME})", f"v{dist.version}, bws -> {matches[0].value}")


def _check_version_sync() -> Check:
    declared = _pyproject_version()
    if declared is None:
        return Check(WARN, "版本同步", "读不到 pyproject.toml 的 project.version")

    from importlib import metadata

    try:
        installed = metadata.version(_DIST_NAME)
    except metadata.PackageNotFoundError:
        return Check(
            FAIL,
            "版本同步",
            f"pyproject={declared} 但包未安装",
            hint=r".venv\Scripts\python.exe -m pip install -e .",
        )

    if declared != installed:
        return Check(
            WARN,
            "版本同步",
            f"pyproject={declared} != 已装={installed} (改了 version 没重装)",
            hint=r".venv\Scripts\python.exe -m pip install -e .",
        )
    return Check(OK, "版本同步", f"pyproject == 已装 == {declared}")


def _check_residue() -> Check:
    residue = _find_residue()
    if not residue:
        return Check(OK, "site-packages 残骸", "无 ~* 残留")

    names = ", ".join(p.name for p in residue)

    def _fix() -> str:
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
        return "已删除 " + ", ".join(done)

    return Check(
        WARN,
        "site-packages 残骸",
        f"{len(residue)} 个 ~* 残留 (pip 半卸载): {names}",
        hint="bws doctor --fix",
        fix=_fix,
    )


def _check_db() -> Check:
    from sqlalchemy import inspect

    from ..database import engine

    try:
        tables = set(inspect(engine).get_table_names())
    except Exception as exc:  # noqa: BLE001 — 连不上库就是要报出来
        return Check(FAIL, "数据库", f"无法连接 {engine.url}: {exc}", hint="bws db init")

    missing = {"users", "quotes"} - tables
    if missing:
        return Check(
            WARN,
            "数据库",
            f"{engine.url} — 缺核心表 {sorted(missing)} (未初始化?)",
            hint="bws db init",
        )
    return Check(OK, "数据库", f"{engine.url} — {len(tables)} 张表")


def _check_alembic() -> Check:
    from sqlalchemy import inspect

    from ..config import BACKEND_DIR
    from ..database import engine

    ini = BACKEND_DIR / "alembic.ini"
    if not ini.exists():
        return Check(WARN, "Alembic", f"找不到 {ini}")

    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    cfg = Config(str(ini))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    try:
        head = ScriptDirectory.from_config(cfg).get_current_head()
    except Exception as exc:  # noqa: BLE001
        return Check(WARN, "Alembic", f"读取迁移脚本失败: {exc}")

    if "alembic_version" not in inspect(engine).get_table_names():
        return Check(
            WARN,
            "Alembic",
            f"DB 无 alembic_version 表 (脚本 head={head})",
            hint="bws db migrate",
        )

    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()

    if current == head:
        return Check(OK, "Alembic", f"已是最新 head={head}")
    return Check(
        WARN,
        "Alembic",
        f"DB rev={current} 落后于 head={head}",
        hint="bws db migrate",
    )


def _pyproject_version() -> Optional[str]:
    import tomllib

    from ..config import PROJECT_ROOT

    pyproject = PROJECT_ROOT / "pyproject.toml"
    if not pyproject.exists():
        return None
    try:
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        return data["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return None


def _site_dirs() -> list[Path]:
    dirs: set[Path] = set()
    try:
        for d in site.getsitepackages():
            dirs.add(Path(d))
    except Exception:  # noqa: BLE001 — getsitepackages 在某些嵌入式环境不存在
        pass
    try:
        dirs.add(Path(site.getusersitepackages()))
    except Exception:  # noqa: BLE001
        pass
    try:
        dirs.add(Path(sysconfig.get_paths()["purelib"]))
    except Exception:  # noqa: BLE001
        pass
    return [d for d in dirs if d.exists()]


def _find_residue() -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for d in _site_dirs():
        try:
            entries = list(d.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith("~") and entry not in seen:
                seen.add(entry)
                found.append(entry)
    return found
