"""並列Googleファイル翻訳エンジン — Sheets、Docs、プレーンテキスト対応。"""

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
TRANSLATE_CHUNK = 20   # LLM呼び出し1回あたりの最大アイテム数
CHUNK_CHAR_MAX  = 2000 # 1チャンクあたりの最大文字数（長いセルの切り詰めを防ぐ）
SHEET_WORKERS   = 40   # 並列LLMワーカー数 — レートリミッター（40回/分）が実際の制御者
FILE_WORKERS    = 1    # 複数ファイルの並列処理数

Progress = Callable[[str], None]

# このパターンに一致するセルは翻訳不要
_RE_SKIP = re.compile(
    r'^[\d\s,.\-+%/()\[\]{}:;*|]+$'   # 数字・記号のみ
    r'|^https?://'                      # URL
    r'|^[a-zA-Z0-9._%+\-]+@\S+'        # メールアドレス
    r'|^\d{4}[-/]\d{2}[-/]\d{2}',      # ISO日付 — 2024-01-01
)


def _is_translatable(text: str) -> bool:
    t = text.strip()
    return len(t) > 2 and not t.startswith("=") and not _RE_SKIP.match(t)


# ── レートリミッター ──────────────────────────────────────────────────────────

class _RateLimiter:
    """スライディングウィンドウ方式のスレッドセーフなレートリミッター。"""
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
    limiter        = _get_limiter()
    attempt        = 0
    non_429_fails  = 0
    last_exc: Exception | None = None

    while True:
        limiter.acquire()
        try:
            resp = client.chat.completions.create(
                model=cfg["model"],
                messages=[{"role": "user", "content": prompt}],
                max_tokens=8192,
            )
            raw = (resp.choices[0].message.content or "").strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw.strip())
            return raw
        except Exception as exc:
            last_exc = exc
            is_429   = "429" in str(exc) or "rate" in str(exc).lower()
            if is_429:
                # 429: 無制限リトライ — 30秒 → 60秒 → 120秒上限
                wait = min(30 * (attempt + 1), 120)
                if on_retry:
                    on_retry(attempt + 1, "∞", exc, wait)
                time.sleep(wait)
            else:
                non_429_fails += 1
                if non_429_fails >= retries:
                    raise last_exc  # type: ignore[misc]
                wait = 2 ** non_429_fails
                if on_retry:
                    on_retry(non_429_fails, retries, exc, wait)
                time.sleep(wait)
            attempt += 1


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


# ── ユーティリティ ────────────────────────────────────────────────────────────

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


def _smart_chunks(cells: list[tuple]) -> list[list[tuple]]:
    """アイテム数と文字数の両方を考慮してチャンクを分割する。"""
    chunks, cur, cur_chars = [], [], 0
    for cell in cells:
        text = cell[3]
        if cur and (len(cur) >= TRANSLATE_CHUNK or cur_chars + len(text) > CHUNK_CHAR_MAX):
            chunks.append(cur)
            cur, cur_chars = [], 0
        cur.append(cell)
        cur_chars += len(text)
    if cur:
        chunks.append(cur)
    return chunks


def _noop(*_): pass


# ── Sheets ────────────────────────────────────────────────────────────────────

