"""
ビルドスクリプト — dist\LLM-Translator\ フォルダを生成する。

使い方:
    python build.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist" / "LLM-Translator"

APP_FILES = ["app.py", "engine.py", "app_config.py"]

PACKAGES = [
    "openai",
    "openpyxl",
    "python-docx",
    "rich",
    "json-repair",
]

RUN_BAT = """\
@echo off
cd /d "%~dp0"
set PYTHONPATH=%~dp0packages
python app.py %*
if errorlevel 1 pause
"""


def step(msg: str):
    print(f"\n>>> {msg}")


def run(*args, **kwargs):
    result = subprocess.run(args, **kwargs)
    if result.returncode != 0:
        print(f"[ERROR] コマンド失敗: {' '.join(str(a) for a in args)}")
        sys.exit(1)


def main():
    print("=" * 50)
    print(" LLM File Translator ビルド")
    print("=" * 50)
    print(f"Python: {sys.executable}")
    print(f"出力先: {DIST}")

    step("旧ビルドを削除中...")
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "packages").mkdir(parents=True)

    step("パッケージをインストール中...")
    run(
        sys.executable, "-m", "pip", "install",
        *PACKAGES,
        "--target", str(DIST / "packages"),
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

    step("ランチャーを作成中...")
    (DIST / "run.bat").write_text(RUN_BAT, encoding="utf-8")

    print("\n" + "=" * 50)
    print(f" 完了: {DIST}")
    print(f" run.bat をダブルクリックして起動")
    print("=" * 50)


if __name__ == "__main__":
    main()
