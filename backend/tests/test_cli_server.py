"""bws server 命令退码测试 — 只测不需要真起 uvicorn 的路径."""
from __future__ import annotations


def test_status_unreachable_is_business_error(bws):
    """对一个肯定不通的端口探活, 应当 BusinessError → 1."""
    # 端口 1 通常无服务在监听; --host 127.0.0.1 避免出网
    r = bws("server", "status", "--host", "127.0.0.1", "--port", "1", timeout=10)
    assert r.returncode == 1, f"got {r.returncode}; stderr={r.stderr}; stdout={r.stdout}"
    assert "BusinessError" in r.stderr
    assert "不可达" in r.stderr


def test_stop_no_process_returns_0(bws):
    """没进程在监听 → 退码 0 (幂等)."""
    # 端口 1 通常没监听; --yes 防止 confirm 阻塞 (反正不会触发)
    r = bws("server", "stop", "--port", "1", "--yes", timeout=10)
    assert r.returncode == 0, f"got {r.returncode}; stderr={r.stderr}"
    assert "没有进程" in r.stdout