def _translate_sheets(svc, sid, sheet_names, target_language, progress: Progress = _noop,
                       sheet_cols: dict | None = None) -> int:
    # ── フェーズ1：全シートを並列スキャン ────────────────────────────────────
    all_cells: list[tuple[str, int, int, str]] = []
    total_raw = 0
    scan_lock = threading.Lock()
    _cols = sheet_cols or {}

    def _scan_sheet(sheet_name: str, max_col: int):
        # httplib2はスレッドセーフではないため、スレッドごとに専用サービスを作成する
        from src.auth.google_auth import build_sheets_service as _bss
        _svc = _bss()
        col_end = _col_letter(max_col - 1)
        cells, raw = [], 0
        row_offset = 0
        while True:
            if row_offset > 0:
                progress(f"  [{sheet_name}] スキャン中… {row_offset}行目")
            range_str = f"'{sheet_name}'!A{row_offset + 1}:{col_end}{row_offset + SCAN_ROW_BATCH}"
            for attempt in range(4):
                try:
                    values = _svc.spreadsheets().values().get(
                        spreadsheetId=sid, range=range_str
                    ).execute().get("values", [])
                    break
                except Exception as exc:
                    if attempt < 3:
                        time.sleep(2 ** attempt)
                    else:
                        raise
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

    SCAN_WORKERS = min(len(sheet_names), 3)   # 上限3 — 並列TLSハンドシェイクによるSSLエラーを回避
    progress(f"{len(sheet_names)}シートを並列スキャン中…")
    with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
        scan_futures = {pool.submit(_scan_sheet, sn, _cols.get(sn, 52)): sn for sn in sheet_names}
        for fut in as_completed(scan_futures):
            sn = scan_futures[fut]
            try:
                cells, raw = fut.result()
                all_cells.extend(cells)
                total_raw += raw
                progress(f"  [{sn}] {len(cells)}セル検出")
            except Exception as e:
                import traceback as _tb
                progress(f"  [{sn}] スキャンエラー ({type(e).__name__}) (スキップ): {e}")
                progress(f"  [{sn}] {_tb.format_exc().strip()}")

    skipped = total_raw - len(all_cells)
    progress(
        f"合計: {len(all_cells)}セルを翻訳します"
        + (f" ({skipped}件スキップ)" if skipped else "")
    )

    if not all_cells:
        return 0

    # ── フェーズ2+3：翻訳して即座に書き戻し ──────────────────────────────────
    lock       = threading.Lock()
    write_lock = threading.Lock()
    done       = 0
    all_chunks   = _smart_chunks(all_cells)
    total_chunks = len(all_chunks)

    def _write_chunk(data: list, chunk_idx: int):
        """チャンクの翻訳結果を即座にSheetsへ書き込む（リトライ付き）。"""
        if not data:
            return
        with write_lock:
            for attempt in range(3):
                try:
                    svc.spreadsheets().values().batchUpdate(
                        spreadsheetId=sid,
                        body={"valueInputOption": "RAW", "data": data},
                    ).execute()
                    return
                except Exception as e:
                    if attempt < 2:
                        time.sleep(2 ** attempt)
                    else:
                        progress(f"  書き込みエラー [{chunk_idx}/{total_chunks}]: {e}")

    def _worker(chunk: list[tuple[str, int, int, str]], idx: int):
        nonlocal done
        progress(f"[{idx}/{total_chunks}] LLMを呼び出し中 ({len(chunk)}セル)…")

        def _on_retry(attempt, total, exc, wait):
            progress(f"リトライ [{idx}/{total_chunks}] 試行 {attempt}/{total} (待機 {wait}秒) — {exc}")

        texts      = [t for _, _, _, t in chunk]
        translated = _translate_list(texts, target_language, on_retry=_on_retry)

        write_data = [
            {"range": f"'{sn}'!{_col_letter(c)}{r + 1}", "values": [[new]]}
            for (sn, r, c, orig), new in zip(chunk, translated)
            if orig != new
        ]
        with lock:
            done += len(chunk)
            progress(f"[{idx}/{total_chunks}] 完了 — {done}/{len(all_cells)}セル翻訳済み")

        _write_chunk(write_data, idx)

    with ThreadPoolExecutor(max_workers=SHEET_WORKERS) as pool:
        futures = {
            pool.submit(_worker, chunk, i + 1): i
            for i, chunk in enumerate(all_chunks)
        }
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                progress(f"ERROR チャンク {futures[fut] + 1}: {e}")

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
                progress(f"{done}/{total}段落翻訳済み")
            except Exception as e:
                progress(f"段落チャンクが失敗しました、スキップ: {e}")

    return done


