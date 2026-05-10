@echo off
REM BWS 预报价系统启动 (Windows)
cd /d "%~dp0\.."
echo [1/3] 检查依赖...
pip install -q -r backend\requirements.txt
echo [2/3] 初始化数据库...
python scripts\init_db.py
echo [3/3] 启动后端 (http://localhost:8000) ...
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
