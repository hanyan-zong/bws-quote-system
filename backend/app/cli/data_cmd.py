"""bws data — 数据导入/导出/备份/恢复."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from ..config import DATA_DIR, PROJECT_ROOT, settings
from ._common import BusinessError, UsageError


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("data", help="数据导入/导出/备份")
    sub = p.add_subparsers(dest="action", metavar="<action>", required=True)

    p_imp = sub.add_parser("import", help="从母库 xlsx 导入资源 (调用 scripts/import_bali_data.py)")
    p_imp.add_argument("--apply", action="store_true", help="真写入 (默认 dry-run)")
    p_imp.add_argument("--base", default="http://localhost:8000", help="后端 base URL")
    p_imp.add_argument("--only", nargs="+", help="只导入指定类别: attractions hotels vehicles ...")
    p_imp.add_argument("--json", action="store_true", help="只输出 JSON 汇总 (机读, 用于 cron / 上游集成)")
    p_imp.set_defaults(_handler=_cmd_import)

    p_exp = sub.add_parser("export", help="导出 SQLite 为 SQL dump")
    p_exp.add_argument("output", nargs="?", help="输出文件 (默认 ./bws_export_<ts>.sql)")
    p_exp.set_defaults(_handler=_cmd_export)

    p_bak = sub.add_parser("backup", help="复制 bws_quote.db 到 data/backups/")
    p_bak.add_argument("--tag", help="备份标签 (默认时间戳)")
    p_bak.set_defaults(_handler=_cmd_backup)

    p_res = sub.add_parser("restore", help="用备份文件覆盖当前 DB")
    p_res.add_argument("backup_file", help="data/backups/ 下的备份文件名或绝对路径")
    p_res.add_argument("--yes", action="store_true", help="跳过确认")
    p_res.set_defaults(_handler=_cmd_restore)


def _db_path() -> Path:
    """从 settings.database_url 解析 sqlite 文件路径. 非 sqlite 直接拒绝."""
    url = settings.database_url
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise UsageError(
            f"data export/backup/restore 只支持 sqlite — 当前 BWS_DATABASE_URL={url}"
        )
    return Path(url[len(prefix):])


def _backup_dir() -> Path:
    p = DATA_DIR / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _cmd_import(args: argparse.Namespace) -> int:
    script = PROJECT_ROOT / "scripts" / "import_bali_data.py"
    if not script.exists():
        raise BusinessError(f"找不到导入脚本: {script}")
    cmd = [sys.executable, str(script), "--base", args.base]
    if args.apply:
        cmd.append("--apply")
    if args.only:
        cmd.extend(["--only", *args.only])

    if not args.json:
        print(f"运行: {' '.join(cmd)}")
        return subprocess.call(cmd)

    # JSON 模式: 捕获 stdout, 解析汇总块, 打印结构化结果
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    summary = _parse_import_summary(proc.stdout)
    out = {
        "returncode": proc.returncode,
        "apply": bool(args.apply),
        "categories": summary,
    }
    if not summary:
        out["raw_output"] = proc.stdout
    if proc.stderr:
        out["stderr"] = proc.stderr
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return proc.returncode


_SUMMARY_LINE_RE = re.compile(
    r"^\s+(\S+)\s*:\s*parsed=\s*(\d+)\s+ok=\s*(\d+)\s+fail=\s*(\d+)\s*$"
)


def _parse_import_summary(stdout: str) -> dict[str, dict[str, int]]:
    """从 import_bali_data.py 的输出里抓最后那块 '汇总:' 表."""
    out: dict[str, dict[str, int]] = {}
    in_block = False
    for line in stdout.splitlines():
        if line.strip().startswith("汇总"):
            in_block = True
            continue
        if not in_block:
            continue
        m = _SUMMARY_LINE_RE.match(line)
        if m:
            kind, parsed, ok, fail = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
            out[kind] = {"parsed": parsed, "ok": ok, "fail": fail}
    return out


def _cmd_export(args: argparse.Namespace) -> int:
    db = _db_path()
    if not db.exists():
        raise BusinessError(f"DB 不存在: {db}")
    out = Path(args.output) if args.output else Path.cwd() / f"bws_export_{_ts()}.sql"
    conn = sqlite3.connect(str(db))
    try:
        with out.open("w", encoding="utf-8") as f:
            for line in conn.iterdump():
                f.write(line + "\n")
    finally:
        conn.close()
    print(f"已导出: {out}  ({out.stat().st_size} bytes)")
    return 0


def _cmd_backup(args: argparse.Namespace) -> int:
    db = _db_path()
    if not db.exists():
        raise BusinessError(f"DB 不存在: {db}")
    tag = args.tag or _ts()
    dest = _backup_dir() / f"bws_quote_{tag}.db"
    shutil.copy2(db, dest)
    print(f"已备份: {dest}  ({dest.stat().st_size} bytes)")
    return 0


def _cmd_restore(args: argparse.Namespace) -> int:
    db = _db_path()
    src = Path(args.backup_file)
    if not src.is_absolute():
        src = _backup_dir() / args.backup_file
    if not src.exists():
        raise BusinessError(f"备份文件不存在: {src}")

    if not args.yes:
        print(f"即将用 {src} 覆盖 {db}")
        from ._common import confirm
        if not confirm("确认?"):
            print("已取消")
            return 0

    if db.exists():
        safety = _backup_dir() / f"bws_quote_pre_restore_{_ts()}.db"
        shutil.copy2(db, safety)
        print(f"  (旧 DB 已自动保存到 {safety})")
    shutil.copy2(src, db)
    print(f"已恢复: {db}")
    return 0


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")
