"""LLM File TranslatorのCLIエントリーポイント。"""

from __future__ import annotations

import argparse
import json
import sys


def cmd_translate(args):
    from src.tools.translate_google import translate_google_file

    target = args.language or "Japanese"

    def _progress(msg: str):
        print(f"  {msg}")

    print(f"{target}に翻訳中...\n{'─' * 50}")
    result = translate_google_file(args.file_id, target, args.sheet or "", _progress)
    print("─" * 50)

    if "error" in result:
        print(f"エラー: {result['error']}", file=sys.stderr)
        sys.exit(1)

    n = (result.get("cells_translated") or result.get("paragraphs_translated")
         or result.get("lines_translated", 0))
    print(f"完了！複製ファイル: {result.get('clone_name', '?')}  —  {n}項目翻訳済み。")


def cmd_list(args):
    from src.tools.google_drive import list_drive_files

    raw = list_drive_files(
        folder_id=args.folder_id or "root",
        query=args.query or "",
        page_size=args.limit or 50,
    )
    data = json.loads(raw)
    if "error" in data:
        print(f"エラー: {data['error']}", file=sys.stderr)
        sys.exit(1)

    print(f"フォルダ: {data['folder_id']}  ({data['count']}件)")
    print("─" * 60)
    for f in data["files"]:
        size = f.get("size", "")
        size_str = f" [{int(size):,} バイト]" if size else ""
        print(f"  {f['name']:<40} {f['mimeType'].split('.')[-1]}{size_str}")
        if f.get("webViewLink"):
            print(f"    {f['webViewLink']}")


def main():
    parser = argparse.ArgumentParser(
        prog="llm-file-translator",
        description="LLMを使ってGoogleドライブのファイルを翻訳します",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_translate = sub.add_parser("translate", help="Googleファイルを翻訳する")
    p_translate.add_argument("file_id", help="GoogleファイルIDまたはURL")
    p_translate.add_argument("-l", "--language", default="Japanese", help="翻訳先言語（デフォルト: Japanese）")
    p_translate.add_argument("-s", "--sheet", default="", help="シート名（Sheetsのみ）")
    p_translate.set_defaults(func=cmd_translate)

    p_list = sub.add_parser("list", help="Google Driveのファイル一覧を表示する")
    p_list.add_argument("folder_id", nargs="?", default="root", help="フォルダIDまたはURL（デフォルト: root）")
    p_list.add_argument("-q", "--query", default="", help="検索キーワード")
    p_list.add_argument("-n", "--limit", type=int, default=50, help="最大件数")
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
