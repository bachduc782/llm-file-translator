"""Interactive console UI for Google Translator."""

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
    """Patch requests to tolerate SSL EOF — fixes Python 3.14 strict TLS behavior."""
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

TITLE = "[bold cyan]Google Translator[/bold cyan]"
VERSION = "v2.0"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _check_auth() -> bool:
    import config
    return os.path.exists(config.GOOGLE_TOKEN_FILE)


def _check_api_key() -> bool:
    import config
    return bool(config.get_api_key())


def _header():
    import config as _cfg
    console.clear()
    status_auth = "[green]✓ Đã xác thực[/green]" if _check_auth() else "[red]✗ Chưa xác thực[/red]"
    status_api  = "[green]✓ API key OK[/green]"   if _check_api_key() else "[red]✗ Thiếu API key[/red]"
    provider    = _cfg.PROVIDERS[_cfg.get_active_provider()]["label"]
    model       = _cfg.get_model()

    console.print(Panel(
        f"[bold cyan]Google Translator[/bold cyan]  [dim]{VERSION}[/dim]\n"
        f"Google OAuth: {status_auth}    LLM: {status_api}  "
        f"[dim]({provider} / {model})[/dim]",
        box=box.DOUBLE_EDGE,
        expand=False,
        padding=(0, 2),
    ))
    console.print()


def _press_enter():
    console.print()
    Prompt.ask("[dim]Nhấn Enter để tiếp tục[/dim]", default="")


# ── Screens ───────────────────────────────────────────────────────────────────

def screen_auth():
    _header()
    console.print(Panel("[bold]Xác thực Google OAuth[/bold]", style="yellow", expand=False))
    console.print()

    if _check_auth():
        import config
        console.print(f"[green]Token hiện có tại:[/green] {config.GOOGLE_TOKEN_FILE}")
        if not Confirm.ask("Xác thực lại?", default=False):
            return

    console.print("[dim]Mở trình duyệt để đăng nhập Google...[/dim]\n")
    try:
        import auth_setup
        auth_setup.main()
        console.print("\n[bold green]✓ Xác thực thành công![/bold green]")
    except Exception as e:
        console.print(f"\n[bold red]Lỗi:[/bold red] {e}")

    _press_enter()


def screen_translate():
    _header()
    console.print(Panel("[bold]Dịch file Google[/bold]", style="green", expand=False))
    console.print()

    if not _check_auth():
        console.print("[red]Chưa xác thực Google. Vui lòng chạy Auth Setup trước.[/red]")
        _press_enter()
        return

    console.print("[dim]Nhập một hoặc nhiều File ID / URL, mỗi cái một dòng. Dòng trống để kết thúc.[/dim]")
    file_ids: list[str] = []
    idx = 1
    while True:
        val = Prompt.ask(f"  File {idx}").strip()
        if not val:
            break
        file_ids.append(val)
        idx += 1

    if not file_ids:
        return

    language = Prompt.ask("Ngôn ngữ đích", default="Vietnamese")
    sheet    = Prompt.ask("Tên sheet [dim](để trống = dịch tất cả sheet)[/dim]", default="")

    multi = len(file_ids) > 1
    console.print()
    console.print(
        f"[dim]{'Mỗi file' if multi else 'File'} sẽ được sao chép với hậu tố ngôn ngữ "
        f"(ví dụ [/dim][cyan]-jp[/cyan][dim]) — file gốc giữ nguyên."
        + (f" {len(file_ids)} file chạy song song.[/dim]" if multi else "[/dim]")
    )
    console.print()

    console.rule("[dim]Tiến trình[/dim]")

    def _progress(msg: str):
        console.print(f"  [dim]{msg}[/dim]")

    from src.tools.translate_google import translate_google_file, translate_google_files
    import time

    t0 = time.monotonic()

    def _fmt_elapsed() -> str:
        s = time.monotonic() - t0
        if s < 60:
            return f"{s:.1f}s"
        return f"{int(s) // 60}m {int(s) % 60}s"

    try:
        if multi:
            result = translate_google_files(file_ids, language, sheet, _progress)
        else:
            result = translate_google_file(file_ids[0], language, sheet, _progress)

        elapsed = _fmt_elapsed()
        console.rule()

        if "error" in result:
            console.print(f"[bold red]Lỗi:[/bold red] {result['error']}")
            console.print(f"[dim]Thời gian: {elapsed}[/dim]")
        elif multi:
            lines = [
                f"[bold]Tổng:[/bold] {result['total']} file  "
                f"[green]✓ {result['succeeded']} thành công[/green]"
                + (f"  [red]✗ {result['failed']} thất bại[/red]" if result["failed"] else "")
            ]
            for r in result.get("results", []):
                cn = r.get("clone_name", "?")
                n  = (r.get("cells_translated") or r.get("paragraphs_translated")
                      or r.get("lines_translated", 0))
                if r.get("ok"):
                    lines.append(f"  [green]✓[/green] {cn} — {n} mục đã dịch")
                else:
                    lines.append(f"  [red]✗[/red] {cn}: {r.get('error', '?')}")
            lines.append(f"[dim]Thời gian xử lý: {elapsed}[/dim]")
            console.print(Panel("\n".join(lines), title="[bold]Kết quả[/bold]", style="green"))
        else:
            n = (result.get("cells_translated") or result.get("paragraphs_translated")
                 or result.get("lines_translated", 0))
            console.print(Panel(
                f"[green]✓ Thành công![/green]\n"
                f"File mới: [cyan]{result.get('clone_name', '?')}[/cyan]\n"
                f"Đã dịch : {n} mục\n"
                f"[dim]Thời gian xử lý: {elapsed}[/dim]",
                title="[bold]Kết quả[/bold]", style="green",
            ))
    except Exception as e:
        elapsed = _fmt_elapsed()
        console.print(f"[bold red]Lỗi:[/bold red] {e}")
        console.print(f"[dim]Thời gian: {elapsed}[/dim]")

    _press_enter()


