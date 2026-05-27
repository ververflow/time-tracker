@echo off
setlocal
cd /d "%~dp0"

REM Uses python/pythonw from PATH. If you have multiple Python installs, set TIMETRACKER_PY
REM to an absolute path before calling: set "TIMETRACKER_PY=C:\path\to\python.exe"
if defined TIMETRACKER_PY (
    set "PY=%TIMETRACKER_PY%"
    set "PYW=%TIMETRACKER_PY:python.exe=pythonw.exe%"
) else (
    set "PY=python"
    set "PYW=pythonw"
)

if "%~1"=="" goto dash
if /i "%~1"=="dashboard" goto dash
if /i "%~1"=="start" goto start
if /i "%~1"=="stop" goto stop
if /i "%~1"=="today" ( "%PY%" dashboard.py --today & goto end )
if /i "%~1"=="week"  ( "%PY%" dashboard.py --week  & goto end )
if /i "%~1"=="all"   ( "%PY%" dashboard.py --all   & goto end )

echo Unknown command: %~1
echo Usage: track [start ^| stop ^| dashboard ^| today ^| week ^| all]
goto end

:start
wscript start-tracker.vbs
echo Tracker started (look for the dot in your system tray).
goto end

:dash
start "" "%PYW%" dashboard.py --serve
ping -n 2 127.0.0.1 >nul
start "" http://localhost:7878/
goto end

:stop
powershell -NoProfile -Command "$py='python.exe','pythonw.exe'; Get-CimInstance Win32_Process | Where-Object { $py -contains $_.Name -and $_.CommandLine -match 'tracker\.py|dashboard\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
echo Stopped tracker and dashboard.
goto end

:end
endlocal
