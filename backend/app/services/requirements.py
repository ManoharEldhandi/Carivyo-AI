from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from app.utils import stable_hash, tokenize


REQUIREMENT_VERSION = "carivyo-requirements-2.1.0"

# This vocabulary is intentionally a normalization layer, not the boundary of
# what Carivyo can understand. Unknown requirement text is retained and scored
# through field-aware lexical evidence instead of disappearing as N/A.
TECHNOLOGY_ALIASES: Mapping[str, tuple[str, ...]] = {
    "Python": ("python",),
    "Java": ("java",),
    "JavaScript": ("javascript",),
    "TypeScript": ("typescript",),
    "C++": ("c++",),
    "C#": ("c#",),
    "Go": ("golang", "go language"),
    "Rust": ("rust",),
    "Scala": ("scala",),
    "Kotlin": ("kotlin",),
    "SQL": ("sql",),
    "PostgreSQL": ("postgresql", "postgres"),
    "MySQL": ("mysql",),
    "SQLite": ("sqlite",),
    "MongoDB": ("mongodb",),
    "Redis": ("redis",),
    "Snowflake": ("snowflake",),
    "Databricks": ("databricks",),
    "dbt": ("dbt", "data build tool"),
    "FastAPI": ("fastapi",),
    "Django": ("django",),
    "Flask": ("flask",),
    "Spring Boot": ("spring boot",),
    "Node.js": ("node.js", "nodejs"),
    "React": ("react", "react.js"),
    "Next.js": ("next.js", "nextjs"),
    "Angular": ("angular",),
    "Vue": ("vue", "vue.js"),
    "REST": ("rest api", "restful", "rest apis"),
    "GraphQL": ("graphql",),
    "gRPC": ("grpc",),
    "AWS": ("aws", "amazon web services"),
    "Azure": ("azure",),
    "GCP": ("gcp", "google cloud"),
    "Docker": ("docker",),
    "Kubernetes": ("kubernetes", "k8s"),
    "Terraform": ("terraform",),
    "Linux": ("linux",),
    "Git": ("git",),
    "GitHub Actions": ("github actions",),
    "Jenkins": ("jenkins",),
    "CI/CD": ("ci/cd", "continuous integration", "continuous delivery"),
    "Kafka": ("kafka",),
    "RabbitMQ": ("rabbitmq",),
    "Airflow": ("airflow", "apache airflow"),
    "Spark": ("spark", "apache spark", "pyspark"),
    "Hadoop": ("hadoop",),
    "Machine Learning": ("machine learning",),
    "Deep Learning": ("deep learning",),
    "PyTorch": ("pytorch",),
    "TensorFlow": ("tensorflow",),
    "scikit-learn": ("scikit-learn", "sklearn"),
    "LLM": ("llm", "large language model", "large language models"),
    "RAG": ("rag", "retrieval augmented generation", "retrieval-augmented generation"),
    "LangChain": ("langchain",),
    "Hugging Face": ("hugging face", "huggingface"),
    "Selenium": ("selenium",),
    "Playwright": ("playwright",),
    "OpenAPI": ("openapi",),
    "OAuth": ("oauth", "oauth2", "oauth 2.0"),
    "Microservices": ("microservices", "microservice"),
}

SOFT_SKILL_ALIASES: Mapping[str, tuple[str, ...]] = {
    "Communication": ("communication", "communicate", "presented", "presentation"),
    "Collaboration": ("collaboration", "collaborated", "collaborative", "teamwork"),
    "Leadership": ("leadership", "led", "leading", "mentored", "managed"),
    "Problem solving": ("problem solving", "problem-solving", "troubleshooting"),
    "Ownership": ("ownership", "owned", "accountability"),
    "Adaptability": ("adaptability", "adaptable", "adapted"),
    "Mentoring": ("mentoring", "mentored", "coached"),
    "Stakeholder management": ("stakeholder management", "stakeholders"),
    "Cross-functional work": ("cross-functional", "cross functional"),
    "Time management": ("time management", "prioritization", "prioritized"),
}

