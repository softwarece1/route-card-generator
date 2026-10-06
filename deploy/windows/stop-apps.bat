@echo off
setlocal EnableExtensions
REM Stops processes listening on Route Card ports (backend 8008, frontend 5174).

set "SCRIPT_DIR=%~dp0"
set "LOG_DIR=%SCRIPT_DIR%logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "LOG_FILE=%LOG_DIR%\stop-apps.log"

echo.>> "%LOG_FILE%"
echo ===== %DATE% %TIME% stop-apps =====>> "%LOG_FILE%"

call :KillPort 8008
call :KillPort 5174

echo Done.>> "%LOG_FILE%"
echo Stopped listeners on 8008 and 5174 (if any).
exit /b 0

:KillPort
set "PORT=%~1"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
  echo Killing PID %%P on port %PORT%>> "%LOG_FILE%"
  taskkill /F /PID %%P >nul 2>&1
)
exit /b 0
