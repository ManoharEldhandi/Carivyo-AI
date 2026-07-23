from __future__ import annotations

import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.security import sanitize_untrusted_text
from app.utils import normalize_space, unique


SUPPORTED_EXTENSIONS = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".tex": "tex",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
}

SECTION_NAMES = {
    "experience": "experience",
    "work experience": "experience",
    "professional experience": "experience",
    "work history": "experience",
    "career history": "experience",
    "internships": "experience",
    "employment": "experience",
    "projects": "projects",
    "selected projects": "projects",
    "personal projects": "projects",
    "academic projects": "projects",
    "education": "education",
    "skills": "skills",
    "technical skills": "skills",
    "core competencies": "skills",
    "technologies": "skills",
    "certifications": "certifications",
    "certificates": "certifications",
    "licenses & certifications": "certifications",
    "licenses and certifications": "certifications",
    "achievements": "achievements",
    "awards": "achievements",
    "awards & honors": "achievements",
    "awards and honors": "achievements",
    "honors": "achievements",
    "summary": "summary",
    "profile": "summary",
    "professional summary": "summary",
    "career summary": "summary",
    "executive summary": "summary",
    "about me": "summary",
    "volunteer": "volunteer",
    "volunteering": "volunteer",
    "volunteer experience": "volunteer",
    "leadership": "leadership",
    "leadership experience": "leadership",
    "publications": "publications",
    "research & publications": "publications",
    "research and publications": "publications",
    "languages": "languages",
    "spoken languages": "languages",
}

SKILL_TERMS = [
    "Python",
    "Java",
    "JavaScript",
    "TypeScript",
    "React",
    "Next.js",
    "Node.js",
    "FastAPI",
    "Django",
    "Flask",
    "Spring Boot",
    "SQL",
    "PostgreSQL",
    "MySQL",
    "SQLite",
    "MongoDB",
    "Redis",
    "AWS",
    "Azure",
    "GCP",
    "Docker",
    "Kubernetes",
    "Terraform",
    "Git",
    "Linux",
    "REST",
    "GraphQL",
    "Machine Learning",
    "Deep Learning",
    "PyTorch",
    "TensorFlow",
    "scikit-learn",
    "LLM",
    "RAG",
    "LangChain",
    "MCP",
    "C++",
    "C#",
    "Go",
    "Rust",
    "HTML",
    "CSS",
    "Playwright",
    "Selenium",
    "Jenkins",
    "GitHub Actions",
]

ROLE_FAMILIES = {
    "Backend Engineer": ["backend", "api", "fastapi", "django", "spring", "microservice"],
    "Full-stack Engineer": ["full stack", "full-stack", "react", "node.js", "frontend"],
    "AI/LLM Engineer": ["llm", "rag", "langchain", "prompt", "agent", "generative ai"],
    "Machine Learning Engineer": [
        "machine learning",
        "deep learning",
        "pytorch",
        "tensorflow",
        "model",
    ],
    "Platform Engineer": ["platform", "kubernetes", "terraform", "devops", "infrastructure"],
    "Software Engineer": ["software engineer", "developer", "programming", "computer science"],
    "QA Automation Engineer": ["playwright", "selenium", "automation testing", "sdet"],
}


class ExtractionError(ValueError):
    pass


def detect_kind(filename: str, content: bytes) -> str:
    extension = Path(filename).suffix.lower()
    kind = SUPPORTED_EXTENSIONS.get(extension)
    if not kind:
        raise ExtractionError("Supported formats are PDF, DOCX, TeX, Markdown, and text")
    if kind == "pdf" and not content.startswith(b"%PDF"):
        raise ExtractionError("The uploaded file is not a valid PDF")
    if kind == "docx":
        from io import BytesIO

        try:
            with zipfile.ZipFile(BytesIO(content)) as archive:
                if "[Content_Types].xml" not in archive.namelist():
                    raise ExtractionError("The uploaded file is not a valid DOCX")
        except zipfile.BadZipFile as exc:
            raise ExtractionError("The uploaded file is not a valid DOCX") from exc
    return kind


