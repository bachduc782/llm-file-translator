"""Google Docsユーティリティ。"""

from __future__ import annotations

import json
import re

from src.auth.google_auth import build_docs_service


def _parse_doc_id(url_or_id: str) -> str:
    m = re.search(r"/document/d/([a-zA-Z0-9_-]+)", url_or_id)
    return m.group(1) if m else url_or_id.strip()


def _extract_text_from_element(element: dict) -> str:
    if "paragraph" in element:
        return "".join(
            pe.get("textRun", {}).get("content", "")
            for pe in element["paragraph"].get("elements", [])
        )
    if "table" in element:
        lines = []
        for row in element["table"].get("tableRows", []):
            for cell in row.get("tableCells", []):
                for sub in cell.get("content", []):
                    lines.append(_extract_text_from_element(sub))
        return "\n".join(lines)
    return ""


def read_google_doc(url: str) -> str:
    """Read content from a Google Doc. Returns JSON string."""
    svc = build_docs_service()
    doc_id = _parse_doc_id(url)
    try:
        doc = svc.documents().get(documentId=doc_id).execute()
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)

    body_content = doc.get("body", {}).get("content", [])
    paragraphs = [
        _extract_text_from_element(e).rstrip("\n")
        for e in body_content
    ]
    paragraphs = [p for p in paragraphs if p.strip()]

    return json.dumps({
        "doc_id": doc_id,
        "title": doc.get("title", ""),
        "paragraph_count": len(paragraphs),
        "paragraphs": paragraphs,
    }, ensure_ascii=False)
