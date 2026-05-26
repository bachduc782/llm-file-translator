"""
ビルドスクリプト — dist\LLM-Translator\ フォルダを生成する。

使い方:
    python build.py          # アプリファイルのみ更新（packages再利用）
    python build.py --full   # packages含め完全再ビルド
"""

from __future__ import annotations

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
    has_packages = packages_dir.exists() and any(packages_dir.iterdir())

    if full:
        step("旧ビルドを削除中...")
        if DIST.exists():
            shutil.rmtree(DIST)
        packages_dir.mkdir(parents=True)
        has_packages = False
    else:
        DIST.mkdir(parents=True, exist_ok=True)
        packages_dir.mkdir(exist_ok=True)

    if not has_packages:
        step("パッケージをインストール中...")
        run(
            sys.executable, "-m", "pip", "install",
            *PACKAGES,
            "--target", str(packages_dir),
            "--no-warn-script-location", "-q",
        )
    else:
        step("パッケージはキャッシュ済み — スキップ")

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
