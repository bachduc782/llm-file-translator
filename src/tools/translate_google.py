"""Parallel Google file translator — Sheets, Docs, plain-text Drive files."""

from __future__ import annotations

import io
import json
import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import config

SCAN_ROW_BATCH  = 1000
TRANSLATE_CHUNK = 20   # items per LLM call
SHEET_WORKERS   = 4    # parallel LLM calls per sheet (rate limiter keeps within quota)
FILE_WORKERS    = 3    # parallel across multiple files

Progress = Callable[[str], None]

# Cells matching this pattern don't need translation
_RE_SKIP = re.compile(
    r'^[\d\s,.\-+%/()\[\]{}:;*|]+$'   # pure numbers / punctuation
    r'|^[A-Z0-9][A-Z0-9_.\-]{1,29}$'  # ALL_CAPS_CODE — TEST_001, NO-123
    r'|^https?://'                      # URLs
    r'|^[a-zA-Z0-9._%+\-]+@\S+'        # email addresses
    r'|^\d{4}[-/]\d{2}[-/]\d{2}',      # ISO dates — 2024-01-01
)


def _is_translatable(text: str) -> bool:
    t = text.strip()
    return len(t) > 2 and not _RE_SKIP.match(t)


# ── Rate limiter ──────────────────────────────────────────────────────────────

class _RateLimiter:
    """Sliding-window rate limiter, thread-safe."""
    def __init__(self, max_calls: int, period: float = 60.0):
        self.max_calls = max_calls
        self.period    = period
        self._lock     = threading.Lock()
        self._calls: deque[float] = deque()

    def acquire(self):
        while True:
            with self._lock:
                now = time.monotonic()
                while self._calls and self._calls[0] <= now - self.period:
                    self._calls.popleft()
                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return
                wait = self._calls[0] + self.period - now + 0.05
            time.sleep(wait)


_limiter: _RateLimiter | None = None
_limiter_key: tuple | None    = None
_limiter_meta_lock             = threading.Lock()


def _get_limiter() -> _RateLimiter:
    global _limiter, _limiter_key
    cfg = config.get_llm_config()
    key = (cfg["base_url"], cfg["rate_limit"])
    with _limiter_meta_lock:
        if _limiter is None or _limiter_key != key:
            _limiter     = _RateLimiter(cfg["rate_limit"])
            _limiter_key = key
    return _limiter


# ── LLM ───────────────────────────────────────────────────────────────────────

def _call_llm(prompt: str, retries: int = 3, on_retry=None) -> str:
    from openai import OpenAI

    cfg    = config.get_llm_config()
    client = OpenAI(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        default_headers=cfg.get("headers", {}),
        timeout=90.0,
    )
    limiter   = _get_limiter()
    last_exc: Exception | None = None

    for attempt in range(retries):
        limiter.acquire()
        try:
            resp = client.chat.completions.create(
                model=cfg["model"],
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
            )
            raw = (resp.choices[0].message.content or "").strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw.strip())
            return raw
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                is_429 = "429" in str(exc) or "rate" in str(exc).lower()
                wait   = 2 if is_429 else 2 ** (attempt + 1)
                if on_retry:
                    on_retry(attempt + 1, retries, exc, wait)
                time.sleep(wait)
    raise last_exc  # type: ignore[misc]


def _translate_list(items: list[str], target_language: str, on_retry=None) -> list[str]:
    prompt = (
        f"Translate the following list of text items to {target_language}.\n"
        "Rules:\n"
        "- Translate ALL text items.\n"
        "- KEEP AS-IS: proper nouns, codes, numbers, URLs, empty strings.\n"
        "- Preserve EXACT list length — one output per input.\n"
        "- Return ONLY valid JSON array of strings, no explanation, no markdown.\n\n"
        f"Input:\n{json.dumps(items, ensure_ascii=False)}"
    )
    raw = _call_llm(prompt, on_retry=on_retry)
    if not raw.strip():
        return items
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        from json_repair import repair_json
        repaired = repair_json(raw)
        if not repaired or repaired in ("null", "[]", "{}"):
            return items
        try:
            result = json.loads(repaired)
        except json.JSONDecodeError:
            return items
    if not isinstance(result, list):
        return items
    return (result + items[len(result):])[:len(items)]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _col_letter(idx: int) -> str:
    result = ""
    i = idx
    while True:
        result = chr(65 + i % 26) + result
        i = i // 26 - 1
        if i < 0:
            break
    return result


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _noop(*_): pass


# ── Sheets ────────────────────────────────────────────────────────────────────

