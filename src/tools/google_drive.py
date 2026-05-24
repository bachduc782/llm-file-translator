"""Google Drive helpers."""

from __future__ import annotations

import json
import re

from src.auth.google_auth import build_drive_service

_LANG_SUFFIX: dict[str, str] = {
    "vietnamese": "vn", "japanese": "jp", "english": "en", "korean": "ko",
    "chinese": "zh", "french": "fr", "spanish": "es", "german": "de",
    "thai": "th", "indonesian": "id", "arabic": "ar", "portuguese": "pt",
    "russian": "ru", "italian": "it", "dutch": "nl", "hindi": "hi",
}


def _parse_drive_id(url_or_id: str) -> str:
    for pat in [r"/folders/([a-zA-Z0-9_-]+)", r"/file/d/([a-zA-Z0-9_-]+)", r"[?&]id=([a-zA-Z0-9_-]+)"]:
        m = re.search(pat, url_or_id)
        if m:
            return m.group(1)
    return url_or_id.strip()


def _resolve_file_id(url_or_id: str) -> str:
    for pat in [
        r"/spreadsheets/d/([a-zA-Z0-9_-]+)",
        r"/document/d/([a-zA-Z0-9_-]+)",
        r"/file/d/([a-zA-Z0-9_-]+)",
        r"[?&]id=([a-zA-Z0-9_-]+)",
    ]:
        m = re.search(pat, url_or_id)
        if m:
            return m.group(1)
    return url_or_id.strip()


def _clone_file_impl(drive, file_id: str, target_language: str) -> dict:
    """Clone a single file and return result dict."""
    clean_id = _resolve_file_id(file_id)

    try:
        meta = drive.files().get(
            fileId=clean_id, fields="id,name,mimeType,parents", supportsAllDrives=True
        ).execute()
    except Exception as e:
        return {"error": f"Cannot access file: {e}", "original_id": file_id}

    original_name = meta.get("name", clean_id)
    parents = meta.get("parents", [])
    suffix = _LANG_SUFFIX.get(target_language.lower(), target_language[:2].lower())
    clone_name = f"{original_name}-{suffix}"

    try:
        clone_meta = {"name": clone_name}
        if parents:
            clone_meta["parents"] = parents
        clone = drive.files().copy(
            fileId=clean_id, body=clone_meta, supportsAllDrives=True
        ).execute()
    except Exception as e:
        return {"error": f"Cannot clone file: {e}", "original_id": clean_id}

    return {
        "ok": True,
        "original_id": clean_id,
        "original_name": original_name,
        "clone_id": clone["id"],
        "clone_name": clone_name,
        "file_type": meta.get("mimeType", ""),
    }


def list_drive_files(folder_id: str = "root", query: str = "", page_size: int = 50) -> str:
    """List files and folders in Google Drive. Returns JSON string."""
    drive = build_drive_service()
    fid = _parse_drive_id(folder_id)

    q_parts = [f"'{fid}' in parents", "trashed=false"]
    if query:
        q_parts.append(f"name contains '{query}'")
    q = " and ".join(q_parts)

    try:
        result = drive.files().list(
            q=q,
            pageSize=min(page_size, 100),
            fields="files(id,name,mimeType,size,modifiedTime,webViewLink)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)

    files = result.get("files", [])
    return json.dumps({"folder_id": fid, "count": len(files), "files": files}, ensure_ascii=False)
