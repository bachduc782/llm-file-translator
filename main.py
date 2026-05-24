"""CLI entry point for Google Translator."""

from __future__ import annotations

import argparse
import json
import sys


def cmd_translate(args):
    from src.tools.translate_google import translate_google_file

    target = args.language or "Vietnamese"

    def _progress(msg: str):
        print(f"  {msg}")

    print(f"Translating to {target}...\n{'─' * 50}")
    result = translate_google_file(args.file_id, target, args.sheet or "", _progress)
    print("─" * 50)

    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)

    n = (result.get("cells_translated") or result.get("paragraphs_translated")
         or result.get("lines_translated", 0))
    print(f"Done! Clone: {result.get('clone_name', '?')}  —  {n} items translated.")


def cmd_list(args):
    from src.tools.google_drive import list_drive_files

    raw = list_drive_files(
        folder_id=args.folder_id or "root",
        query=args.query or "",
        page_size=args.limit or 50,
    )
    data = json.loads(raw)
    if "error" in data:
        print(f"Error: {data['error']}", file=sys.stderr)
        sys.exit(1)

    print(f"Folder: {data['folder_id']}  ({data['count']} files)")
    print("─" * 60)
    for f in data["files"]:
        size = f.get("size", "")
        size_str = f" [{int(size):,} bytes]" if size else ""
        print(f"  {f['name']:<40} {f['mimeType'].split('.')[-1]}{size_str}")
        if f.get("webViewLink"):
            print(f"    {f['webViewLink']}")


def main():
    parser = argparse.ArgumentParser(
        prog="langchain-translator",
        description="Translate Google Drive files using an LLM",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_translate = sub.add_parser("translate", help="Translate a Google file")
    p_translate.add_argument("file_id", help="Google file ID or URL")
    p_translate.add_argument("-l", "--language", default="Vietnamese", help="Target language (default: Vietnamese)")
    p_translate.add_argument("-s", "--sheet", default="", help="Sheet name (Sheets only)")
    p_translate.set_defaults(func=cmd_translate)

    p_list = sub.add_parser("list", help="List files in Google Drive")
    p_list.add_argument("folder_id", nargs="?", default="root", help="Folder ID or URL (default: root)")
    p_list.add_argument("-q", "--query", default="", help="Search keyword")
    p_list.add_argument("-n", "--limit", type=int, default=50, help="Max results")
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