def _translate_sheets(svc, sid, sheet_names, target_language, progress: Progress = _noop) -> int:
    # ── Phase 1: scan all sheets in parallel ──────────────────────────────────
    all_cells: list[tuple[str, int, int, str]] = []
    total_raw = 0
    scan_lock = threading.Lock()

    def _scan_sheet(sheet_name: str):
        cells, raw = [], 0
        row_offset = 0
        while True:
            range_str = f"'{sheet_name}'!A{row_offset + 1}:ZZ{row_offset + SCAN_ROW_BATCH}"
            values = svc.spreadsheets().values().get(
                spreadsheetId=sid, range=range_str
            ).execute().get("values", [])
            if not values:
                break
            for r, row in enumerate(values):
                for c, cell in enumerate(row):
                    if isinstance(cell, str) and cell.strip():
                        raw += 1
                        if _is_translatable(cell):
                            cells.append((sheet_name, row_offset + r, c, cell))
            row_offset += SCAN_ROW_BATCH
            if len(values) < SCAN_ROW_BATCH:
                break
        return cells, raw

    progress(f"Scanning {len(sheet_names)} sheet(s) in parallel…")
    with ThreadPoolExecutor(max_workers=len(sheet_names)) as pool:
        scan_futures = {pool.submit(_scan_sheet, sn): sn for sn in sheet_names}
        for fut in as_completed(scan_futures):
            cells, raw = fut.result()
            all_cells.extend(cells)
            total_raw += raw
            progress(f"  [{scan_futures[fut]}] {len(cells)} cells found")

    skipped = total_raw - len(all_cells)
    progress(
        f"Total: {len(all_cells)} cells to translate"
        + (f" ({skipped} skipped)" if skipped else "")
    )

    if not all_cells:
        return 0

    # ── Phase 2: translate all cells together in parallel chunks ──────────────
    translated_map: dict[tuple[str, int, int], str] = {}
    lock          = threading.Lock()
    done          = 0
    all_chunks    = list(_chunks(all_cells, TRANSLATE_CHUNK))
    total_chunks  = len(all_chunks)

    def _worker(chunk: list[tuple[str, int, int, str]], idx: int):
        nonlocal done
        progress(f"[{idx}/{total_chunks}] Calling LLM for {len(chunk)} cells…")

        def _on_retry(attempt, total, exc, wait):
            progress(f"RETRY [{idx}/{total_chunks}] attempt {attempt}/{total} (wait {wait}s) — {exc}")

        texts      = [t for _, _, _, t in chunk]
        translated = _translate_list(texts, target_language, on_retry=_on_retry)
        with lock:
            for (sn, r, c, orig), new in zip(chunk, translated):
                if orig != new:
                    translated_map[(sn, r, c)] = new
            done += len(chunk)
            progress(f"[{idx}/{total_chunks}] Done — {done}/{len(all_cells)} cells translated")

    with ThreadPoolExecutor(max_workers=SHEET_WORKERS) as pool:
        futures = {
            pool.submit(_worker, chunk, i + 1): i
            for i, chunk in enumerate(all_chunks)
        }
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                progress(f"ERROR chunk {futures[fut] + 1}: {e}")

    # ── Phase 3: write back — one batchUpdate per sheet ───────────────────────
    by_sheet: dict[str, list] = {}
    for (sn, r, c), new in translated_map.items():
        by_sheet.setdefault(sn, []).append(
            {"range": f"'{sn}'!{_col_letter(c)}{r + 1}", "values": [[new]]}
        )

    WRITE_BATCH = 500   # Sheets API limit per batchUpdate call
    for sn, value_ranges in by_sheet.items():
        for batch in _chunks(value_ranges, WRITE_BATCH):
            svc.spreadsheets().values().batchUpdate(
                spreadsheetId=sid,
                body={"valueInputOption": "RAW", "data": batch},
            ).execute()
        progress(f"Written {len(value_ranges)} cells → [{sn}]")

    return len(all_cells)


# ── Docs ──────────────────────────────────────────────────────────────────────

def _docs_worker(svc, doc_id, para_chunk, target_language, write_lock) -> int:
    translated = _translate_list(para_chunk, target_language)
    requests = [
        {"replaceAllText": {
            "containsText": {"text": orig, "matchCase": True},
            "replaceText":  new,
        }}
        for orig, new in zip(para_chunk, translated)
        if orig.strip() and orig != new
    ]
    if requests:
        with write_lock:
            svc.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
    return len(para_chunk)


def _translate_docs(svc, doc_id, target_language, progress: Progress = _noop) -> int:
    from src.tools.google_docs import _extract_text_from_element

    body_content = svc.documents().get(documentId=doc_id).execute().get("body", {}).get("content", [])
    paragraphs   = [_extract_text_from_element(e).rstrip("\n") for e in body_content]
    paragraphs   = [p for p in paragraphs if p.strip() and _is_translatable(p)]
    total        = len(paragraphs)

    write_lock = threading.Lock()
    done = 0

    with ThreadPoolExecutor(max_workers=SHEET_WORKERS) as pool:
        futures = [
            pool.submit(_docs_worker, svc, doc_id, chunk, target_language, write_lock)
            for chunk in _chunks(paragraphs, TRANSLATE_CHUNK)
        ]
        for fut in as_completed(futures):
            try:
                n = fut.result()
                done += n
                progress(f"Translated {done}/{total} paragraphs")
            except Exception as e:
                progress(f"Paragraph chunk failed, skipping: {e}")

    return done


