@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title BWS 预报价系统 · 诊断并启动 v0.5

REM 自动切到本脚本所在目录
cd /d "%~dp0"

echo.
echo ============================================================
echo   BWS 预报价系统 - 诊断并启动 (v0.5 导出闭环版)
echo   目录: %CD%
echo ============================================================
echo.

REM ============= Step 1: Docker Desktop =============
echo [1/7] 检查 Docker Desktop ...
docker version >nul 2>&1
if errorlevel 1 (
  echo.
  echo [致命] Docker Desktop 没启动或没装
  echo   解决: 任务栏右下角找鲸鱼图标右键 启动. 等图标变绿后重跑此 .bat
  echo   没装的话去下载: https://www.docker.com/products/docker-desktop
  pause
  exit /b 1
)
echo       OK Docker 已就绪
echo.

REM ============= Step 2: 项目结构 =============
echo [2/7] 检查项目结构 ...
if not exist "docker-compose.yml" (
  echo [致命] 当前目录没 docker-compose.yml
  echo   你可能在错误的目录, 或者解压缺文件
  echo   当前目录: %CD%
  pause
  exit /b 1
)
echo       OK docker-compose.yml 存在
echo.

REM ============= Step 3: .env =============
echo [3/7] 检查 .env ...
if not exist ".env" (
  if exist ".env.example" (
    echo       .env 不存在, 从 .env.example 自动生成
    copy ".env.example" ".env" >nul
  ) else (
    echo       .env 和 .env.example 都不存在, 创建空 .env
    type nul > .env
  )
) else (
  echo       OK .env 已存在
)
echo.

REM ============= Step 4: 看现有容器状态 =============
echo [4/7] 当前容器状态 ...
docker compose ps
echo.

REM ============= Step 5: 看是否需要 rebuild (v0.5 改了 requirements.txt 锁了 pydyf) =============
echo [5/7] 检查镜像是否需要重建 (v0.5 改了 requirements.txt 锁 pydyf==0.10.0) ...
docker images bws-quote --format "{{.Tag}} {{.CreatedSince}}" 2>nul
echo.
set /p REBUILD="    是否重建镜像? 首次启动 / 刚升级到 v0.5 必选 [Y/n]: "
if /i "!REBUILD!"=="" set REBUILD=Y
if /i "!REBUILD!"=="Y" (
  echo       停止旧容器 ...
  docker compose down
  echo       重建镜像 (无缓存, 约 5-10 分钟首次, 之后更快) ...
  docker compose build --no-cache
  if errorlevel 1 (
    echo.
    echo [致命] 镜像构建失败
    echo   常见原因:
    echo     1. Docker Hub 被墙 - Docker Desktop 设置加 registry-mirrors
    echo        参考 docs\今日工作记录_2026-05-08.md "Docker Hub 镜像源" 章节
    echo     2. 磁盘空间不足 - 清掉旧镜像: docker system prune -a
    pause
    exit /b 1
  )
  echo       OK 镜像构建完成
)
echo.

REM ============= Step 6: 启动容器 =============
echo [6/7] 启动容器 ...
docker compose up -d
if errorlevel 1 (
  echo.
  echo [致命] 容器启动失败
  echo   看日志: docker compose logs bws-quote
  pause
  exit /b 1
)
echo       OK 容器已启动
echo.

REM ============= Step 7: 等服务就绪 =============
echo [7/7] 等待服务就绪 ...
set /a TRY=0
:wait_loop
set /a TRY+=1
if %TRY% gtr 45 (
  echo.
  echo [警告] 等了 90 秒服务还没就绪, 但容器已启动. 可能在初始化数据库
  echo   看实时日志: docker compose logs -f bws-quote
  goto open_browser
)
curl -s -o nul -w "" http://localhost:8000/api/v1/health 2>nul
if errorlevel 1 (
  timeout /t 2 /nobreak >nul
  goto wait_loop
)
echo       OK 服务已就绪 (用了 %TRY% × 2 秒)

:open_browser
echo.
echo ============================================================
echo   v0.5 启动成功!
echo.
echo   前端面板:    http://localhost:8000
echo   API 文档:    http://localhost:8000/docs
echo   思维导图:    http://localhost:8000/mindmap
echo.
echo   v0.5 新功能 (在历史 Tab 和 设置 Tab):
echo     - 报价历史 - Excel/PDF/Word 三件套下载
echo     - 报价历史 - 团结束反馈按钮
echo     - 设置页底部 - 策略胜率统计卡
echo ============================================================
echo.

REM 端口监听最终确认
echo === 8000 端口监听状态 ===
netstat -ano | findstr :8000 | findstr LISTENING
echo.

echo 正在自动打开浏览器 ...
start "" http://localhost:8000

echo.
echo === 实用命令 ===
echo   实时日志:        docker compose logs -f bws-quote
echo   停止服务:        docker compose down
echo   重启服务:        docker compose restart bws-quote
echo   进入容器:        docker compose exec bws-quote bash
echo.
pause
endlocal