def screen_list():
    _header()
    console.print(Panel("[bold]Liệt kê file Google Drive[/bold]", style="blue", expand=False))
    console.print()

    if not _check_auth():
        console.print("[red]Chưa xác thực Google. Vui lòng chạy Auth Setup trước.[/red]")
        _press_enter()
        return

    folder_id = Prompt.ask("Folder ID hoặc URL [dim](Enter = root)[/dim]", default="root")
    query     = Prompt.ask("Tìm kiếm theo tên [dim](Enter = tất cả)[/dim]", default="")
    limit     = Prompt.ask("Số lượng tối đa", default="50")

    try:
        from src.tools.google_drive import list_drive_files
        with console.status("[bold blue]Đang tải danh sách...[/bold blue]", spinner="dots"):
            raw = list_drive_files(folder_id=folder_id, query=query, page_size=int(limit))
        data = json.loads(raw)
    except Exception as e:
        console.print(f"[bold red]Lỗi:[/bold red] {e}")
        _press_enter()
        return

    if "error" in data:
        console.print(f"[bold red]Lỗi:[/bold red] {data['error']}")
        _press_enter()
        return

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
    table.add_column("Tên file", style="white", min_width=30, max_width=50)
    table.add_column("Loại", style="yellow", min_width=12)
    table.add_column("Kích thước", justify="right", style="dim")
    table.add_column("Link", style="blue dim", no_wrap=True, max_width=40)

    for f in data["files"]:
        mime_short = f.get("mimeType", "").split(".")[-1].replace("google-apps.", "")
        size = f.get("size", "")
        size_str = f"{int(size):,} B" if size else "—"
        link = f.get("webViewLink", "")
        table.add_row(f["name"], mime_short, size_str, link)

    console.print()
    console.print(f"[bold]Folder:[/bold] {data['folder_id']}  |  [bold]{data['count']}[/bold] file(s)")
    console.print(table)

    _press_enter()


def screen_settings():
    import config as _cfg

    while True:
        _header()
        console.print(Panel("[bold]Cài đặt Provider LLM[/bold]", style="cyan", expand=False))
        console.print()

        for pid, info in _cfg.PROVIDERS.items():
            active  = "● " if pid == _cfg.get_active_provider() else "  "
            key     = _cfg.get_api_key(pid)
            key_str = f"[green]{key[:8]}…[/green]" if key else "[red]Chưa cấu hình[/red]"
            model   = _cfg.get_model(pid)
            style   = "bold cyan" if pid == _cfg.get_active_provider() else "white"
            console.print(f"  [{style}]{active}{info['label']}[/{style}]")
            console.print(f"      API Key : {key_str}")
            console.print(f"      Model   : [dim]{model}[/dim]")
            console.print()

        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column("Key", style="bold cyan", width=4)
        table.add_column("", style="white")
        for pid, info in _cfg.PROVIDERS.items():
            idx = list(_cfg.PROVIDERS).index(pid) + 1
            table.add_row(f"[{idx}]", f"Chọn {info['label']}")
        table.add_row("[a]", "Cập nhật API key")
        table.add_row("[m]", "Đổi model")
        table.add_row("[0]", "[dim]Quay lại[/dim]")
        console.print(table)
        console.print()

        choice = Prompt.ask("[bold]Chọn[/bold]",
                            choices=[str(i+1) for i in range(len(_cfg.PROVIDERS))] + ["a","m","0"],
                            default="0")

        if choice == "0":
            break

        elif choice in [str(i+1) for i in range(len(_cfg.PROVIDERS))]:
            pid = list(_cfg.PROVIDERS)[int(choice) - 1]
            _cfg.set_active_provider(pid)
            _cfg.save_to_env()
            console.print(f"\n[green]✓ Đã chọn {_cfg.PROVIDERS[pid]['label']}[/green]")
            _press_enter()

        elif choice == "a":
            console.print()
            for i, (pid, info) in enumerate(_cfg.PROVIDERS.items(), 1):
                console.print(f"  [{i}] {info['label']}")
            p_choice = Prompt.ask("Chọn provider để cập nhật key",
                                  choices=[str(i+1) for i in range(len(_cfg.PROVIDERS))],
                                  default="1")
            pid  = list(_cfg.PROVIDERS)[int(p_choice) - 1]
            key  = Prompt.ask(f"API key cho {_cfg.PROVIDERS[pid]['label']}").strip()
            if key:
                _cfg.set_api_key(pid, key)
                _cfg.save_to_env()
                console.print("[green]✓ Đã lưu API key[/green]")
            _press_enter()

        elif choice == "m":
            console.print()
            pid   = _cfg.get_active_provider()
            info  = _cfg.PROVIDERS[pid]
            console.print(f"Provider: [bold]{info['label']}[/bold]\n")
            for i, m in enumerate(info["models"], 1):
                cur = " [cyan]← hiện tại[/cyan]" if m == _cfg.get_model(pid) else ""
                console.print(f"  [{i}] {m}{cur}")
            console.print(f"  [c] Nhập model khác")
            model_choices = [str(i+1) for i in range(len(info["models"]))] + ["c"]
            m_choice = Prompt.ask("Chọn model", choices=model_choices, default="1")
            if m_choice == "c":
                new_model = Prompt.ask("Nhập model ID").strip()
            else:
                new_model = info["models"][int(m_choice) - 1]
            if new_model:
                _cfg.set_model(pid, new_model)
                _cfg.save_to_env()
                console.print(f"[green]✓ Model đã đổi thành {new_model}[/green]")
            _press_enter()


