"""LLM File TranslatorのインタラクティブコンソールUI。"""

from __future__ import annotations

import json
import os
import sys

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.text import Text
from rich import box

console = Console()

def _patch_ssl():
    """requestsのSSLをパッチ — Python 3.14の厳格なTLS動作を修正。"""
    import ssl
    import requests
    from requests.adapters import HTTPAdapter

    class _TLSAdapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            ctx = ssl.create_default_context()
            if hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
                ctx.options |= ssl.OP_IGNORE_UNEXPECTED_EOF
            try:
                import certifi
                ctx.load_verify_locations(certifi.where())
            except ImportError:
                pass
            kwargs["ssl_context"] = ctx
            super().init_poolmanager(*args, **kwargs)

    _orig_init = requests.Session.__init__

    def _patched_init(self):
        _orig_init(self)
        self.mount("https://", _TLSAdapter())

    requests.Session.__init__ = _patched_init

_patch_ssl()

TITLE = "[bold cyan]LLM File Translator[/bold cyan]"
VERSION = "v2.0"


# ── ユーティリティ ────────────────────────────────────────────────────────────

def _check_auth() -> bool:
    import config
    return os.path.exists(config.GOOGLE_TOKEN_FILE)


def _check_api_key() -> bool:
    import config
    return bool(config.get_api_key())


def _header():
    import config as _cfg
    console.clear()
    status_auth = "[green]✓ 認証済み[/green]"   if _check_auth()    else "[red]✗ 未認証[/red]"
    status_api  = "[green]✓ APIキー OK[/green]" if _check_api_key() else "[red]✗ APIキー未設定[/red]"
    provider    = _cfg.PROVIDERS[_cfg.get_active_provider()]["label"]
    model       = _cfg.get_model()

    console.print(Panel(
        f"[bold cyan]LLM File Translator[/bold cyan]  [dim]{VERSION}[/dim]\n"
        f"Google OAuth: {status_auth}    LLM: {status_api}  "
        f"[dim]({provider} / {model})[/dim]",
        box=box.DOUBLE_EDGE,
        expand=False,
        padding=(0, 2),
    ))
    console.print()


def _press_enter():
    console.print()
    Prompt.ask("[dim]Enterキーを押して続ける[/dim]", default="")


# ── スクリーン ────────────────────────────────────────────────────────────────

def screen_auth():
    _header()
    console.print(Panel("[bold]Google OAuth 認証[/bold]", style="yellow", expand=False))
    console.print()

    if _check_auth():
        import config
        console.print(f"[green]既存のトークン:[/green] {config.GOOGLE_TOKEN_FILE}")
        if not Confirm.ask("再認証しますか？", default=False):
            return

    console.print("[dim]ブラウザを開いてGoogleにログイン中...[/dim]\n")
    try:
        import auth_setup
        auth_setup.main()
        console.print("\n[bold green]✓ 認証成功！[/bold green]")
    except Exception as e:
        console.print(f"\n[bold red]エラー:[/bold red] {e}")

    _press_enter()


