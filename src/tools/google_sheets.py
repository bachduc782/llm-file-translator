"""Google Sheetsユーティリティ。"""

from __future__ import annotations

import json
import re

from src.auth.google_auth import build_sheets_service


def _parse_spreadsheet_id(url_or_id: str) -> str:
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url_or_id)
    return m.group(1) if m else url_or_id.strip()


def list_sheets(url: str) -> str:
    """List all sheets in a Google Spreadsheet. Returns JSON string."""
    svc = build_sheets_service()
    sid = _parse_spreadsheet_id(url)
    try:
        result = svc.spreadsheets().get(
            spreadsheetId=sid, fields="properties.title,sheets.properties"
        ).execute()
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)

    sheets = [
        {"title": s["properties"]["title"], "sheet_id": s["properties"]["sheetId"]}
        for s in result.get("sheets", [])
    ]
    return json.dumps({
        "spreadsheet_id": sid,
        "title": result.get("properties", {}).get("title", ""),
        "sheets": sheets,
    }, ensure_ascii=False)
