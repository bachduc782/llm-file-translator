"""ローカルファイル翻訳エンジン — Excel (.xlsx)、Word (.docx)、テキスト (.txt)。"""

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

# ローカルファイルはGoogle APIレート制限なし — ワーカー数=レート上限に設定
# レートリミッタースロットが空いた瞬間に常にワーカーが待機している状態にする
LOCAL_WORKERS = 40
from src.tools.google_drive import _LANG_SUFFIX

SUPPORTED_EXT = {".xlsx", ".docx", ".txt"}


def _clone_path(file_path: str, target_language: str) -> str:
    base, ext = os.path.splitext(file_path)
    suffix = _LANG_SUFFIX.get(target_language.lower(), target_language[:2].lower())
    return f"{base}-{suffix}{ext}"


# ── Excel (.xlsx) ──────────────────────────────────────────────────────────────

def _translate_xlsx(file_path: str, sheet_name: str, target_language: str, progress: Progress) -> int:
    import openpyxl
    from collections import Counter

    # data_only=True: 数式セルは計算済みの値として読み込む
    wb         = openpyxl.load_workbook(file_path, data_only=True)
    wb_formula = openpyxl.load_workbook(file_path)

    if sheet_name:
        if sheet_name not in wb.sheetnames:
            raise ValueError(f"シート '{sheet_name}' が見つかりません。利用可能: {wb.sheetnames}")
        ws_list = [wb[sheet_name]]
    else:
        ws_list = [wb[sn] for sn in wb.sheetnames]

    # フェーズ1：スキャン
    all_cells: list[tuple[str, int, int, str]] = []
    total_raw = 0
    for ws in ws_list:
        ws_f = wb_formula[ws.title]
        progress(f"スキャン中 [{ws.title}]…")
        uncached_formulas = 0
        for row in ws.iter_rows():
            for cell in row:
                v = cell.value
                if not isinstance(v, str):
                    if v is None:
                        fv = ws_f.cell(cell.row, cell.column).value
                        if isinstance(fv, str) and fv.startswith("="):
                            uncached_formulas += 1
                    continue
                v = v.strip()
                if not v:
                    continue
                total_raw += 1
                if _is_translatable(v):
                    all_cells.append((ws.title, cell.row, cell.column, v))
        if uncached_formulas:
            progress(
                f"[{ws.title}] ⚠ {uncached_formulas}件の数式セルはキャッシュなし"
                "（Excelで一度開いて保存してください）"
            )

    skipped = total_raw - len(all_cells)
    progress(
        f"{len(ws_list)}シートで{len(all_cells)}セルを翻訳します"
        + (f" ({skipped}件スキップ)" if skipped else "")
    )
    if not all_cells:
        return 0

    # フェーズ2：dedup
    texts  = [t for _, _, _, t in all_cells]
    counts = Counter(texts)
    unique = list(dict.fromkeys(texts))
    dupes  = len(texts) - len(unique)
    if dupes:
        progress(f"{len(unique)}件のユニークテキストを翻訳 ({dupes}件重複スキップ)")
        for text, cnt in sorted(counts.items(), key=lambda x: -x[1]):
            if cnt > 1:
                preview = text[:60].replace("\n", "↵")
                progress(f"  重複 x{cnt}: {preview}{'…' if len(text) > 60 else ''}")

    # フェーズ3：翻訳（uniqueのみ）
    cache        : dict[str, str] = {}
    lock         = threading.Lock()
    done         = 0
    all_chunks   = list(_chunks(list(enumerate(unique)), TRANSLATE_CHUNK))
    total_chunks = len(all_chunks)

    def _worker(chunk: list, idx: int):
        nonlocal done
        progress(f"[{idx}/{total_chunks}] LLMを呼び出し中 ({len(chunk)}件)…")

        def _on_retry(attempt, total_r, exc, wait):
            progress(f"リトライ [{idx}/{total_chunks}] 試行 {attempt}/{total_r} (待機 {wait}秒) — {exc}")

        texts_chunk = [t for _, t in chunk]
        translated  = _translate_list(texts_chunk, target_language, on_retry=_on_retry)
        with lock:
            for (_, orig), new in zip(chunk, translated):
                cache[orig] = new
            done += len(chunk)
            progress(f"[{idx}/{total_chunks}] 完了 — {done}/{len(unique)}件翻訳済み")

    with ThreadPoolExecutor(max_workers=LOCAL_WORKERS) as pool:
        futures = {pool.submit(_worker, chunk, i + 1): i for i, chunk in enumerate(all_chunks)}
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                progress(f"ERROR チャンク {futures[fut] + 1}: {e}")

    # フェーズ4：書き戻し
    unchanged = 0
    for sn, r, c, orig in all_cells:
        new = cache.get(orig, orig)
        if orig != new:
            wb[sn].cell(row=r, column=c).value = new
        else:
            unchanged += 1
    if unchanged:
        progress(f"⚠ {unchanged}件はLLMが同一テキストを返したため未更新")

    progress("ファイルを保存中…")
    wb.save(file_path)
    return len(all_cells)