def screen_translate():
    _header()
    console.print(Panel("[bold]Googleファイルを翻訳[/bold]", style="green", expand=False))
    console.print()

    if not _check_auth():
        console.print("[red]Google認証が完了していません。先に認証を行ってください。[/red]")
        _press_enter()
        return

    console.print("[dim]ファイルIDまたはURLを1行ずつ入力。空行で終了。[/dim]")
    file_ids: list[str] = []
    idx = 1
    while True:
        val = Prompt.ask(f"  ファイル {idx}").strip()
        if not val:
            break
        file_ids.append(val)
        idx += 1

    if not file_ids:
        return

    language = Prompt.ask("翻訳先言語", default="Japanese")
    sheet    = Prompt.ask("シート名 [dim]（空白 = 全シート翻訳）[/dim]", default="")

    multi = len(file_ids) > 1
    console.print()
    console.print(
        f"[dim]{'各ファイル' if multi else 'ファイル'}は言語サフィックス付きで複製されます "
        f"（例: [/dim][cyan]-jp[/cyan][dim]） — 元ファイルはそのまま保持。"
        + (f" {len(file_ids)}ファイルを並列処理。[/dim]" if multi else "[/dim]")
    )
    console.print()

    console.rule("[dim]進捗[/dim]")

    from src.tools.translate_google import translate_google_file, translate_google_files
    import time

    t0 = time.monotonic()

    def _fmt_elapsed() -> str:
        s = time.monotonic() - t0
        if s < 60:
            return f"{s:.1f}s"
        return f"{int(s) // 60}m {int(s) % 60}s"

    def _progress(msg: str):
        t_str = _fmt_elapsed()
        is_error = msg.upper().startswith("ERROR") or "failed" in msg.lower()
        if is_error:
            console.print(f"  [red][{t_str}] {msg}[/red]")
        else:
            console.print(f"  [dim][{t_str}][/dim] {msg}")

    try:
        if multi:
            result = translate_google_files(file_ids, language, sheet, _progress)
        else:
            result = translate_google_file(file_ids[0], language, sheet, _progress)

        elapsed = _fmt_elapsed()
        console.rule()

        if "error" in result:
            console.print(f"[bold red]エラー:[/bold red] {result['error']}")
            console.print(f"[dim]処理時間: {elapsed}[/dim]")
        elif multi:
            lines = [
                f"[bold]合計:[/bold] {result['total']}ファイル  "
                f"[green]✓ {result['succeeded']}件成功[/green]"
                + (f"  [red]✗ {result['failed']}件失敗[/red]" if result["failed"] else "")
            ]
            for r in result.get("results", []):
                cn = r.get("clone_name", "?")
                n  = (r.get("cells_translated") or r.get("paragraphs_translated")
                      or r.get("lines_translated", 0))
                if r.get("ok"):
                    lines.append(f"  [green]✓[/green] {cn} — {n}項目翻訳済み")
                else:
                    lines.append(f"  [red]✗[/red] {cn}: {r.get('error', '?')}")
            lines.append(f"[dim]処理時間: {elapsed}[/dim]")
            console.print(Panel("\n".join(lines), title="[bold]結果[/bold]", style="green"))
        else:
            n = (result.get("cells_translated") or result.get("paragraphs_translated")
                 or result.get("lines_translated", 0))
            console.print(Panel(
                f"[green]✓ 完了！[/green]\n"
                f"複製ファイル: [cyan]{result.get('clone_name', '?')}[/cyan]\n"
                f"翻訳済み    : {n}項目\n"
                f"[dim]処理時間: {elapsed}[/dim]",
                title="[bold]結果[/bold]", style="green",
            ))
    except Exception as e:
        elapsed = _fmt_elapsed()
        console.print(f"[bold red]エラー:[/bold red] {e}")
        console.print(f"[dim]処理時間: {elapsed}[/dim]")

    _press_enter()


def _pick_files_dialog() -> list[str]:
    """ネイティブOSファイル選択ダイアログを開く。選択されたパスの一覧を返す。失敗時は[]。"""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        paths = filedialog.askopenfilenames(
            title="翻訳するファイルを選択",
            filetypes=[
                ("対応ファイル", "*.xlsx *.docx *.txt"),
                ("Excel",       "*.xlsx"),
                ("Word",        "*.docx"),
                ("テキスト",    "*.txt"),
                ("すべて",      "*.*"),
            ],
        )
        root.destroy()
        return list(paths)
    except Exception as e:
        console.print(f"  [dim]ファイル選択ダイアログを開けません: {e}[/dim]")
        return []


