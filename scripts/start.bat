@echo off
REM BWS Quote System Launcher (Windows) - v0.9
cd /d "%~dp0\.."
echo [1/2] Install Python deps + bws entry point
pip install -q -r backend\requirements.txt
pip install -q -e .
echo [2/2] bws dev (init + alembic migrate + uvicorn on :8000)
bws dev --no-reload --no-seed
