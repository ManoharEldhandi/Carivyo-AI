from __future__ import annotations

import re
import shutil
import subprocess
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Sequence

from pypdf import PdfReader


PDF_VALIDATION_VERSION = "carivyo-pdf-parsers-1.0.0"


def _normalize_tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9+#.-]+", value.casefold())


def _fields(value: str) -> Dict[str, Any]:
    lowered = value.casefold()
    headings = [
        heading
        for heading in (
            "summary",
            "experience",
            "projects",
            "skills",
            "education",
            "certifications",
            "achievements",
            "leadership",
            "publications",
            "languages",
        )
        if re.search(rf"(?m)^\s*{re.escape(heading)}\s*:?\s*$", lowered)
    ]
    return {
        "character_count": len(value),
        "token_count": len(_normalize_tokens(value)),
        "email_count": len(
            re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", value, re.I)
        ),
        "phone_count": len(
            re.findall(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)", value)
        ),
        "headings": headings,
    }


def _pdftotext(pdf_path: Path) -> tuple[str, str | None]:
    executable = shutil.which("pdftotext")
    if not executable:
        return "", "pdftotext_unavailable"
    try:
        result = subprocess.run(
            [executable, "-layout", "-enc", "UTF-8", str(pdf_path), "-"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "", "pdftotext_failed"
    if result.returncode != 0:
        return "", "pdftotext_failed"
    return result.stdout, None


def validate_pdf_parsers(
    pdf_path: Path,
    *,
    pypdf_text: str | None = None,
    expected_sections: Sequence[str] = (),
) -> Dict[str, Any]:
    if pypdf_text is None:
        reader = PdfReader(str(pdf_path))
        pypdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    poppler_text, poppler_error = _pdftotext(pdf_path)
    parser_texts = {"pypdf": pypdf_text, "poppler_layout": poppler_text}
    available = {
        name: value for name, value in parser_texts.items() if value.strip()
    }
    pypdf_tokens = _normalize_tokens(pypdf_text)
    poppler_tokens = _normalize_tokens(poppler_text)
    token_sequence_agreement = (
        SequenceMatcher(None, pypdf_tokens, poppler_tokens).ratio()
        if pypdf_tokens and poppler_tokens
        else 0.0
    )
    pypdf_set = set(pypdf_tokens)
    poppler_set = set(poppler_tokens)
    token_set_agreement = (
        len(pypdf_set & poppler_set) / len(pypdf_set | poppler_set)
        if pypdf_set or poppler_set
        else 0.0
    )
    parser_fields = {name: _fields(value) for name, value in available.items()}
    required_sections = {str(item).casefold() for item in expected_sections}
    missing_by_parser = {
        name: sorted(required_sections - set(fields["headings"]))
        for name, fields in parser_fields.items()
    }
    blocking_reasons = []
    if not pypdf_text.strip():
        blocking_reasons.append("pypdf_empty")
    if not poppler_text.strip():
        blocking_reasons.append(poppler_error or "poppler_empty")
    if len(available) >= 2 and token_set_agreement < 0.72:
        blocking_reasons.append("parser_token_coverage_disagrees")
    if any(missing for missing in missing_by_parser.values()):
        blocking_reasons.append("required_section_missing_from_parser")
    review_reasons = []
    if len(available) >= 2 and token_sequence_agreement < 0.72:
        review_reasons.append("reading_order_disagrees")
    status = "blocked" if blocking_reasons else "review" if review_reasons else "strong"
    consensus = round(
        (token_set_agreement * 0.65 + token_sequence_agreement * 0.35) * 100,
        1,
    )
    return {
        "version": PDF_VALIDATION_VERSION,
        "status": status,
        "consensus_score": consensus,
        "token_set_agreement": round(token_set_agreement, 4),
        "token_sequence_agreement": round(token_sequence_agreement, 4),
        "available_parsers": sorted(available),
        "parsers": parser_fields,
        "missing_sections_by_parser": missing_by_parser,
        "blocking_reasons": blocking_reasons,
        "review_reasons": review_reasons,
        "note": (
            "The final PDF was independently extracted with pypdf and Poppler; "
            "field presence and token/read-order agreement are reported separately."
        ),
    }


__all__ = ["PDF_VALIDATION_VERSION", "validate_pdf_parsers"]