def screen_translate_local():
    _header()
    console.print(Panel("[bold]ローカルファイルを翻訳[/bold]", style="green", expand=False))
    console.print()

    console.print("[dim]対応形式: .xlsx  .docx  .txt[/dim]")
    console.print()

    use_dialog = Confirm.ask("ファイル選択ダイアログを開きますか？", default=True)

    file_paths: list[str] = []

    if use_dialog:
        console.print("[dim]ファイル選択ダイアログを開いています…[/dim]")
        picked = _pick_files_dialog()
        if picked:
            for p in picked:
                console.print(f"  [cyan]✓[/cyan] {p}")
            file_paths = picked
        else:
            console.print("  [yellow]ファイルが選択されませんでした。[/yellow]")

    if not file_paths:
        console.print("[dim]絶対パスを1行ずつ入力。空行で終了。[/dim]")
        console.print()
        idx = 1
        while True:
            val = Prompt.ask(f"  ファイル {idx}").strip().strip('"').strip("'")
            if not val:
                break
            if not os.path.isfile(val):
                console.print(f"  [red]見つかりません: {val}[/red]")
                continue
            file_paths.append(val)
            idx += 1

    if not file_paths:
        return

    language = Prompt.ask("翻訳先言語", default="Japanese")
    sheet    = Prompt.ask("シート名 [dim]（.xlsxのみ、空白 = 全シート）[/dim]", default="")

    multi = len(file_paths) > 1
    console.print()
    console.print(
        f"[dim]{'各ファイル' if multi else 'ファイル'}は言語サフィックス付きで複製されます "
        f"（例: [/dim][cyan]-jp[/cyan][dim]） — 元ファイルはそのまま保持。"
        + (f" {len(file_paths)}ファイルを並列処理。[/dim]" if multi else "[/dim]")
    )
    console.print()

    console.rule("[dim]進捗[/dim]")

    from src.tools.translate_local import translate_local_file, translate_local_files
    import time

    t0 = time.monotonic()

    def _fmt_elapsed() -> str:
        s = time.monotonic() - t0
        return f"{s:.1f}s" if s < 60 else f"{int(s)//60}m {int(s)%60:02d}s"

    def _progress(msg: str):
        t_str    = _fmt_elapsed()
        is_error = msg.upper().startswith("ERROR") or "failed" in msg.lower()
        if is_error:
            console.print(f"  [red][{t_str}] {msg}[/red]")
        else:
            console.print(f"  [dim][{t_str}][/dim] {msg}")

    try:
        if multi:
            result = translate_local_files(file_paths, language, sheet, _progress)
        else:
            result = translate_local_file(file_paths[0], language, sheet, _progress)

        elapsed = _fmt_elapsed()
        console.rule()

        if "error" in result:
            console.print(f"[bold red]エラー:[/bold red] {result['error']}")
            console.print(f"[dim]処理時間: {elapsed}[/dim]")
        elif multi:
            lines = [
                f"[bold]合計:[/bold] {result['total']}ファイル  "
                f"[green]✓ {result['succeeded']}件成功[/green]"
                + (f"  [red]✗ {result['failed']}件失敗[/red]" if result["failed"] else "")
            ]
            for r in result.get("results", []):
                cn = r.get("clone_name", "?")
                n  = (r.get("cells_translated") or r.get("paragraphs_translated")
                      or r.get("lines_translated", 0))
                if r.get("ok"):
                    lines.append(f"  [green]✓[/green] {cn} — {n}項目翻訳済み")
                else:
                    lines.append(f"  [red]✗[/red] {cn}: {r.get('error', '?')}")
            lines.append(f"[dim]処理時間: {elapsed}[/dim]")
            console.print(Panel("\n".join(lines), title="[bold]結果[/bold]", style="green"))
        else:
            n  = (result.get("cells_translated") or result.get("paragraphs_translated")
                  or result.get("lines_translated", 0))
            cp = result.get("clone_path", "")
            console.print(Panel(
                f"[green]✓ 完了！[/green]\n"
                f"複製ファイル: [cyan]{result.get('clone_name', '?')}[/cyan]\n"
                f"パス        : [dim]{cp}[/dim]\n"
                f"翻訳済み    : {n}項目\n"
                f"[dim]処理時間: {elapsed}[/dim]",
                title="[bold]結果[/bold]", style="green",
            ))
    except Exception as e:
        elapsed = _fmt_elapsed()
        console.print(f"[bold red]エラー:[/bold red] {e}")
        console.print(f"[dim]処理時間: {elapsed}[/dim]")

    _press_enter()


def screen_list():
    _header()
    console.print(Panel("[bold]Google Driveファイル一覧[/bold]", style="blue", expand=False))
    console.print()

    if not _check_auth():
        console.print("[red]Google認証が完了していません。先に認証を行ってください。[/red]")
        _press_enter()
        return

    folder_id = Prompt.ask("フォルダIDまたはURL [dim]（Enter = root）[/dim]", default="root")
    query     = Prompt.ask("名前で検索 [dim]（Enter = 全て）[/dim]", default="")
    limit     = Prompt.ask("最大件数", default="50")

    try:
        from src.tools.google_drive import list_drive_files
        with console.status("[bold blue]一覧を読み込み中...[/bold blue]", spinner="dots"):
            raw = list_drive_files(folder_id=folder_id, query=query, page_size=int(limit))
        data = json.loads(raw)
    except Exception as e:
        console.print(f"[bold red]エラー:[/bold red] {e}")
        _press_enter()
        return

    if "error" in data:
        console.print(f"[bold red]エラー:[/bold red] {data['error']}")
        _press_enter()
        return

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
    table.add_column("ファイル名", style="white", min_width=30, max_width=50)
    table.add_column("種類", style="yellow", min_width=12)
    table.add_column("サイズ", justify="right", style="dim")
    table.add_column("リンク", style="blue dim", no_wrap=True, max_width=40)

    for f in data["files"]:
        mime_short = f.get("mimeType", "").split(".")[-1].replace("google-apps.", "")
        size = f.get("size", "")
        size_str = f"{int(size):,} B" if size else "—"
        link = f.get("webViewLink", "")
        table.add_row(f["name"], mime_short, size_str, link)

    console.print()
    console.print(f"[bold]フォルダ:[/bold] {data['folder_id']}  |  [bold]{data['count']}[/bold]件")
    console.print(table)

    _press_enter()


