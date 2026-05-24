"""Local file translator — Excel (.xlsx), Word (.docx), plain text (.txt)."""

from __future__ import annotations

import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.tools.translate_google import (
    _translate_list, _is_translatable, _chunks,
    TRANSLATE_CHUNK, FILE_WORKERS,
    Progress, _noop,
)

# Local files have no Google API rate limit — use more workers to saturate
# the LLM rate limit (40 req/min → need ~7+ concurrent workers at 10s/call)
LOCAL_WORKERS = 8
from src.tools.google_drive import _LANG_SUFFIX

SUPPORTED_EXT = {".xlsx", ".docx", ".txt"}


def _clone_path(file_path: str, target_language: str) -> str:
    base, ext = os.path.splitext(file_path)
    suffix = _LANG_SUFFIX.get(target_language.lower(), target_language[:2].lower())
    return f"{base}-{suffix}{ext}"


# ── Excel (.xlsx) ──────────────────────────────────────────────────────────────

def _translate_xlsx(file_path: str, sheet_name: str, target_language: str, progress: Progress) -> int:
    import openpyxl

    wb = openpyxl.load_workbook(file_path)

    if sheet_name:
        if sheet_name not in wb.sheetnames:
            raise ValueError(f"Sheet '{sheet_name}' not found. Available: {wb.sheetnames}")
        ws_list = [wb[sheet_name]]
    else:
        ws_list = [wb[sn] for sn in wb.sheetnames]

    # Phase 1: scan
    all_cells: list[tuple[str, int, int, str]] = []
    total_raw = 0
    for ws in ws_list:
        progress(f"Scanning [{ws.title}]…")
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.strip():
                    total_raw += 1
                    if _is_translatable(cell.value):
                        all_cells.append((ws.title, cell.row, cell.column, cell.value))

    skipped = total_raw - len(all_cells)
    progress(
        f"Found {len(all_cells)} cells to translate across {len(ws_list)} sheet(s)"
        + (f" ({skipped} skipped)" if skipped else "")
    )
    if not all_cells:
        return 0

    # Phase 2: translate
    translated_map: dict[tuple[str, int, int], str] = {}
    lock         = threading.Lock()
    done         = 0
    all_chunks   = list(_chunks(all_cells, TRANSLATE_CHUNK))
    total_chunks = len(all_chunks)

    def _worker(chunk: list, idx: int):
        nonlocal done
        progress(f"[{idx}/{total_chunks}] Calling LLM for {len(chunk)} cells…")

        def _on_retry(attempt, total_r, exc, wait):
            progress(f"RETRY [{idx}/{total_chunks}] attempt {attempt}/{total_r} (wait {wait}s) — {exc}")

        texts      = [t for _, _, _, t in chunk]
        translated = _translate_list(texts, target_language, on_retry=_on_retry)
        with lock:
            for (sn, r, c, orig), new in zip(chunk, translated):
                if orig != new:
                    translated_map[(sn, r, c)] = new
            done += len(chunk)
            progress(f"[{idx}/{total_chunks}] Done — {done}/{len(all_cells)} cells translated")

    with ThreadPoolExecutor(max_workers=LOCAL_WORKERS) as pool:
        futures = {pool.submit(_worker, chunk, i + 1): i for i, chunk in enumerate(all_chunks)}
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                progress(f"ERROR chunk {futures[fut] + 1}: {e}")

    # Phase 3: write back
    for (sn, r, c), new in translated_map.items():
        wb[sn].cell(row=r, column=c).value = new

    progress("Saving file…")
    wb.save(file_path)
    return len(all_cells)


# ── Word (.docx) ───────────────────────────────────────────────────────────────

def _set_para_text(para, new_text: str):
    """Replace paragraph text, keeping first run's formatting."""
    if not para.runs:
        para.add_run(new_text)
        return
    para.runs[0].text = new_text
    for run in para.runs[1:]:
        run.text = ""


def _iter_doc_paragraphs(doc):
    """Yield all paragraphs from body and tables."""
    yield from doc.paragraphs
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs


def _translate_docx(file_path: str, target_language: str, progress: Progress) -> int:
    from docx import Document

    doc = Document(file_path)

    para_items: list[tuple[object, str]] = [
        (para, para.text.strip())
        for para in _iter_doc_paragraphs(doc)
        if para.text.strip() and _is_translatable(para.text.strip())
    ]
    total = len(para_items)
    progress(f"Found {total} paragraphs to translate")
    if not total:
        return 0

    translated_results: dict[int, str] = {}
    lock         = threading.Lock()
    done         = 0
    indexed      = [(i, text) for i, (_, text) in enumerate(para_items)]
    all_chunks   = list(_chunks(indexed, TRANSLATE_CHUNK))
    total_chunks = len(all_chunks)

    def _worker(chunk: list, idx: int):
        nonlocal done
        progress(f"[{idx}/{total_chunks}] Calling LLM for {len(chunk)} paragraphs…")

        def _on_retry(attempt, total_r, exc, wait):
            progress(f"RETRY [{idx}/{total_chunks}] attempt {attempt}/{total_r} (wait {wait}s) — {exc}")

        texts      = [t for _, t in chunk]
        translated = _translate_list(texts, target_language, on_retry=_on_retry)
        with lock:
            for (i, orig), new in zip(chunk, translated):
                if orig != new:
                    translated_results[i] = new
            done += len(chunk)
            progress(f"[{idx}/{total_chunks}] Done — {done}/{total} paragraphs translated")

    with ThreadPoolExecutor(max_workers=LOCAL_WORKERS) as pool:
        futures = {pool.submit(_worker, chunk, i + 1): i for i, chunk in enumerate(all_chunks)}
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                progress(f"ERROR chunk {futures[fut] + 1}: {e}")

    for i, new_text in translated_results.items():
        _set_para_text(para_items[i][0], new_text)

    progress("Saving file…")
    doc.save(file_path)
    return total