# ── プレーンテキスト ──────────────────────────────────────────────────────────

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
            progress(f"{done}/{total}行翻訳済み")

    with ThreadPoolExecutor(max_workers=SHEET_WORKERS) as pool:
        futures = [pool.submit(_worker, chunk) for chunk in _chunks(indexed, TRANSLATE_CHUNK)]
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                progress(f"行チャンクが失敗しました、スキップ: {e}")

    for idx, new in translated_map.items():
        all_lines[idx] = new

    upload_buf = io.BytesIO("\n".join(all_lines).encode("utf-8"))
    drive.files().update(
        fileId=file_id,
        media_body=MediaIoBaseUpload(upload_buf, mimetype="text/plain"),
        supportsAllDrives=True,
    ).execute()

    return total


# ── 公開API ───────────────────────────────────────────────────────────────────

def translate_google_file(
    file_id: str,
    target_language: str,
    sheet_name: str = "",
    progress: Progress = _noop,
) -> dict:
    """Googleファイルを1つ複製して翻訳する。結果dictを返す。"""
    try:
        from src.auth.google_auth import build_drive_service, build_sheets_service, build_docs_service
        from src.tools.google_drive import _clone_file_impl
        from src.tools.google_sheets import _parse_spreadsheet_id
        from src.tools.google_docs import _parse_doc_id

        drive = build_drive_service()

        progress("ファイルを複製中...")
        clone = _clone_file_impl(drive, file_id, target_language)
        if "error" in clone:
            return {"error": clone["error"], "original_id": file_id}

        clone_id   = clone["clone_id"]
        clone_name = clone["clone_name"]
        mime       = clone["file_type"]
        progress(f"複製完了: {clone['original_name']} → {clone_name}")

        if mime == "application/vnd.google-apps.spreadsheet":
            svc = build_sheets_service()
            sid = _parse_spreadsheet_id(clone_id)
            if sheet_name:
                sheet_names = [sheet_name]
                sheet_cols  = {sheet_name: 52}
            else:
                s_meta     = svc.spreadsheets().get(spreadsheetId=sid, fields="sheets.properties").execute()
                sheet_list = s_meta.get("sheets", [])
                sheet_names = [s["properties"]["title"] for s in sheet_list]
                sheet_cols  = {
                    s["properties"]["title"]: s["properties"]["gridProperties"].get("columnCount", 52)
                    for s in sheet_list
                }
            total = _translate_sheets(svc, sid, sheet_names, target_language, progress, sheet_cols)
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
            return {"error": f"未対応のファイル形式: {mime}", "clone_name": clone_name}

    except Exception as e:
        import traceback as _tb
        return {"error": f"{type(e).__name__}: {e}", "traceback": _tb.format_exc(), "original_id": file_id}


def translate_google_files(
    file_ids: list[str],
    target_language: str,
    sheet_name: str = "",
    progress: Progress = _noop,
) -> dict:
    """複数のGoogleファイルを並列で複製・翻訳する。"""
    results: list[dict] = [{}] * len(file_ids)

    def _process(idx: int, fid: str):
        def _prog(msg):
            progress(f"[{idx + 1}/{len(file_ids)}] {msg}")
        result = translate_google_file(fid, target_language, sheet_name, _prog)
        results[idx] = result
        if result.get("ok"):
            n = (result.get("cells_translated") or result.get("paragraphs_translated")
                 or result.get("lines_translated", 0))
            _prog(f"✓ 完了 — {result.get('clone_name', '?')} ({n}項目翻訳済み)")
        else:
            _prog(f"✗ 失敗 — {result.get('error', '?')}")

    with ThreadPoolExecutor(max_workers=min(len(file_ids), FILE_WORKERS)) as pool:
        futures = {pool.submit(_process, i, fid): i for i, fid in enumerate(file_ids)}
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                idx = futures[fut]
                progress(f"[{idx + 1}/{len(file_ids)}] 予期しないエラー: {e}")
                results[idx] = {"error": str(e)}

    succeeded = sum(1 for r in results if r.get("ok"))
    return {
        "total": len(file_ids),
        "succeeded": succeeded,
        "failed": len(file_ids) - succeeded,
        "results": results,
    }