# ── Word (.docx) ───────────────────────────────────────────────────────────────

def _set_para_text(para, new_text: str):
    """段落テキストを置換する。先頭ランのフォーマットを維持。"""
    if not para.runs:
        para.add_run(new_text)
        return
    para.runs[0].text = new_text
    for run in para.runs[1:]:
        run.text = ""


def _iter_doc_paragraphs(doc):
    """本文とテーブルから全段落を生成する。"""
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
    progress(f"{total}段落を翻訳します")
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
        progress(f"[{idx}/{total_chunks}] LLMを呼び出し中 ({len(chunk)}段落)…")

        def _on_retry(attempt, total_r, exc, wait):
            progress(f"リトライ [{idx}/{total_chunks}] 試行 {attempt}/{total_r} (待機 {wait}秒) — {exc}")

        texts      = [t for _, t in chunk]
        translated = _translate_list(texts, target_language, on_retry=_on_retry)
        with lock:
            for (i, orig), new in zip(chunk, translated):
                if orig != new:
                    translated_results[i] = new
            done += len(chunk)
            progress(f"[{idx}/{total_chunks}] 完了 — {done}/{total}段落翻訳済み")

    with ThreadPoolExecutor(max_workers=LOCAL_WORKERS) as pool:
        futures = {pool.submit(_worker, chunk, i + 1): i for i, chunk in enumerate(all_chunks)}
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                progress(f"ERROR チャンク {futures[fut] + 1}: {e}")

    for i, new_text in translated_results.items():
        _set_para_text(para_items[i][0], new_text)

    progress("ファイルを保存中…")
    doc.save(file_path)
    return total


# ── プレーンテキスト (.txt) ────────────────────────────────────────────────────

def _translate_txt_local(file_path: str, target_language: str, progress: Progress) -> int:
    with open(file_path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    indexed = [
        (i, line.rstrip("\r\n"))
        for i, line in enumerate(lines)
        if line.strip() and _is_translatable(line.strip())
    ]
    total = len(indexed)
    progress(f"{total}行を翻訳します")
    if not total:
        return 0

    translated_map: dict[int, str] = {}
    lock         = threading.Lock()
    done         = 0
    all_chunks   = list(_chunks(indexed, TRANSLATE_CHUNK))
    total_chunks = len(all_chunks)

    def _worker(chunk: list, idx: int):
        nonlocal done
        progress(f"[{idx}/{total_chunks}] LLMを呼び出し中 ({len(chunk)}行)…")

        def _on_retry(attempt, total_r, exc, wait):
            progress(f"リトライ [{idx}/{total_chunks}] 試行 {attempt}/{total_r} (待機 {wait}秒) — {exc}")

        texts      = [t for _, t in chunk]
        translated = _translate_list(texts, target_language, on_retry=_on_retry)
        with lock:
            for (i, _), new in zip(chunk, translated):
                translated_map[i] = new
            done += len(chunk)
            progress(f"[{idx}/{total_chunks}] 完了 — {done}/{total}行翻訳済み")

    with ThreadPoolExecutor(max_workers=LOCAL_WORKERS) as pool:
        futures = {pool.submit(_worker, chunk, i + 1): i for i, chunk in enumerate(all_chunks)}
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                progress(f"ERROR チャンク {futures[fut] + 1}: {e}")

    result_lines = list(lines)
    for i, new_text in translated_map.items():
        orig    = lines[i]
        ending  = "\r\n" if orig.endswith("\r\n") else "\n"
        result_lines[i] = new_text + ending

    progress("ファイルを保存中…")
    with open(file_path, "w", encoding="utf-8") as f:
        f.writelines(result_lines)
    return total


# ── 公開API ───────────────────────────────────────────────────────────────────

def translate_local_file(
    file_path: str,
    target_language: str,
    sheet_name: str = "",
    progress: Progress = _noop,
) -> dict:
    """ローカルファイルを1つ複製して翻訳する。結果dictを返す。"""
    if not os.path.isfile(file_path):
        return {"error": f"ファイルが見つかりません: {file_path}"}

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in SUPPORTED_EXT:
        return {"error": f"未対応の形式: {ext}。対応形式: {', '.join(sorted(SUPPORTED_EXT))}"}

    clone = _clone_path(file_path, target_language)
    clone_name    = os.path.basename(clone)
    original_name = os.path.basename(file_path)

    progress("ファイルを複製中…")
    try:
        shutil.copy2(file_path, clone)
    except Exception as e:
        return {"error": f"ファイルを複製できません: {e}"}
    progress(f"複製完了: {original_name} → {clone_name}")

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
    """複数のローカルファイルを並列で複製・翻訳する。"""
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