# ── Main menu ─────────────────────────────────────────────────────────────────

MENU_ITEMS = [
    ("1", "Xác thực Google (Auth Setup)", screen_auth),
    ("2", "Dịch file Google",             screen_translate),
    ("3", "Liệt kê file Google Drive",    screen_list),
    ("4", "Cài đặt Provider LLM",        screen_settings),
    ("0", "Thoát",                        None),
]


def _setup_wizard():
    """First-run wizard: choose provider → enter API key → choose model."""
    import config as _cfg

    console.clear()
    console.print(Panel(
        "[bold cyan]Chào mừng đến Google Translator![/bold cyan]\n"
        "[dim]Lần đầu sử dụng — hãy cấu hình LLM provider.[/dim]",
        box=box.DOUBLE_EDGE, expand=False, padding=(0, 2),
    ))
    console.print()

    console.print("[bold]Bước 1/3 — Chọn LLM Provider[/bold]\n")
    for i, (pid, info) in enumerate(_cfg.PROVIDERS.items(), 1):
        console.print(f"  [{i}] [bold]{info['label']}[/bold]")
    console.print()

    p_choice = Prompt.ask(
        "Chọn provider",
        choices=[str(i+1) for i in range(len(_cfg.PROVIDERS))],
        default="1",
    )
    pid  = list(_cfg.PROVIDERS)[int(p_choice) - 1]
    info = _cfg.PROVIDERS[pid]
    _cfg.set_active_provider(pid)
    console.print(f"[green]✓ Đã chọn {info['label']}[/green]\n")

    console.print(f"[bold]Bước 2/3 — Nhập API key cho {info['label']}[/bold]")
    if pid == "openrouter":
        console.print("[dim]Lấy tại: https://openrouter.ai/keys[/dim]")
    elif pid == "nvidia":
        console.print("[dim]Lấy tại: https://build.nvidia.com/ → Get API Key[/dim]")
    console.print()

    while True:
        key = Prompt.ask("API key").strip()
        if key:
            break
        console.print("[red]API key không được để trống.[/red]")

    _cfg.set_api_key(pid, key)
    console.print("[green]✓ Đã lưu API key[/green]\n")

    console.print(f"[bold]Bước 3/3 — Chọn Model[/bold]\n")
    for i, m in enumerate(info["models"], 1):
        console.print(f"  [{i}] {m}")
    console.print(f"  [c] Nhập model ID khác")
    console.print()

    model_choices = [str(i+1) for i in range(len(info["models"]))] + ["c"]
    m_choice = Prompt.ask("Chọn model", choices=model_choices, default="1")

    if m_choice == "c":
        while True:
            new_model = Prompt.ask("Nhập model ID").strip()
            if new_model:
                break
            console.print("[red]Model ID không được để trống.[/red]")
    else:
        new_model = info["models"][int(m_choice) - 1]

    _cfg.set_model(pid, new_model)
    console.print(f"[green]✓ Đã chọn model: {new_model}[/green]\n")

    _cfg.save_to_env()
    console.print(Panel(
        f"[bold green]Cấu hình hoàn tất![/bold green]\n"
        f"Provider : [cyan]{info['label']}[/cyan]\n"
        f"Model    : [cyan]{new_model}[/cyan]",
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

        choice = Prompt.ask("[bold]Chọn[/bold]", choices=[k for k, *_ in MENU_ITEMS], default="0")

        for key, _, fn in MENU_ITEMS:
            if choice == key:
                if fn is None:
                    console.print("\n[dim]Tạm biệt![/dim]")
                    sys.exit(0)
                fn()
                break


if __name__ == "__main__":
    main()