def extract_in_subprocess(path: Path, kind: str, timeout_seconds: int = 20) -> str:
    worker = Path(__file__).resolve().parents[1] / "workers" / "extract_resume.py"
    result = subprocess.run(
        [sys.executable, "-I", str(worker), str(path), kind],
        cwd=str(path.parent),
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"},
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ExtractionError("Resume extraction returned invalid output") from exc
    if result.returncode != 0 or payload.get("error"):
        raise ExtractionError(payload.get("error") or "Resume extraction failed")
    text = sanitize_untrusted_text(payload.get("text", ""))
    if len(text) < 40:
        raise ExtractionError("Not enough readable text was found in the resume")
    return text


def split_sections(text: str) -> Dict[str, List[Tuple[int, str, bool]]]:
    sections: Dict[str, List[Tuple[int, str, bool]]] = {"header": []}
    current = "header"
    for index, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        bullet = bool(re.match(r"^[•●▪◦●\-*]\s+", stripped))
        line = normalize_space(stripped.strip("•●▪◦\t -*"))
        if not line:
            continue
        heading_key = normalize_space(line.casefold().rstrip(":"))
        if heading_key in SECTION_NAMES and len(line) <= 40:
            current = SECTION_NAMES[heading_key]
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append((index, line, bullet))
    return sections


def _logical_claims(
    category: str,
    lines: List[Tuple[int, str, bool]],
) -> List[Tuple[str, str]]:
    """Merge wrapped PDF lines while preserving entry and bullet boundaries."""

    if not lines:
        return []
    if category == "summary":
        return [
            (
                f"line:{lines[0][0]}-{lines[-1][0]}",
                normalize_space(" ".join(item[1] for item in lines)),
            )
        ]

    result: List[Tuple[str, str]] = []
    active_start = 0
    active_end = 0
    active_text = ""
    active_is_bullet = False

    def flush() -> None:
        nonlocal active_start, active_end, active_text, active_is_bullet
        if active_text:
            location = (
                f"line:{active_start}"
                if active_start == active_end
                else f"line:{active_start}-{active_end}"
            )
            result.append((location, normalize_space(active_text)))
        active_start = active_end = 0
        active_text = ""
        active_is_bullet = False

    for line_number, line, is_bullet in lines:
        if is_bullet:
            flush()
            active_start = active_end = line_number
            active_text = line
            active_is_bullet = True
            continue
        entry_boundary = (
            category == "projects"
            and bool(
                re.search(r"(?:github\.com/|gitlab\.com/|https?://)", line, re.IGNORECASE)
            )
        ) or (
            category == "experience"
            and bool(
                re.search(
                    r"\b(?:19|20)\d{2}\b.*(?:present|current|\b(?:19|20)\d{2}\b)",
                    line,
                    re.IGNORECASE,
                )
            )
        )
        if active_is_bullet and not entry_boundary:
            active_end = line_number
            active_text = f"{active_text} {line}"
            continue
        flush()
        active_start = active_end = line_number
        active_text = line
    flush()
    return result


def build_evidence(text: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    sections = split_sections(text)
    claims: List[Dict[str, Any]] = []
    for category, lines in sections.items():
        for source_location, line in _logical_claims(category, lines):
            if len(line) < 12 or len(line) > 700:
                continue
            if category == "header" and (
                "@" in line
                or re.search(r"\+?\d[\d\s()-]{7,}", line)
                or line.startswith(("http://", "https://", "www."))
            ):
                continue
            claims.append(
                {
                    "category": category if category != "header" else "identity",
                    "text": line,
                    "source_location": source_location,
                    "confidence": 1.0,
                }
            )
    claims = claims[:120]

    full_lower = text.casefold()
    skills = [
        skill
        for skill in SKILL_TERMS
        if re.search(r"(?<!\w)" + re.escape(skill.casefold()) + r"(?!\w)", full_lower)
    ]
    role_scores = {
        role: sum(full_lower.count(keyword) for keyword in keywords)
        for role, keywords in ROLE_FAMILIES.items()
    }
    role_tracks = [
        role
        for role, score in sorted(role_scores.items(), key=lambda item: item[1], reverse=True)
        if score > 0
    ][:4]

    lines = [normalize_space(line) for line in text.splitlines() if normalize_space(line)]
    name = ""
    for line in lines[:8]:
        if (
            2 <= len(line.split()) <= 5
            and "@" not in line
            and not re.search(r"\d", line)
            and len(line) <= 70
        ):
            name = line
            break
    email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    phone_match = re.search(r"(?:\+\d{1,3}[-\s]?)?[\d()\s-]{8,}\d", text)
    raw_links = re.findall(
        r"(?:(?:https?://|www\.)[^\s|,)·]+|"
        r"(?:github\.com|linkedin\.com/in|[A-Za-z0-9.-]+\.github\.io)"
        r"/[^\s|,)·]+)",
        text,
        flags=re.IGNORECASE,
    )
    links = unique(
        [link if link.startswith(("http://", "https://")) else f"https://{link}" for link in raw_links]
    )

    highlights = [
        claim["text"]
        for claim in claims
        if claim["category"] in {"experience", "projects", "achievements"}
    ][:5]
    summary = {
        "name": name or "Candidate",
        "email": email_match.group(0) if email_match else None,
        "phone": normalize_space(phone_match.group(0)) if phone_match else None,
        "links": links[:8],
        "skills": skills[:30],
        "role_tracks": role_tracks or ["Software Engineer"],
        "highlights": highlights,
        "claim_count": len(claims),
    }
    return claims, summary
