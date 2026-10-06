@echo off
setlocal EnableExtensions
REM Starts Route Card Vite frontend (LAN --host) for Scheduled Task / manual use.

set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%..\.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"
set "FRONTEND_DIR=%REPO_ROOT%\frontend"
set "LOG_DIR=%SCRIPT_DIR%logs"
set "LOG_FILE=%LOG_DIR%\frontend.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo.>> "%LOG_FILE%"
echo ===== %DATE% %TIME% starting frontend =====>> "%LOG_FILE%"

where npm >nul 2>&1
if errorlevel 1 (
  echo ERROR: npm not found on PATH for this account.>> "%LOG_FILE%"
  echo ERROR: Install Node.js and ensure npm is on PATH for the task user.
  exit /b 1
)

cd /d "%FRONTEND_DIR%"
if errorlevel 1 (
  echo ERROR: cannot cd to "%FRONTEND_DIR%">> "%LOG_FILE%"
  exit /b 1
)

if not exist "%FRONTEND_DIR%\node_modules\" (
  echo ERROR: frontend\node_modules missing — run npm install first.>> "%LOG_FILE%"
  exit /b 1
)

REM Prefer production build when dist exists; else Vite dev server.
if exist "%FRONTEND_DIR%\dist\index.html" (
  echo Using frontend\dist via vite preview>> "%LOG_FILE%"
  call npx --yes vite preview --host --port 5174 >> "%LOG_FILE%" 2>&1
) else (
  echo frontend\dist missing — npm run dev>> "%LOG_FILE%"
  call npm run dev >> "%LOG_FILE%" 2>&1
)

echo ===== %DATE% %TIME% frontend exited code %ERRORLEVEL% =====>> "%LOG_FILE%"
exit /b %ERRORLEVEL%