# ── Plain text ────────────────────────────────────────────────────────────────

def _translate_txt(drive, file_id, target_language, progress: Progress = _noop) -> int:
    from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

    buf = io.BytesIO()
    dl  = MediaIoBaseDownload(buf, drive.files().get_media(fileId=file_id))
    done_dl = False
    while not done_dl:
        _, done_dl = dl.next_chunk()

    all_lines = buf.getvalue().decode("utf-8", errors="replace").splitlines()
    indexed   = [(i, line) for i, line in enumerate(all_lines)
                 if line.strip() and _is_translatable(line)]
    total     = len(indexed)

    translated_map: dict[int, str] = {}
    lock = threading.Lock()
    done = 0

    def _worker(chunk):
        nonlocal done
        result = _translate_list([t for _, t in chunk], target_language)
        with lock:
            for (idx, _), new in zip(chunk, result):
                translated_map[idx] = new
            done += len(chunk)
            progress(f"Translated {done}/{total} lines")

    with ThreadPoolExecutor(max_workers=SHEET_WORKERS) as pool:
        futures = [pool.submit(_worker, chunk) for chunk in _chunks(indexed, TRANSLATE_CHUNK)]
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                progress(f"Line chunk failed, skipping: {e}")

    for idx, new in translated_map.items():
        all_lines[idx] = new

    upload_buf = io.BytesIO("\n".join(all_lines).encode("utf-8"))
    drive.files().update(
        fileId=file_id,
        media_body=MediaIoBaseUpload(upload_buf, mimetype="text/plain"),
        supportsAllDrives=True,
    ).execute()

    return total


# ── Public API ────────────────────────────────────────────────────────────────

def translate_google_file(
    file_id: str,
    target_language: str,
    sheet_name: str = "",
    progress: Progress = _noop,
) -> dict:
    """Clone + translate a single Google file. Returns result dict."""
    from src.auth.google_auth import build_drive_service, build_sheets_service, build_docs_service
    from src.tools.google_drive import _clone_file_impl
    from src.tools.google_sheets import _parse_spreadsheet_id
    from src.tools.google_docs import _parse_doc_id

    drive = build_drive_service()

    progress("Cloning file...")
    clone = _clone_file_impl(drive, file_id, target_language)
    if "error" in clone:
        return {"error": clone["error"], "original_id": file_id}

    clone_id   = clone["clone_id"]
    clone_name = clone["clone_name"]
    mime       = clone["file_type"]
    progress(f"Clone: {clone['original_name']} → {clone_name}")

    try:
        if mime == "application/vnd.google-apps.spreadsheet":
            svc = build_sheets_service()
            sid = _parse_spreadsheet_id(clone_id)
            if sheet_name:
                sheet_names = [sheet_name]
            else:
                s_meta      = svc.spreadsheets().get(spreadsheetId=sid, fields="sheets.properties.title").execute()
                sheet_names = [s["properties"]["title"] for s in s_meta.get("sheets", [])]
            total = _translate_sheets(svc, sid, sheet_names, target_language, progress)
            return {"ok": True, "clone_name": clone_name, "file_type": "sheets",
                    "sheets": sheet_names, "cells_translated": total}

        elif mime == "application/vnd.google-apps.document":
            svc    = build_docs_service()
            doc_id = _parse_doc_id(clone_id)
            total  = _translate_docs(svc, doc_id, target_language, progress)
            return {"ok": True, "clone_name": clone_name, "file_type": "docs",
                    "paragraphs_translated": total}

        elif mime == "text/plain":
            total = _translate_txt(drive, clone_id, target_language, progress)
            return {"ok": True, "clone_name": clone_name, "file_type": "txt",
                    "lines_translated": total}

        else:
            return {"error": f"Unsupported file type: {mime}", "clone_name": clone_name}

    except Exception as e:
        return {"error": str(e), "clone_name": clone_name}


def translate_google_files(
    file_ids: list[str],
    target_language: str,
    sheet_name: str = "",
    progress: Progress = _noop,
) -> dict:
    """Clone + translate multiple Google files in parallel."""
    results: list[dict] = [{}] * len(file_ids)

    def _process(idx: int, fid: str):
        def _prog(msg):
            progress(f"[{idx + 1}/{len(file_ids)}] {msg}")
        results[idx] = translate_google_file(fid, target_language, sheet_name, _prog)

    with ThreadPoolExecutor(max_workers=min(len(file_ids), FILE_WORKERS)) as pool:
        futures = {pool.submit(_process, i, fid): i for i, fid in enumerate(file_ids)}
        for fut in as_completed(futures):
            fut.result()

    succeeded = sum(1 for r in results if r.get("ok"))
    return {
        "total": len(file_ids),
        "succeeded": succeeded,
        "failed": len(file_ids) - succeeded,
        "results": results,
    }
