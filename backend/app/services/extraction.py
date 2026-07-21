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
    "employment": "experience",
    "projects": "projects",
    "selected projects": "projects",
    "education": "education",
    "skills": "skills",
    "technical skills": "skills",
    "certifications": "certifications",
    "achievements": "achievements",
    "awards": "achievements",
    "summary": "summary",
    "profile": "summary",
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


def split_sections(text: str) -> Dict[str, List[Tuple[int, str]]]:
    sections: Dict[str, List[Tuple[int, str]]] = {"header": []}
    current = "header"
    for index, raw_line in enumerate(text.splitlines(), start=1):
        line = normalize_space(raw_line.strip("•●▪◦\t "))
        if not line:
            continue
        heading_key = line.casefold().rstrip(":")
        if heading_key in SECTION_NAMES and len(line) <= 40:
            current = SECTION_NAMES[heading_key]
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append((index, line))
    return sections


def build_evidence(text: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    sections = split_sections(text)
    claims: List[Dict[str, Any]] = []
    for category, lines in sections.items():
        for line_number, line in lines:
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
                    "source_location": f"line:{line_number}",
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
    links = unique(re.findall(r"https?://[^\s|,)]+", text))

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
