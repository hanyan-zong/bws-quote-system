"""bws server — 后端服务启动/状态/停止."""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

from ..config import PROJECT_ROOT
from ._common import BusinessError


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("server", help="后端服务运维")
    sub = p.add_subparsers(dest="action", metavar="<action>", required=True)

    p_start = sub.add_parser("start", help="启动 uvicorn (前台)")
    p_start.add_argument("--host", default="0.0.0.0")
    p_start.add_argument("--port", type=int, default=8000)
    p_start.add_argument("--no-reload", action="store_true", help="关闭 --reload (生产模式)")
    p_start.set_defaults(_handler=_cmd_start)

    p_status = sub.add_parser("status", help="探活 /api/v1/health")
    p_status.add_argument("--host", default="127.0.0.1")
    p_status.add_argument("--port", type=int, default=8000)
    p_status.set_defaults(_handler=_cmd_status)

    p_stop = sub.add_parser("stop", help="结束监听指定端口的进程 (Windows: netstat + taskkill)")
    p_stop.add_argument("--port", type=int, default=8000)
    p_stop.add_argument("--yes", action="store_true", help="跳过确认")
    p_stop.set_defaults(_handler=_cmd_stop)


def _cmd_start(args: argparse.Namespace) -> int:
    if _port_in_use(args.host if args.host != "0.0.0.0" else "127.0.0.1", args.port):
        raise BusinessError(
            f"端口 {args.port} 已被占用 — 服务可能已在运行 (bws server status 验证)"
        )
    cmd = [
        sys.executable, "-m", "uvicorn", "app.main:app",
        "--host", args.host, "--port", str(args.port),
    ]
    if not args.no_reload:
        cmd.append("--reload")
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    backend_dir = PROJECT_ROOT / "backend"
    print(f"启动: {' '.join(cmd)}  (cwd={backend_dir})")
    return subprocess.call(cmd, cwd=str(backend_dir), env=env)


def _cmd_status(args: argparse.Namespace) -> int:
    url = f"http://{args.host}:{args.port}/api/v1/health"
    req = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=3) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        print(f"OK  {url}")
        print(body)
        return 0
    except URLError as e:
        raise BusinessError(f"不可达 {url} → {e}")


def _cmd_stop(args: argparse.Namespace) -> int:
    pids = _find_pids_listening(args.port)
    if not pids:
        print(f"没有进程在监听 :{args.port}")
        return 0
    print(f"监听 :{args.port} 的进程 PID: {', '.join(str(p) for p in pids)}")
    if not args.yes:
        from ._common import confirm
        if not confirm("结束这些进程?"):
            print("已取消")
            return 0
    rc_total = 0
    for pid in pids:
        rc = subprocess.call(["taskkill", "/PID", str(pid), "/F"])
        rc_total = rc_total or rc
    return rc_total


def _port_in_use(host: str, port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def _find_pids_listening(port: int) -> list[int]:
    """Windows: 解析 netstat -ano 找 LISTENING + :port 的 PID."""
    try:
        out = subprocess.check_output(["netstat", "-ano"], text=True, errors="replace")
    except (OSError, subprocess.CalledProcessError):
        return []
    pids: set[int] = set()
    needle = f":{port}"
    for line in out.splitlines():
        if "LISTENING" not in line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        local = parts[1]
        if not local.endswith(needle):
            continue
        try:
            pids.add(int(parts[-1]))
        except ValueError:
            pass
    return sorted(pids)
