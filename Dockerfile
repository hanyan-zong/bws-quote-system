# BWS 预报价系统 · 后端 + 前端单镜像
# 多阶段构建: builder 装依赖, runtime 仅含运行所需

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    BWS_DATABASE_URL=sqlite:////app/backend/data/bws_quote.db

# 系统依赖:
#   - WeasyPrint 需要 cairo/pango/gdk-pixbuf
#   - pdfplumber 需要 libtiff/libjpeg (PDF 图像抽取)
#   - 字体: 中文 fallback (DroidSansFallback) + Noto CJK
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libcairo2 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libgdk-pixbuf-2.0-0 \
        libffi-dev \
        libjpeg-dev \
        libpq-dev \
        fonts-noto-cjk \
        fonts-droid-fallback \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖 (利用 layer cache)
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# 复制应用代码
COPY backend /app/backend
COPY frontend /app/frontend
COPY scripts /app/scripts
COPY docs /app/docs
COPY README.md /app/

# 创建运行时所需目录
RUN mkdir -p /app/backend/data /app/uploads /app/logs

# 健康检查 — uvicorn 起来 + DB 初始化完成
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

EXPOSE 8000

# 入口脚本: 先 init_db (幂等) 再起 uvicorn
COPY <<'EOF' /app/entrypoint.sh
#!/bin/bash
set -e

echo "==> [1/2] 初始化数据库 (幂等)..."
cd /app
python scripts/init_db.py || echo "    (DB 已存在, 跳过 seed)"

echo "==> [2/2] 启动 uvicorn..."
echo "   API 文档: http://localhost:8000/docs"
echo "   思维导图: http://localhost:8000/mindmap"
echo "   AI: ${ANTHROPIC_API_KEY:+已配置 ✓}${ANTHROPIC_API_KEY:-MOCK 模式}"

cd /app/backend
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
EOF
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
