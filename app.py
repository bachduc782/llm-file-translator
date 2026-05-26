"""LLM File Translator — ローカルファイル専用スタンドアロンアプリ。"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

# PyInstallerバンドル時のパス解決
if getattr(sys, "frozen", False):
    _BASE = Path(sys.executable).parent
else:
    _BASE = Path(__file__).parent

sys.path.insert(0, str(_BASE))

import app_config

# ── クラッシュログ ────────────────────────────────────────────────────────────

_LOG_DIR = Path(app_config.log_dir())

def _write_crash(text: str):
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(_LOG_DIR / "crash.log", "a", encoding="utf-8") as f:
        f.write(f"\n[{datetime.now().isoformat()}]\n{text}\n")

def _excepthook(exc_type, exc_val, exc_tb):
    _write_crash("".join(traceback.format_exception(exc_type, exc_val, exc_tb)))
    sys.__excepthook__(exc_type, exc_val, exc_tb)

def _thread_excepthook(args):
    _write_crash("".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))

sys.excepthook       = _excepthook
threading.excepthook = _thread_excepthook

# ── Rich UI ───────────────────────────────────────────────────────────────────

from rich.console import Console
from rich.panel   import Panel
from rich.prompt  import Prompt, Confirm
from rich.table   import Table
from rich import print as rprint

console = Console()

LANGUAGES = [
    "Japanese (日本語)",
    "English (英語)",
    "Vietnamese (ベトナム語)",
    "Chinese (Simplified)",
    "Chinese (Traditional)",
    "Korean (韓国語)",
    "French (フランス語)",
    "German (ドイツ語)",
    "Spanish (スペイン語)",
    "Portuguese (ポルトガル語)",
    "Thai (タイ語)",
    "Indonesian (インドネシア語)",
]


# ── 初回セットアップウィザード ────────────────────────────────────────────────

def _setup_wizard():
    """APIキーと翻訳プロバイダーを設定する。"""
    console.print(Panel(
        "[bold cyan]LLM File Translator — 初回セットアップ[/bold cyan]\n"
        "翻訳に使用するLLMプロバイダーを設定します。",
        expand=False,
    ))

    providers = list(app_config.PROVIDERS.keys())
    console.print("\n利用可能なプロバイダー:")
    for i, p in enumerate(providers, 1):
        label = app_config.PROVIDERS[p]["label"]
        console.print(f"  [bold]{i}.[/bold] {label}")

    while True:
        choice = Prompt.ask("プロバイダーを選択", choices=[str(i) for i in range(1, len(providers) + 1)])
        provider = providers[int(choice) - 1]
        break

    app_config.set_active_provider(provider)

    label = app_config.PROVIDERS[provider]["label"]
    current_key = app_config.get_api_key(provider)
    masked = (current_key[:4] + "****" + current_key[-4:]) if len(current_key) > 8 else ""
    prompt_key = f"\n[bold]{label}[/bold] APIキー"
    if masked:
        prompt_key += f" [dim](現在: {masked}、変更しない場合はEnter)[/dim]"
    api_key = Prompt.ask(prompt_key, default=current_key)
    if api_key.strip():
        app_config.set_api_key(provider, api_key.strip())

    models = app_config.PROVIDERS[provider]["models"]
    console.print(f"\n利用可能なモデル ({label}):")
    for i, m in enumerate(models, 1):
        console.print(f"  [bold]{i}.[/bold] {m}")
    console.print(f"  [bold]{len(models) + 1}.[/bold] [dim]その他（直接入力）[/dim]")

    current_model = app_config.get_model(provider)
    try:
        default_idx = str(models.index(current_model) + 1)
    except ValueError:
        default_idx = str(len(models) + 1)

    model_choice = Prompt.ask(
        "モデルを選択",
        choices=[str(i) for i in range(1, len(models) + 2)],
        default=default_idx,
    )
    if int(model_choice) <= len(models):
        selected_model = models[int(model_choice) - 1]
    else:
        selected_model = Prompt.ask(
            "モデルIDを入力",
            default=current_model,
        ).strip()

    app_config.set_model(provider, selected_model)
    app_config.save()

    console.print(f"\n[green]✓ 設定を保存しました。[/green] モデル: [cyan]{selected_model}[/cyan]")


def _show_settings():
    p    = app_config.get_active_provider()
    info = app_config.PROVIDERS[p]
    key  = app_config.get_api_key(p)
    masked = (key[:4] + "****" + key[-4:]) if len(key) > 8 else "****"

    t = Table(show_header=False, box=None, padding=(0, 1))
    t.add_row("[dim]プロバイダー[/dim]", info["label"])
    t.add_row("[dim]モデル[/dim]",       app_config.get_model(p))
    t.add_row("[dim]APIキー[/dim]",      masked if key else "[red]未設定[/red]")
    t.add_row("[dim]レート制限[/dim]",   f"{info['rate_limit']}回/分")
    console.print(Panel(t, title="現在の設定", expand=False))


# ── Windowsスリープ防止 ───────────────────────────────────────────────────────

_ES_CONTINUOUS      = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001

def _prevent_sleep():
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)

def _allow_sleep():
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)


# ── 翻訳実行 ─────────────────────────────────────────────────────────────────

def _run_translation(file_paths: list[str], target_language: str, sheet_name: str):
    from engine import translate_local_files

    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = _LOG_DIR / f"translate_{ts}.log"
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_f   = open(log_path, "w", encoding="utf-8")

    def progress(msg: str):
        console.print(f"  {msg}")
        log_f.write(msg + "\n")
        log_f.flush()

    console.print(f"\n[dim]ログ: {log_path}[/dim]")
    _prevent_sleep()
    try:
        results = translate_local_files(
            file_paths, target_language, sheet_name=sheet_name, progress=progress
        )
    except BaseException as e:
        _write_crash(traceback.format_exc())
        console.print(f"\n[red]予期しないエラー: {e}[/red]")
        return
    finally:
        _allow_sleep()
        log_f.close()

    console.print()
    ok   = results["succeeded"]
    fail = results["failed"]
    if ok:
        console.print(f"[green]✓ {ok}件完了[/green]", end="  ")
    if fail:
        console.print(f"[red]✗ {fail}件失敗[/red]", end="")
    console.print()

    for r in results["results"]:
        if r.get("ok"):
            n = (r.get("cells_translated") or r.get("paragraphs_translated")
                 or r.get("lines_translated", 0))
            console.print(f"  [green]✓[/green] {r['clone_name']} ({n}項目翻訳済み)")
        elif r:
            console.print(f"  [red]✗[/red] {r.get('error', '不明なエラー')}")


# ── メインループ ──────────────────────────────────────────────────────────────

def _pick_language() -> str:
    console.print("\n翻訳先言語:")
    for i, lang in enumerate(LANGUAGES, 1):
        console.print(f"  [bold]{i:2}.[/bold] {lang}")
    console.print(f"  [bold] 0.[/bold] その他（直接入力）")
    choice = Prompt.ask("番号を入力", default="1")
    if choice == "0":
        return Prompt.ask("言語名を入力（例: Italian）")
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(LANGUAGES):
            return LANGUAGES[idx]
    except ValueError:
        pass
    return LANGUAGES[0]


def _get_files_from_args() -> list[str]:
    """コマンドライン引数またはドラッグ&ドロップでファイルパスを受け取る。"""
    paths = []
    for arg in sys.argv[1:]:
        p = arg.strip('"').strip("'")
        if os.path.isfile(p):
            paths.append(p)
    return paths


def main():
    console.print(Panel(
        "[bold]LLM File Translator[/bold]  v1.0\n"
        "[dim]Excel / Word / テキストファイルをLLMで翻訳します[/dim]",
        expand=False,
    ))

    # 初回セットアップ
    if not app_config.get_api_key():
        _setup_wizard()
    else:
        _show_settings()

    while True:
        console.rule()
        console.print("\n[bold]メニュー[/bold]")
        console.print("  [bold]1.[/bold] ファイルを翻訳")
        console.print("  [bold]2.[/bold] 設定を変更")
        console.print("  [bold]3.[/bold] 終了\n")

        choice = Prompt.ask("選択", choices=["1", "2", "3"], default="1")

        if choice == "3":
            break

        elif choice == "2":
            _setup_wizard()

        elif choice == "1":
            # ドラッグ&ドロップ or 手動入力でファイルを受け取る
            drag_files = _get_files_from_args()
            if drag_files:
                console.print(f"\n[green]{len(drag_files)}件のファイルを検出:[/green]")
                for fp in drag_files:
                    console.print(f"  • {fp}")
                file_paths = drag_files
            else:
                console.print("\nファイルパスをスペース区切りで入力してください。")
                console.print("[dim]ヒント: ファイルをこのウィンドウにドラッグ&ドロップして次回起動するか、パスを直接入力[/dim]")
                raw = Prompt.ask("ファイルパス")
                # クォートで囲まれたパスを分割
                import shlex
                try:
                    parts = shlex.split(raw)
                except ValueError:
                    parts = raw.split()
                file_paths = [p.strip('"').strip("'") for p in parts if p.strip()]
                file_paths = [p for p in file_paths if os.path.isfile(p)]

            if not file_paths:
                console.print("[red]有効なファイルが見つかりませんでした。[/red]")
                continue

            # 未対応形式のチェック
            from engine import SUPPORTED_EXT
            invalid = [p for p in file_paths if Path(p).suffix.lower() not in SUPPORTED_EXT]
            if invalid:
                console.print(f"[yellow]未対応の形式が含まれています (スキップ):[/yellow]")
                for p in invalid:
                    console.print(f"  • {p}")
                file_paths = [p for p in file_paths if p not in invalid]
            if not file_paths:
                continue

            target_language = _pick_language()

            sheet_name = ""
            if any(Path(p).suffix.lower() == ".xlsx" for p in file_paths):
                ans = Prompt.ask(
                    "\nExcelの特定シートのみ翻訳しますか？ (空白=全シート)",
                    default="",
                )
                sheet_name = ans.strip()

            console.print(f"\n[bold]翻訳開始:[/bold] {len(file_paths)}ファイル → {target_language}")
            _run_translation(file_paths, target_language, sheet_name)

    console.print("\n[dim]終了します。[/dim]")


if __name__ == "__main__":
    main()
