@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem ============================================================
rem  Required Python version - refuse to run on anything else.
rem ============================================================
set "PYVER=3.11"
set "VENV_PY=C:\venv\llm-file-translator\Scripts\python.exe"

if not exist logs mkdir logs
set "LOG=logs\launcher.log"
echo ============================================================>> "%LOG%"
echo [%date% %time%] run.bat start, require Python %PYVER%>> "%LOG%"

set "PYEXE="

rem 1] dedicated venv - most reliable
call :try "%VENV_PY%"
if defined PYEXE goto :run

rem 2] py launcher, explicit version, resolve real exe path
where py >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%i in ('py -%PYVER% -c "import sys;print(sys.executable)" 2^>nul') do set "CAND=%%i"
    call :try "!CAND!"
    if defined PYEXE goto :run
)

rem 3] common install locations
call :try "%LocalAppData%\Programs\Python\Python311\python.exe"
if defined PYEXE goto :run
call :try "%ProgramFiles%\Python311\python.exe"
if defined PYEXE goto :run
call :try "%ProgramFiles(x86)%\Python311\python.exe"
if defined PYEXE goto :run
call :try "C:\Python311\python.exe"
if defined PYEXE goto :run

rem not found - do NOT run any other python
echo.
echo ============================================================
echo  ERROR: Python %PYVER% not found.
echo  This app runs ONLY on Python %PYVER%.
echo  Install it from https://www.python.org/downloads/
echo  Log: %LOG%
echo ============================================================
echo [%date% %time%] FATAL: Python %PYVER% not found>> "%LOG%"
pause
exit /b 9009

:run
echo [%date% %time%] using %PYEXE%>> "%LOG%"
rem stderr [Python tracebacks] goes to the log; stdout stays on screen for the UI
"%PYEXE%" ui.py %* 2>> "%LOG%"
set "RC=%errorlevel%"
echo [%date% %time%] ui.py exited with code %RC%>> "%LOG%"

if not "%RC%"=="0" (
    echo.
    echo ============================================================
    echo  An error occurred. Exit code %RC%.
    echo  Log: %LOG%
    echo  --- last error output ---
    echo ============================================================
    powershell -NoProfile -Command "Get-Content '%LOG%' -Tail 25"
    echo ============================================================
    pause
)

endlocal & exit /b %RC%

rem -- subroutine: verify candidate is Python %PYVER%, set PYEXE if it matches --
:try
set "CAND_PATH=%~1"
if "%CAND_PATH%"=="" exit /b 0
if not exist "%CAND_PATH%" exit /b 0
"%CAND_PATH%" -c "import sys;sys.exit(0 if sys.version_info[:2]==tuple(int(x) for x in '%PYVER%'.split('.')) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [%date% %time%] skip wrong-version: %CAND_PATH%>> "%LOG%"
    exit /b 0
)
set "PYEXE=%CAND_PATH%"
echo [%date% %time%] matched Python %PYVER%: %CAND_PATH%>> "%LOG%"
exit /b 0
