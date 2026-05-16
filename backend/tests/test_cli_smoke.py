"""最小烟雾测试 — 确认 bws CLI 能跑起来 + argparse 路径退码正确."""
from __future__ import annotations


def test_version(bws):
    r = bws("--version")
    assert r.returncode == 0
    assert "bws" in r.stdout.lower()


def test_help(bws):
    r = bws("--help")
    assert r.returncode == 0
    assert "<group>" in r.stdout or "quote" in r.stdout


def test_no_args_exits_2(bws):
    """无参数: argparse 因为 group 是 required 应当 exit 2."""
    r = bws()
    assert r.returncode == 2, f"expected 2, got {r.returncode}\nstdout={r.stdout}\nstderr={r.stderr}"


def test_unknown_group_exits_2(bws):
    r = bws("nosuchgroup")
    assert r.returncode == 2


def test_group_without_action_exits_2(bws):
    """`bws quote` 没指定 action: argparse 因为 action 也 required 应当 exit 2."""
    r = bws("quote")
    assert r.returncode == 2
