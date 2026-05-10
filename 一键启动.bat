@echo off
chcp 65001 >nul
REM ============================================================
REM  BWS 预报价系统 · 一键启动 (双击即可运行)
REM  自动定位项目目录 / 检查 Docker / 启动容器 / 打开浏览器
REM ============================================================

setlocal enabledelayedexpansion
title BWS 预报价系统 · 一键启动

REM 自动切到本脚本所在目录(无论你从哪里双击都对)
cd /d "%~dp0"

echo.
echo ============================================================
echo   BWS 预报价系统 - 一键启动
echo   当前目录: %CD%
echo ============================================================
echo.

REM === Step 1: 验证项目结构 ===
if not exist "docker-compose.yml" (
  echo [错误] 当前目录没有 docker-compose.yml
  echo 请确认这个 .bat 文件放在 "预报价系统B端版本" 文件夹根目录
  pause
  exit /b 1
)
echo [1/5] 项目结构 OK ✓

REM === Step 2: 检查 Docker Desktop ===
echo [2/5] 检查 Docker Desktop ...
docker version >nul 2>&1
if errorlevel 1 (
  echo.
  echo [错误] Docker Desktop 没启动或没装
  echo 请先启动 Docker Desktop ^(任务栏右下角鲸鱼图标^),等图标变绿再重新双击此文件
  pause
  exit /b 1
)
echo       Docker 已就绪 ✓

REM === Step 3: 检查 .env 是否存在,不存在就从 .env.example 创建 ===
if not exist ".env" (
  echo [3/5] 创建默认 .env 文件 ...
  copy ".env.example" ".env" >nul
  echo       已生成 .env ^(无密码模式,任何人可访问^)
) else (
  echo [3/5] .env 已存在 ✓
)

REM === Step 4: 启动容器 ===
echo [4/5] 启动 Docker 容器 ^(首次构建约 5-10 分钟,后续秒起^) ...
echo.
docker compose up -d --build
if errorlevel 1 (
  echo.
  echo [错误] docker compose 启动失败,看上面的错误信息
  pause
  exit /b 1
)
echo.
echo       容器已启动 ✓

REM === Step 5: 等服务就绪 + 打开浏览器 ===
echo [5/5] 等待服务就绪 ...
set /a TRY=0
:wait_loop
set /a TRY+=1
if %TRY% gtr 30 (
  echo.
  echo [警告] 等了 60 秒服务还没就绪,但容器已启动
  echo 你可以试试手动打开 http://localhost:8000 看看
  goto open_browser
)
curl -s -o nul -w "" http://localhost:8000/api/v1/health 2>nul
if errorlevel 1 (
  timeout /t 2 /nobreak >nul
  goto wait_loop
)

echo       服务已就绪 ✓ ^(用了 %TRY% × 2 秒^)

:open_browser
echo.
echo ============================================================
echo   ✅ 启动成功!
echo   前端面板:  http://localhost:8000
echo   API 文档:  http://localhost:8000/docs
echo   思维导图:  http://localhost:8000/mindmap
echo ============================================================
echo.
echo 正在自动打开浏览器 ...
start "" http://localhost:8000

echo.
echo === 实用命令 ===
echo   看实时日志:    docker compose logs -f bws-quote
echo   停止服务:      docker compose down
echo   重启服务:      docker compose restart bws-quote
echo.
pause
endlocal