def screen_settings():
    import config as _cfg

    while True:
        _header()
        console.print(Panel("[bold]LLMプロバイダー設定[/bold]", style="cyan", expand=False))
        console.print()

        for pid, info in _cfg.PROVIDERS.items():
            active  = "● " if pid == _cfg.get_active_provider() else "  "
            key     = _cfg.get_api_key(pid)
            key_str = f"[green]{key[:8]}…[/green]" if key else "[red]未設定[/red]"
            model   = _cfg.get_model(pid)
            style   = "bold cyan" if pid == _cfg.get_active_provider() else "white"
            console.print(f"  [{style}]{active}{info['label']}[/{style}]")
            console.print(f"      APIキー : {key_str}")
            console.print(f"      モデル  : [dim]{model}[/dim]")
            console.print()

        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column("Key", style="bold cyan", width=4)
        table.add_column("", style="white")
        for pid, info in _cfg.PROVIDERS.items():
            idx = list(_cfg.PROVIDERS).index(pid) + 1
            table.add_row(f"[{idx}]", f"{info['label']}を選択")
        table.add_row("[a]", "APIキーを更新")
        table.add_row("[m]", "モデルを変更")
        table.add_row("[0]", "[dim]戻る[/dim]")
        console.print(table)
        console.print()

        choice = Prompt.ask("[bold]選択[/bold]",
                            choices=[str(i+1) for i in range(len(_cfg.PROVIDERS))] + ["a","m","0"],
                            default="0")

        if choice == "0":
            break

        elif choice in [str(i+1) for i in range(len(_cfg.PROVIDERS))]:
            pid = list(_cfg.PROVIDERS)[int(choice) - 1]
            _cfg.set_active_provider(pid)
            _cfg.save_to_env()
            console.print(f"\n[green]✓ {_cfg.PROVIDERS[pid]['label']}を選択しました[/green]")
            _press_enter()

        elif choice == "a":
            console.print()
            for i, (pid, info) in enumerate(_cfg.PROVIDERS.items(), 1):
                console.print(f"  [{i}] {info['label']}")
            p_choice = Prompt.ask("APIキーを更新するプロバイダーを選択",
                                  choices=[str(i+1) for i in range(len(_cfg.PROVIDERS))],
                                  default="1")
            pid  = list(_cfg.PROVIDERS)[int(p_choice) - 1]
            key  = Prompt.ask(f"{_cfg.PROVIDERS[pid]['label']}のAPIキー").strip()
            if key:
                _cfg.set_api_key(pid, key)
                _cfg.save_to_env()
                console.print("[green]✓ APIキーを保存しました[/green]")
            _press_enter()

        elif choice == "m":
            console.print()
            pid   = _cfg.get_active_provider()
            info  = _cfg.PROVIDERS[pid]
            console.print(f"プロバイダー: [bold]{info['label']}[/bold]\n")
            for i, m in enumerate(info["models"], 1):
                cur = " [cyan]← 現在[/cyan]" if m == _cfg.get_model(pid) else ""
                console.print(f"  [{i}] {m}{cur}")
            console.print(f"  [c] 他のモデルIDを入力")
            model_choices = [str(i+1) for i in range(len(info["models"]))] + ["c"]
            m_choice = Prompt.ask("モデルを選択", choices=model_choices, default="1")
            if m_choice == "c":
                new_model = Prompt.ask("モデルIDを入力").strip()
            else:
                new_model = info["models"][int(m_choice) - 1]
            if new_model:
                _cfg.set_model(pid, new_model)
                _cfg.save_to_env()
                console.print(f"[green]✓ モデルを変更しました: {new_model}[/green]")
            _press_enter()