# ── Plain text (.txt) ──────────────────────────────────────────────────────────

def _translate_txt_local(file_path: str, target_language: str, progress: Progress) -> int:
    with open(file_path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    indexed = [
        (i, line.rstrip("\r\n"))
        for i, line in enumerate(lines)
        if line.strip() and _is_translatable(line.strip())
    ]
    total = len(indexed)
    progress(f"Found {total} lines to translate")
    if not total:
        return 0

    translated_map: dict[int, str] = {}
    lock         = threading.Lock()
    done         = 0
    all_chunks   = list(_chunks(indexed, TRANSLATE_CHUNK))
    total_chunks = len(all_chunks)

    def _worker(chunk: list, idx: int):
        nonlocal done
        progress(f"[{idx}/{total_chunks}] Calling LLM for {len(chunk)} lines…")

        def _on_retry(attempt, total_r, exc, wait):
            progress(f"RETRY [{idx}/{total_chunks}] attempt {attempt}/{total_r} (wait {wait}s) — {exc}")

        texts      = [t for _, t in chunk]
        translated = _translate_list(texts, target_language, on_retry=_on_retry)
        with lock:
            for (i, _), new in zip(chunk, translated):
                translated_map[i] = new
            done += len(chunk)
            progress(f"[{idx}/{total_chunks}] Done — {done}/{total} lines translated")

    with ThreadPoolExecutor(max_workers=LOCAL_WORKERS) as pool:
        futures = {pool.submit(_worker, chunk, i + 1): i for i, chunk in enumerate(all_chunks)}
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                progress(f"ERROR chunk {futures[fut] + 1}: {e}")

    result_lines = list(lines)
    for i, new_text in translated_map.items():
        orig    = lines[i]
        ending  = "\r\n" if orig.endswith("\r\n") else "\n"
        result_lines[i] = new_text + ending

    progress("Saving file…")
    with open(file_path, "w", encoding="utf-8") as f:
        f.writelines(result_lines)
    return total


# ── Public API ─────────────────────────────────────────────────────────────────

def translate_local_file(
    file_path: str,
    target_language: str,
    sheet_name: str = "",
    progress: Progress = _noop,
) -> dict:
    """Clone + translate a single local file. Returns result dict."""
    if not os.path.isfile(file_path):
        return {"error": f"File not found: {file_path}"}

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in SUPPORTED_EXT:
        return {"error": f"Unsupported type: {ext}. Supported: {', '.join(sorted(SUPPORTED_EXT))}"}

    clone = _clone_path(file_path, target_language)
    clone_name    = os.path.basename(clone)
    original_name = os.path.basename(file_path)

    progress("Cloning file…")
    try:
        shutil.copy2(file_path, clone)
    except Exception as e:
        return {"error": f"Cannot clone file: {e}"}
    progress(f"Clone: {original_name} → {clone_name}")

    try:
        if ext == ".xlsx":
            total = _translate_xlsx(clone, sheet_name, target_language, progress)
            return {"ok": True, "clone_name": clone_name, "clone_path": clone,
                    "file_type": "xlsx", "cells_translated": total}

        elif ext == ".docx":
            total = _translate_docx(clone, target_language, progress)
            return {"ok": True, "clone_name": clone_name, "clone_path": clone,
                    "file_type": "docx", "paragraphs_translated": total}

        else:  # .txt
            total = _translate_txt_local(clone, target_language, progress)
            return {"ok": True, "clone_name": clone_name, "clone_path": clone,
                    "file_type": "txt", "lines_translated": total}

    except Exception as e:
        return {"error": str(e), "clone_name": clone_name, "clone_path": clone}


def translate_local_files(
    file_paths: list[str],
    target_language: str,
    sheet_name: str = "",
    progress: Progress = _noop,
) -> dict:
    """Clone + translate multiple local files in parallel."""
    results: list[dict] = [{}] * len(file_paths)

    def _process(idx: int, fp: str):
        def _prog(msg):
            progress(f"[{idx + 1}/{len(file_paths)}] {msg}")
        results[idx] = translate_local_file(fp, target_language, sheet_name, _prog)

    with ThreadPoolExecutor(max_workers=min(len(file_paths), FILE_WORKERS)) as pool:
        futures = {pool.submit(_process, i, fp): i for i, fp in enumerate(file_paths)}
        for fut in as_completed(futures):
            fut.result()

    succeeded = sum(1 for r in results if r.get("ok"))
    return {
        "total": len(file_paths),
        "succeeded": succeeded,
        "failed": len(file_paths) - succeeded,
        "results": results,
    }
