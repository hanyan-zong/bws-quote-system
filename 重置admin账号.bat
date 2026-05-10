@echo off
chcp 65001 >nul
setlocal
title BWS - 紧急重置 admin 账号

cd /d "%~dp0"

echo.
echo ============================================================
echo   BWS - 紧急重置 admin 账号
echo   作用: 解锁 admin + 把密码重置为 admin123
echo ============================================================
echo.

REM 检查容器是否在跑
docker ps --filter "name=bws-quote" --format "{{.Names}}" | findstr "bws-quote" >nul
if errorlevel 1 (
  echo [错误] bws-quote 容器没在跑
  echo 先双击 一键启动.bat 启动容器
  pause
  exit /b 1
)

echo 正在执行重置 ...
docker exec bws-quote python -c "from app.database import SessionLocal; from app import models; from app.routers.auth import _hash_password; db = SessionLocal(); u = db.query(models.User).filter_by(username='admin').first(); print('admin not found') if not u else (setattr(u, 'locked_until', None), setattr(u, 'failed_login_count', 0), setattr(u, 'password_hash', _hash_password('admin123')), setattr(u, 'status', 'active'), db.commit(), print('OK admin reset to admin/admin123, unlocked'))"

if errorlevel 1 (
  echo.
  echo [错误] 重置失败, 看上面的错误信息
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   ✓ 完成! 现在可以用以下账号登录:
echo.
echo     用户名: admin
echo     密  码: admin123
echo.
echo   登录后请立即在 设置 -^> 账号管理 里改密码
echo ============================================================
echo.
pause
endlocal
