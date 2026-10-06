@echo off
setlocal EnableExtensions
REM Starts Route Card FastAPI backend (uvicorn) for Scheduled Task / manual use.
REM No --reload (unstable as a background service).

set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%..\.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"
set "BACKEND_DIR=%REPO_ROOT%\backend"
set "LOG_DIR=%SCRIPT_DIR%logs"
set "LOG_FILE=%LOG_DIR%\backend.log"
set "VENV_PY=%BACKEND_DIR%\.venv\Scripts\python.exe"
set "UVICORN=%BACKEND_DIR%\.venv\Scripts\uvicorn.exe"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo.>> "%LOG_FILE%"
echo ===== %DATE% %TIME% starting backend =====>> "%LOG_FILE%"

if not exist "%VENV_PY%" (
  echo ERROR: venv not found at "%VENV_PY%">> "%LOG_FILE%"
  echo ERROR: Create backend\.venv and install requirements first.
  exit /b 1
)

cd /d "%BACKEND_DIR%"
if errorlevel 1 (
  echo ERROR: cannot cd to "%BACKEND_DIR%">> "%LOG_FILE%"
  exit /b 1
)

REM Prefer uvicorn.exe from venv; fall back to python -m uvicorn
if exist "%UVICORN%" (
  "%UVICORN%" app.main:app --host 0.0.0.0 --port 8008 >> "%LOG_FILE%" 2>&1
) else (
  "%VENV_PY%" -m uvicorn app.main:app --host 0.0.0.0 --port 8008 >> "%LOG_FILE%" 2>&1
)

echo ===== %DATE% %TIME% backend exited code %ERRORLEVEL% =====>> "%LOG_FILE%"
exit /b %ERRORLEVEL%