_PREFERRED_MARKERS = re.compile(
    r"\b(?:preferred|nice to have|bonus|plus|advantage|desirable|ideally)\b",
    re.IGNORECASE,
)
_REQUIRED_MARKERS = re.compile(
    r"\b(?:required|must|minimum|need(?:ed)?|should have|you have|qualifications?)\b",
    re.IGNORECASE,
)
_RESPONSIBILITY_MARKERS = re.compile(
    r"\b(?:build|design|develop|create|maintain|implement|deliver|lead|own|support|"
    r"collaborate|manage|analy[sz]e|test|deploy|operate|improve|work with|responsible for)\b",
    re.IGNORECASE,
)
_EXPERIENCE_RE = re.compile(
    r"\b(?:\d+\s*(?:-|–|to)\s*\d+|\d+\+?)\s+years?\b|\byears? of experience\b",
    re.IGNORECASE,
)
_EDUCATION_RE = re.compile(
    r"\b(?:bachelor|master|ph\.?d|degree|computer science|engineering degree|education)\b",
    re.IGNORECASE,
)
_HEADING_RE = re.compile(
    r"^(?:about (?:the )?(?:role|job)|what (?:we are looking for|you(?:'|’)ll do)|"
    r"how you will fulfill your potential(?:\s*-?\s*job responsibilities)?|responsibilities|"
    r"responsibilities and qualifications|requirements|qualifications|"
    r"minimum qualifications|basic qualifications|preferred qualifications|"
    r"preferred skills|skills and experience(?: we are looking for)?|skills|"
    r"experience|who you are|the team)\s*:?$",
    re.IGNORECASE,
)
_NON_REQUIREMENT_HEADING_RE = re.compile(
    r"^(?:about (?!the (?:role|job)\b).+|company (?:overview|information)|"
    r"equal opportunity|benefits|compensation and benefits|privacy notice)\s*:?$",
    re.IGNORECASE,
)
_NON_REQUIREMENT_SEGMENT_RE = re.compile(
    r"\b(?:equal (?:employment )?opportunity|non-?discrimination|privacy notice|"
    r"data protection|reasonable accommodation|background check|recruit(?:er|ing|ment)|"
    r"applicant tracking system|candidate fraud|job scam|do not (?:send|share)|"
    r"protected characteristic)\b",
    re.IGNORECASE,
)

_MATCH_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "have",
    "in", "is", "it", "of", "on", "or", "our", "that", "the", "their", "this",
    "to", "using", "we", "with", "work", "working", "you", "your", "ability",
    "candidate", "candidates", "experience", "knowledge", "preferred", "required",
    "responsible", "role", "skills", "strong", "team",
}


@dataclass(frozen=True)
class Requirement:
    id: str
    text: str
    priority: str
    category: str
    entities: tuple[str, ...]
    source_section: str

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["entities"] = list(self.entities)
        return value


def contains_term(text: str, term: str) -> bool:
    return bool(
        re.search(
            r"(?<![A-Za-z0-9])" + re.escape(term.casefold()) + r"(?![A-Za-z0-9])",
            text.casefold(),
        )
    )


def extract_catalog_terms(
    text: str, catalog: Mapping[str, tuple[str, ...]]
) -> List[str]:
    return [
        canonical
        for canonical, aliases in catalog.items()
        if any(contains_term(text, alias) for alias in aliases)
    ]


def _meaningful_tokens(value: str) -> set[str]:
    return {
        token.rstrip("s")
        for token in tokenize(value)
        if len(token) >= 3 and token not in _MATCH_STOP_WORDS
    }


def _segments(text: str) -> Iterable[tuple[str, str]]:
    section = "general"
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line.strip(" \t-*•▪◦‣"))
        if not line:
            continue
        if _NON_REQUIREMENT_HEADING_RE.fullmatch(line):
            section = "non_requirement"
            continue
        if _HEADING_RE.fullmatch(line):
            section = line.casefold().rstrip(":")[:60]
            continue
        if section == "non_requirement":
            continue
        parts = re.split(r"(?<=[.!?;])\s+", line)
        for part in parts:
            candidate = part.strip(" ,;:-")
            if len(candidate.split()) >= 3:
                yield section, candidate[:1000]


