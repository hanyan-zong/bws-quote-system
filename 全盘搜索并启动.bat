@echo off
chcp 65001 >nul
title BWS 预报价系统 · 全盘搜索 + 一键启动

echo.
echo ============================================================
echo   BWS 预报价系统 · 智能定位 + 自动启动
echo   适用于:不知道项目在哪里时使用
echo ============================================================
echo.

REM === 候选位置(从最常见到最少见) ===
set "CANDIDATES="
set "CANDIDATES=!CANDIDATES!;%USERPROFILE%\OneDrive\Documents\balijob\预报价系统B端版本"
set "CANDIDATES=!CANDIDATES!;%USERPROFILE%\Documents\balijob\预报价系统B端版本"
set "CANDIDATES=!CANDIDATES!;%USERPROFILE%\Desktop\balijob\预报价系统B端版本"
set "CANDIDATES=!CANDIDATES!;%USERPROFILE%\OneDrive\balijob\预报价系统B端版本"
set "CANDIDATES=!CANDIDATES!;%USERPROFILE%\balijob\预报价系统B端版本"
set "CANDIDATES=!CANDIDATES!;C:\balijob\预报价系统B端版本"
set "CANDIDATES=!CANDIDATES!;D:\balijob\预报价系统B端版本"
set "CANDIDATES=!CANDIDATES!;D:\Documents\balijob\预报价系统B端版本"
set "CANDIDATES=!CANDIDATES!;E:\balijob\预报价系统B端版本"

setlocal enabledelayedexpansion

echo [1/3] 检查常见位置...
set "FOUND="
for %%P in ("%USERPROFILE%\OneDrive\Documents\balijob\预报价系统B端版本" "%USERPROFILE%\Documents\balijob\预报价系统B端版本" "%USERPROFILE%\Desktop\balijob\预报价系统B端版本" "%USERPROFILE%\OneDrive\balijob\预报价系统B端版本" "%USERPROFILE%\balijob\预报价系统B端版本" "C:\balijob\预报价系统B端版本" "D:\balijob\预报价系统B端版本") do (
  if exist "%%~P\docker-compose.yml" (
    set "FOUND=%%~P"
    echo       命中: %%~P
    goto found
  )
)

echo       常见位置都没找到,开始全盘 C/D 搜索 ^(可能 1-2 分钟^)...
echo.

REM 用 PowerShell 全盘搜
for /f "delims=" %%R in ('powershell -NoProfile -Command "Get-ChildItem -Path C:\Users, D:\, E:\ -Filter '预报价系统B端版本' -Directory -Recurse -ErrorAction SilentlyContinue | Where-Object { Test-Path (Join-Path $_.FullName 'docker-compose.yml') } | Select-Object -ExpandProperty FullName -First 1"') do (
  set "FOUND=%%R"
)

if not defined FOUND (
  echo.
  echo [错误] 全盘没找到 "预报价系统B端版本" 文件夹 ^(含 docker-compose.yml^)
  echo 请确认你已下载/解压项目,或手动告诉我路径
  pause
  exit /b 1
)

:found
echo.
echo [2/3] 找到项目: !FOUND!
cd /d "!FOUND!"

echo.
echo [3/3] 启动一键启动脚本 ...
echo.
call "一键启动.bat"
endlocal
