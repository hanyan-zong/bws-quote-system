@echo off
REM bws CLI wrapper - auto-activates venv and forwards to bws entry_point
setlocal
set "ROOT=%~dp0"
set "VENV=%ROOT%.venv"
set "PYTHONIOENCODING=utf-8"
if exist "%VENV%\Scripts\bws.exe" (
  "%VENV%\Scripts\bws.exe" %*
) else if exist "%VENV%\Scripts\python.exe" (
  set "PYTHONPATH=%ROOT%backend;%PYTHONPATH%"
  "%VENV%\Scripts\python.exe" -m app.cli %*
) else (
  echo [bws.bat] .venv not found - run: python -m venv .venv ^&^& .venv\Scripts\pip install -e .
  exit /b 1
)
exit /b %ERRORLEVEL%
