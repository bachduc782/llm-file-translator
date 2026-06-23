"""
ビルドスクリプト — dist\LLM-Translator\ フォルダを生成する。

使い方:
    python build.py          # アプリファイルのみ更新（packages再利用）
    python build.py --full   # packages含め完全再ビルド
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist" / "LLM-Translator"

APP_FILES = ["ui.py", "config.py"]

APP_DIRS = ["src"]

PACKAGES = [
    "openai",
    "openpyxl",
    "python-docx",
    "rich",
    "json-repair",
    "google-api-python-client",
    "google-auth-httplib2",
    "google-auth-oauthlib",
    "python-dotenv",
]

# NOTE: .bat must be PURE ASCII (no Japanese) and CRLF — cmd.exe reads .bat in the
# OEM codepage, so UTF-8 multibyte chars corrupt parsing. Also never use ( ) in echoed
# text inside an if(...) block — an unescaped ) closes the block early.
RUN_BAT = """\
@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
set PYTHONPATH=%~dp0packages

rem ============================================================
rem  Required Python version - refuse to run on anything else.
rem ============================================================
set "PYVER=3.11"

if not exist logs mkdir logs
set "LOG=logs\\launcher.log"
echo ============================================================>> "%LOG%"
echo [%date% %time%] run.bat start, require Python %PYVER%>> "%LOG%"

set "PYEXE="

rem 1] py launcher, explicit version, resolve real exe path
where py >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%i in ('py -%PYVER% -c "import sys;print(sys.executable)" 2^>nul') do set "CAND=%%i"
    call :try "!CAND!"
    if defined PYEXE goto :run
)

rem 2] common install locations
call :try "%LocalAppData%\\Programs\\Python\\Python311\\python.exe"
if defined PYEXE goto :run
call :try "%ProgramFiles%\\Python311\\python.exe"
if defined PYEXE goto :run
call :try "%ProgramFiles(x86)%\\Python311\\python.exe"
if defined PYEXE goto :run
call :try "C:\\Python311\\python.exe"
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
"%PYEXE%" ui.py %* 2>> "%LOG%"
set "RC=%errorlevel%"
echo [%date% %time%] ui.py exited with code %RC%>> "%LOG%"

if not "%RC%"=="0" (
    echo.
    echo ============================================================
    echo  An error occurred. Exit code %RC%.
    echo  Log: %LOG%
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
"""


def _force_remove(path: Path):
    """読み取り専用ファイルも含めて強制削除（Windows対応）。"""
    def _on_error(func, fpath, _):
        os.chmod(fpath, stat.S_IWRITE)
        func(fpath)
    shutil.rmtree(path, onerror=_on_error)


def step(msg: str):
    print(f"\n>>> {msg}")


def run(*args):
    result = subprocess.run(args)
    if result.returncode != 0:
        print(f"[ERROR] コマンド失敗: {' '.join(str(a) for a in args)}")
        sys.exit(1)


def main():
    full = "--full" in sys.argv

    print("=" * 50)
    print(" LLM File Translator ビルド")
    print("=" * 50)
    print(f"Python : {sys.executable}")
    print(f"出力先 : {DIST}")
    print(f"モード : {'完全再ビルド' if full else 'アプリのみ更新 (--full で完全再ビルド)'}")

    packages_dir = DIST / "packages"

    if full:
        step("旧ビルドを削除中...")
        if DIST.exists():
            _force_remove(DIST)
        packages_dir.mkdir(parents=True)

    DIST.mkdir(parents=True, exist_ok=True)
    packages_dir.mkdir(exist_ok=True)

    step("パッケージをインストール中 (未インストール分のみ)...")
    run(
        sys.executable, "-m", "pip", "install",
        *PACKAGES,
        "--target", str(packages_dir),
        "--no-warn-script-location", "-q",
    )

    step("アプリファイルをコピー中...")
    for name in APP_FILES:
        src = ROOT / name
        if not src.exists():
            print(f"[ERROR] ファイルが見つかりません: {src}")
            sys.exit(1)
        shutil.copy2(src, DIST / name)
        print(f"  コピー: {name}")

    for dir_name in APP_DIRS:
        src_dir = ROOT / dir_name
        dst_dir = DIST / dir_name
        if not src_dir.exists():
            print(f"[ERROR] ディレクトリが見つかりません: {src_dir}")
            sys.exit(1)
        if dst_dir.exists():
            _force_remove(dst_dir)
        shutil.copytree(src_dir, dst_dir)
        print(f"  コピー: {dir_name}/")

    step("ランチャーを作成中...")
    # .bat は ASCII + CRLF で書き出す（cmd.exeのコードページ問題を回避）
    (DIST / "run.bat").write_text(RUN_BAT, encoding="ascii", newline="\r\n")

    print("\n" + "=" * 50)
    print(f" 完了: {DIST}")
    print(f" run.bat をダブルクリックして起動")
    print(f" ※ Google Drive機能を使う場合は config/ フォルダを配置してください")
    print("=" * 50)


if __name__ == "__main__":
    main()
