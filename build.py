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

RUN_BAT = """\
@echo off
cd /d "%~dp0"
set PYTHONPATH=%~dp0packages

:: py launcher で 3.11 を優先、なければ python を使用
where py >nul 2>&1
if not errorlevel 1 (
    py -3.11 ui.py %*
) else (
    python ui.py %*
)
if errorlevel 1 pause
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
    (DIST / "run.bat").write_text(RUN_BAT, encoding="utf-8")

    print("\n" + "=" * 50)
    print(f" 完了: {DIST}")
    print(f" run.bat をダブルクリックして起動")
    print(f" ※ Google Drive機能を使う場合は config/ フォルダを配置してください")
    print("=" * 50)


if __name__ == "__main__":
    main()