# ── メインメニュー ────────────────────────────────────────────────────────────

MENU_ITEMS = [
    ("1", "Google認証 (Auth Setup)",              screen_auth),
    ("2", "Googleファイルを翻訳",                  screen_translate),
    ("3", "ローカルファイルを翻訳 (.xlsx/.docx/.txt)", screen_translate_local),
    ("4", "Google Driveファイル一覧",              screen_list),
    ("5", "LLMプロバイダー設定",                   screen_settings),
    ("0", "終了",                                  None),
]


def _setup_wizard():
    """初回起動ウィザード: プロバイダー選択 → APIキー入力 → モデル選択。"""
    import config as _cfg

    console.clear()
    console.print(Panel(
        "[bold cyan]LLM File Translatorへようこそ！[/bold cyan]\n"
        "[dim]初回起動 — LLMプロバイダーを設定してください。[/dim]",
        box=box.DOUBLE_EDGE, expand=False, padding=(0, 2),
    ))
    console.print()

    console.print("[bold]ステップ 1/3 — LLMプロバイダーを選択[/bold]\n")
    for i, (pid, info) in enumerate(_cfg.PROVIDERS.items(), 1):
        console.print(f"  [{i}] [bold]{info['label']}[/bold]")
    console.print()

    p_choice = Prompt.ask(
        "プロバイダーを選択",
        choices=[str(i+1) for i in range(len(_cfg.PROVIDERS))],
        default="1",
    )
    pid  = list(_cfg.PROVIDERS)[int(p_choice) - 1]
    info = _cfg.PROVIDERS[pid]
    _cfg.set_active_provider(pid)
    console.print(f"[green]✓ {info['label']}を選択しました[/green]\n")

    console.print(f"[bold]ステップ 2/3 — APIキーを入力（{info['label']}）[/bold]")
    if pid == "openrouter":
        console.print("[dim]取得場所: https://openrouter.ai/keys[/dim]")
    elif pid == "nvidia":
        console.print("[dim]取得場所: https://build.nvidia.com/ → Get API Key[/dim]")
    console.print()

    while True:
        key = Prompt.ask("APIキー").strip()
        if key:
            break
        console.print("[red]APIキーは必須です。[/red]")

    _cfg.set_api_key(pid, key)
    console.print("[green]✓ APIキーを保存しました[/green]\n")

    console.print(f"[bold]ステップ 3/3 — モデルを選択[/bold]\n")
    for i, m in enumerate(info["models"], 1):
        console.print(f"  [{i}] {m}")
    console.print(f"  [c] 他のモデルIDを入力")
    console.print()

    model_choices = [str(i+1) for i in range(len(info["models"]))] + ["c"]
    m_choice = Prompt.ask("モデルを選択", choices=model_choices, default="1")

    if m_choice == "c":
        while True:
            new_model = Prompt.ask("モデルIDを入力").strip()
            if new_model:
                break
            console.print("[red]モデルIDは必須です。[/red]")
    else:
        new_model = info["models"][int(m_choice) - 1]

    _cfg.set_model(pid, new_model)
    console.print(f"[green]✓ モデルを選択しました: {new_model}[/green]\n")

    _cfg.save_to_env()
    console.print(Panel(
        f"[bold green]設定完了！[/bold green]\n"
        f"プロバイダー: [cyan]{info['label']}[/cyan]\n"
        f"モデル      : [cyan]{new_model}[/cyan]",
        expand=False,
    ))
    _press_enter()


def main():
    import config as _cfg

    if not _cfg.get_api_key():
        _setup_wizard()

    while True:
        _header()

        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column("Key",  style="bold cyan",  width=4)
        table.add_column("Menu", style="white")

        for key, label, _ in MENU_ITEMS:
            style = "dim" if key == "0" else ""
            table.add_row(f"[{key}]", f"[{style}]{label}[/{style}]" if style else label)

        console.print(table)
        console.print()

        choice = Prompt.ask("[bold]選択[/bold]", choices=[k for k, *_ in MENU_ITEMS], default="0")

        for key, _, fn in MENU_ITEMS:
            if choice == key:
                if fn is None:
                    console.print("\n[dim]さようなら！[/dim]")
                    sys.exit(0)
                fn()
                break


if __name__ == "__main__":
    main()
