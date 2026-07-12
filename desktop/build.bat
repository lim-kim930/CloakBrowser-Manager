@echo off
setlocal
rem One-shot packaging script for the Windows desktop client.
rem Usage: desktop\build.bat  (works from any cwd; anchors itself to the repo root)
rem Steps: pip deps -> pnpm frontend build -> PyInstaller.
rem Output: dist\CloakBrowserManager\CloakBrowserManager.exe

cd /d "%~dp0.."

set "PY=backend\.venv\Scripts\python.exe"
set "PYINSTALLER=backend\.venv\Scripts\pyinstaller.exe"

if not exist "%PY%" (
    echo [ERROR] %PY% not found. Create the venv first: python -m venv backend\.venv
    exit /b 1
)

where pnpm >nul 2>nul
if errorlevel 1 (
    echo [ERROR] pnpm not found on PATH.
    exit /b 1
)

echo === [1/4] Install backend deps ===
"%PY%" -m pip install -r backend\requirements.txt || goto :fail

echo === [2/4] Install desktop deps ===
"%PY%" -m pip install -r desktop\requirements.txt || goto :fail

echo === [3/4] Build frontend with pnpm ===
call pnpm -C frontend install || goto :fail
call pnpm -C frontend run build || goto :fail

echo === [4/4] Package with PyInstaller ===
"%PYINSTALLER%" -y desktop\CloakBrowserManager.spec || goto :fail

echo.
echo [OK] dist\CloakBrowserManager\CloakBrowserManager.exe
exit /b 0

:fail
echo.
echo [ERROR] Packaging failed, see output above.
exit /b 1