def extract_requirements(text: str) -> List[Dict[str, Any]]:
    requirements: List[Requirement] = []
    seen: set[str] = set()
    for section, segment in _segments(text):
        normalized = re.sub(r"\s+", " ", segment).strip()
        key = normalized.casefold()
        if key in seen:
            continue
        # Careers pages often append recruiting, privacy, and fraud notices
        # without a heading. They can contain words such as "required" or
        # "experience", but are not candidate requirements and must never be
        # reported as an ATS gap or resume-tailoring demand.
        if _NON_REQUIREMENT_SEGMENT_RE.search(normalized):
            seen.add(key)
            continue
        technologies = extract_catalog_terms(normalized, TECHNOLOGY_ALIASES)
        soft_skills = extract_catalog_terms(normalized, SOFT_SKILL_ALIASES)
        has_experience = bool(_EXPERIENCE_RE.search(normalized))
        has_education = bool(_EDUCATION_RE.search(normalized))
        has_responsibility = bool(_RESPONSIBILITY_MARKERS.search(normalized))
        looks_qualified = bool(
            technologies
            or soft_skills
            or has_experience
            or has_education
            or has_responsibility
            or _REQUIRED_MARKERS.search(normalized)
            or _PREFERRED_MARKERS.search(normalized)
        )
        if not looks_qualified:
            continue
        priority = (
            "preferred"
            if _PREFERRED_MARKERS.search(normalized) or "preferred" in section
            else "required"
            if _REQUIRED_MARKERS.search(normalized)
            or "minimum" in section
            or "requirements" in section
            or "qualifications" in section
            else "responsibility"
            if has_responsibility
            else "required"
        )
        category = (
            "experience"
            if has_experience
            else "education"
            if has_education
            else "technical_skill"
            if technologies
            else "soft_skill"
            if soft_skills
            else "responsibility"
        )
        entities = tuple(dict.fromkeys([*technologies, *soft_skills]))
        # A sentence such as "Build Python and FastAPI services, deploy with
        # Docker and AWS" represents four independently matchable
        # requirements. Keeping it as one blob creates false positives when a
        # resume demonstrates only one tool in the list.
        expanded: List[tuple[str, str, tuple[str, ...]]] = []
        if len(technologies) > 1:
            for technology in technologies:
                aliases = TECHNOLOGY_ALIASES[technology]
                positions = [
                    normalized.casefold().find(alias.casefold())
                    for alias in aliases
                    if normalized.casefold().find(alias.casefold()) >= 0
                ]
                position = min(positions) if positions else 0
                prefix_matches = list(
                    _RESPONSIBILITY_MARKERS.finditer(normalized[:position])
                )
                action = prefix_matches[-1].group(0) if prefix_matches else "Use"
                expanded.append((f"{action.capitalize()} {technology}", "technical_skill", (technology,)))
        else:
            expanded.append((normalized, category, entities))

        for expanded_text, expanded_category, expanded_entities in expanded:
            expanded_key = expanded_text.casefold()
            if expanded_key in seen:
                continue
            requirement = Requirement(
                id=stable_hash(REQUIREMENT_VERSION, expanded_text)[:16],
                text=expanded_text,
                priority=priority,
                category=expanded_category,
                entities=expanded_entities,
                source_section=section,
            )
            requirements.append(requirement)
            seen.add(expanded_key)
            if len(requirements) >= 40:
                break
        seen.add(key)
        if len(requirements) >= 40:
            break
    return [item.to_dict() for item in requirements]


def analyze_job_description(text: str, title: str = "") -> Dict[str, Any]:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    requirements = extract_requirements(str(text or ""))
    word_count = len(tokenize(clean))
    required_count = sum(item["priority"] == "required" for item in requirements)
    responsibility_count = sum(
        item["priority"] == "responsibility" for item in requirements
    )
    recognized_entities = sorted(
        {entity for item in requirements for entity in item["entities"]}
    )
    section_signals = sum(
        bool(re.search(pattern, clean, re.IGNORECASE))
        for pattern in (
            r"responsibilit|what you(?:'|’)ll do",
            r"qualifications?|requirements?",
            r"preferred|nice to have|bonus",
        )
    )
    if word_count >= 45 and len(requirements) >= 3 and (
        required_count + responsibility_count >= 2
    ):
        status = "complete"
    elif word_count >= 18 and len(requirements) >= 1:
        status = "partial"
    else:
        status = "insufficient"
    confidence = (
        "high"
        if status == "complete" and section_signals >= 2
        else "medium"
        if status == "complete"
        else "low"
        if status == "partial"
        else "unavailable"
    )
    return {
        "version": REQUIREMENT_VERSION,
        "status": status,
        "confidence": confidence,
        "title": title or None,
        "character_count": len(clean),
        "word_count": word_count,
        "requirement_count": len(requirements),
        "required_count": required_count,
        "preferred_count": sum(
            item["priority"] == "preferred" for item in requirements
        ),
        "responsibility_count": responsibility_count,
        "recognized_entity_count": len(recognized_entities),
        "recognized_entities": recognized_entities,
        "section_signal_count": section_signals,
        "requirements": requirements,
        "reason": (
            "The official description contains enough responsibility and qualification evidence."
            if status == "complete"
            else "The official description is usable with limited confidence; some qualification evidence is missing."
            if status == "partial"
            else "The official source did not provide a complete responsibilities and qualifications description."
        ),
    }


