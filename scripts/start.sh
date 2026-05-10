#!/bin/bash
# BWS 预报价系统启动脚本
# 自动处理: 依赖安装 + DB 初始化 + 兼容 FUSE 挂载文件系统

set -e

cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

echo "==> [1/4] 检查依赖..."
pip install -q --break-system-packages -r backend/requirements.txt 2>&1 | tail -3 || true

# 自动选择 DB 路径: 如果默认路径写不了 (FUSE 挂载), 切到 /tmp
DEFAULT_DB="$PROJECT_ROOT/backend/data/bws_quote.db"
mkdir -p "$(dirname "$DEFAULT_DB")"
if ! touch "$DEFAULT_DB.lock_test" 2>/dev/null; then
  echo "   ⚠️  默认 DB 路径不可写, 切换到 /tmp"
  export BWS_DATABASE_URL="sqlite:////tmp/bws_quote.db"
else
  rm -f "$DEFAULT_DB.lock_test"
  # 尝试用 SQLite 真正写一次, 验证支持文件锁
  if ! python3 -c "
import sqlite3
c = sqlite3.connect('$DEFAULT_DB.test')
c.execute('CREATE TABLE IF NOT EXISTS t(x INT)')
c.commit()
c.close()
" 2>/dev/null; then
    echo "   ⚠️  SQLite 文件锁不可用 (FUSE), 切换到 /tmp"
    export BWS_DATABASE_URL="sqlite:////tmp/bws_quote.db"
  fi
  rm -f "$DEFAULT_DB.test"
fi

echo "==> [2/4] DB URL: ${BWS_DATABASE_URL:-默认}"

echo "==> [3/4] 初始化数据库..."
python3 scripts/init_db.py

echo "==> [4/4] 启动后端 (http://localhost:8000) ..."
echo "   API 文档: http://localhost:8000/docs"
echo "   思维导图: http://localhost:8000/mindmap"
echo "   AI: ${ANTHROPIC_API_KEY:+已配置}${ANTHROPIC_API_KEY:-MOCK 模式 (设置 ANTHROPIC_API_KEY 启用真实 AI)}"
echo "   Ctrl+C 停止"
cd backend
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
