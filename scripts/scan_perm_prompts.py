"""扫描 Claude Code 会话 jsonl,统计 Bash/MCP 工具调用频次,辅助生成权限白名单。

用法:
    .venv/Scripts/python.exe scripts/scan_perm_prompts.py [--top N] [--sessions N]

输出:
    - totals: 每类常见命令出现次数
    - bws.bat / pip / alembic / git / gh / docker 子命令分布
    - 用来手工挑选 `.claude/settings.json` 的 permissions.allow 条目

数据源:
    %USERPROFILE%/.claude/projects/*/*.jsonl (assistant tool_use 节点)

注意:
    - 只统计,不修改 settings;白名单条目仍需人工审核(读/写/代码执行三档)
    - jsonl 路径包含中文目录时,Windows GBK 编码可能在 print 时炸,加了 errors='replace' 兜底
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

TRANSCRIPT_ROOT = Path.home() / ".claude" / "projects"

PATTERNS = {
    "bws.bat": re.compile(r"(?:^|[\s/\\])bws\.bat\s+(\S+)(?:\s+(\S+))?"),
    "pytest": re.compile(r"(?:^|[\s/\\])pytest\b"),
    "pip": re.compile(r"(?:^|[\s/\\])(?:python\.exe|python|python3)\s+-m\s+pip\s+(\S+)"),
    "alembic": re.compile(r"(?:^|[\s/\\])(?:python\.exe|python|python3)\s+-m\s+alembic\s+(\S+)"),
    "uvicorn": re.compile(r"(?:^|[\s/\\])(?:python\.exe|python|python3)\s+-m\s+uvicorn\b"),
    "git": re.compile(r"(?:^|[\s;|&])git\s+(\S+)"),
    "gh": re.compile(r"(?:^|[\s;|&])gh\s+(\S+)"),
    "curl": re.compile(r"(?:^|[\s;|&])curl\b"),
    "docker": re.compile(r"(?:^|[\s;|&])docker\s+(\S+)"),
    "mkdir": re.compile(r"(?:^|[\s;|&])mkdir\b"),
}


def scan(sessions: int) -> tuple[Counter, dict[str, Counter]]:
    jsonl_files = []
    for p in TRANSCRIPT_ROOT.rglob("*.jsonl"):
        if "subagents" in str(p):
            continue
        jsonl_files.append((p.stat().st_mtime, p))
    jsonl_files.sort(reverse=True)
    jsonl_files = [p for _, p in jsonl_files[:sessions]]
    print(f"Scanning {len(jsonl_files)} transcripts", file=sys.stderr)

    totals: Counter = Counter()
    subs: dict[str, Counter] = {k: Counter() for k in PATTERNS}

    for fp in jsonl_files:
        try:
            with open(fp, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg = obj.get("message")
                    if not isinstance(msg, dict) or msg.get("role") != "assistant":
                        continue
                    content = msg.get("content")
                    if not isinstance(content, list):
                        continue
                    for item in content:
                        if not isinstance(item, dict) or item.get("type") != "tool_use":
                            continue
                        if item.get("name") != "Bash":
                            continue
                        cmd = item.get("input", {}).get("command", "") or ""
                        for tag, pat in PATTERNS.items():
                            for m in pat.finditer(cmd):
                                groups = [g for g in m.groups() if g]
                                key = tuple(groups) if groups else ()
                                subs[tag][key] += 1
                                totals[tag] += 1
        except Exception as e:
            print(f"err {fp}: {e}", file=sys.stderr)

    return totals, subs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--sessions", type=int, default=50)
    args = ap.parse_args()

    totals, subs = scan(args.sessions)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=== totals ===")
    for k, v in totals.most_common():
        print(f"{v}\t{k}")
    for tag, c in subs.items():
        if not c:
            continue
        print(f"\n=== {tag} subcommands ===")
        for k, v in c.most_common(args.top):
            print(f"{v}\t{k}")


if __name__ == "__main__":
    main()