def match_requirements(
    requirements: Sequence[Mapping[str, Any]],
    resume_sections: Mapping[str, Sequence[str]],
) -> Dict[str, Any]:
    field_text = {
        field: "\n".join(str(value) for value in values)
        for field, values in resume_sections.items()
    }
    demonstrated_fields = {
        key: value
        for key, value in field_text.items()
        if key in {"experience", "projects", "achievements", "leadership", "publications"}
    }
    results: List[Dict[str, Any]] = []
    for requirement in requirements:
        text = str(requirement.get("text") or "")
        requirement_tokens = _meaningful_tokens(text)
        entities = [str(item) for item in requirement.get("entities") or []]
        best_field = ""
        best_overlap: set[str] = set()
        entity_fields: Dict[str, List[str]] = {}
        for field, candidate_text in field_text.items():
            overlap = requirement_tokens & _meaningful_tokens(candidate_text)
            if len(overlap) > len(best_overlap):
                best_field, best_overlap = field, overlap
            for entity in entities:
                aliases = TECHNOLOGY_ALIASES.get(entity) or SOFT_SKILL_ALIASES.get(entity) or (entity,)
                if any(contains_term(candidate_text, alias) for alias in aliases):
                    entity_fields.setdefault(entity, []).append(field)
        entity_coverage = len(entity_fields) / len(entities) if entities else None
        lexical_coverage = (
            len(best_overlap) / len(requirement_tokens) if requirement_tokens else 0.0
        )
        demonstrated_entities = {
            entity
            for entity, fields in entity_fields.items()
            if any(field in demonstrated_fields for field in fields)
        }
        demonstrated = bool(demonstrated_entities) or best_field in demonstrated_fields
        if entities and entity_coverage == 1.0 and demonstrated:
            status = "direct"
        elif entities and entity_coverage == 1.0:
            status = "listed_only"
        elif (entity_coverage or 0.0) >= 0.5 or lexical_coverage >= 0.45:
            status = "transferable"
        else:
            status = "unsupported"
        results.append(
            {
                **dict(requirement),
                "match_status": status,
                "best_field": best_field or None,
                "matched_terms": sorted(best_overlap),
                "matched_entities": sorted(entity_fields),
                "demonstrated_entities": sorted(demonstrated_entities),
                "entity_coverage": round(entity_coverage, 3)
                if entity_coverage is not None
                else None,
                "lexical_coverage": round(lexical_coverage, 3),
            }
        )
    required = [item for item in results if item.get("priority") == "required"]
    preferred = [item for item in results if item.get("priority") == "preferred"]
    responsibilities = [
        item for item in results if item.get("priority") == "responsibility"
    ]

    def group_score(items: Sequence[Mapping[str, Any]]) -> float | None:
        if not items:
            return None
        values = {
            "direct": 1.0,
            "listed_only": 0.65,
            "transferable": 0.5,
            "unsupported": 0.0,
        }
        return round(
            sum(values.get(str(item.get("match_status")), 0.0) for item in items)
            / len(items)
            * 100,
            1,
        )

    required_score = group_score(required)
    preferred_score = group_score(preferred)
    responsibility_score = group_score(responsibilities)
    available_groups = [
        (required_score, 0.6),
        (responsibility_score, 0.3),
        (preferred_score, 0.1),
    ]
    present = [(score, weight) for score, weight in available_groups if score is not None]
    score = (
        round(sum(score * weight for score, weight in present) / sum(weight for _, weight in present), 1)
        if present
        else None
    )
    return {
        "version": REQUIREMENT_VERSION,
        "available": bool(results),
        "score": score,
        "required_score": required_score,
        "preferred_score": preferred_score,
        "responsibility_score": responsibility_score,
        "counts": {
            status: sum(item["match_status"] == status for item in results)
            for status in ("direct", "listed_only", "transferable", "unsupported")
        },
        "requirements": results,
    }


__all__ = [
    "REQUIREMENT_VERSION",
    "SOFT_SKILL_ALIASES",
    "TECHNOLOGY_ALIASES",
    "analyze_job_description",
    "contains_term",
    "extract_catalog_terms",
    "extract_requirements",
    "match_requirements",
]
