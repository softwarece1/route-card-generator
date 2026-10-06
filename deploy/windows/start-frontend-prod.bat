@echo off
setlocal EnableExtensions
REM Serves production frontend build (dist) on LAN port 5174.
REM Prefer this after: cd frontend && npm run build

set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%..\.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"
set "FRONTEND_DIR=%REPO_ROOT%\frontend"
set "LOG_DIR=%SCRIPT_DIR%logs"
set "LOG_FILE=%LOG_DIR%\frontend.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo.>> "%LOG_FILE%"
echo ===== %DATE% %TIME% starting frontend (prod preview) =====>> "%LOG_FILE%"

where npm >nul 2>&1
if errorlevel 1 (
  echo ERROR: npm not found on PATH for this account.>> "%LOG_FILE%"
  exit /b 1
)

cd /d "%FRONTEND_DIR%"
if errorlevel 1 (
  echo ERROR: cannot cd to "%FRONTEND_DIR%">> "%LOG_FILE%"
  exit /b 1
)

if not exist "%FRONTEND_DIR%\dist\index.html" (
  echo ERROR: frontend\dist missing — run npm run build first.>> "%LOG_FILE%"
  echo Falling back to start-frontend.bat (dev)...>> "%LOG_FILE%"
  call "%SCRIPT_DIR%start-frontend.bat"
  exit /b %ERRORLEVEL%
)

REM vite preview uses vite.config.js proxy for /api
call npx --yes vite preview --host --port 5174 >> "%LOG_FILE%" 2>&1

echo ===== %DATE% %TIME% frontend prod exited code %ERRORLEVEL% =====>> "%LOG_FILE%"
exit /b %ERRORLEVEL%
