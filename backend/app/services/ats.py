from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

from app.services.requirements import (
    SOFT_SKILL_ALIASES as STRUCTURED_SOFT_SKILLS,
    TECHNOLOGY_ALIASES as STRUCTURED_HARD_SKILLS,
    analyze_job_description,
    extract_catalog_terms as extract_structured_catalog_terms,
    match_requirements,
)


ANALYZER_VERSION = "carivyo-ats-2.0.0"
DISCLAIMER = (
    "No universal ATS score exists. Carivyo reports independent submission "
    "compatibility, evidence alignment, and content-review perspectives using "
    "deterministic public criteria. It does not reproduce a vendor's proprietary "
    "scoring, predict hiring outcomes, or verify the truth of candidate claims."
)

MAX_INPUT_CHARACTERS = 2_000_000


@dataclass(frozen=True)
class CheckSpec:
    id: str
    label: str
    category: str
    max_score: float
    checker: str


@dataclass(frozen=True)
class CheckOutcome:
    ratio: Optional[float]
    evidence: Tuple[str, ...]
    suggestion: str
    status: Optional[str] = None


@dataclass(frozen=True)
class AnalysisContext:
    text: str
    lower: str
    raw_lines: Tuple[str, ...]
    lines: Tuple[str, ...]
    sections: Mapping[str, Tuple[str, ...]]
    section_order: Tuple[str, ...]
    metadata: Mapping[str, Any]
    jd_text: str
    jd_lower: str


CATEGORY_SPECS: Tuple[Tuple[str, str, float], ...] = (
    ("ats_essentials", "ATS essentials", 18.0),
    ("sections", "Sections", 12.0),
    ("content", "Content", 20.0),
    ("job_tailoring", "Job tailoring", 18.0),
    ("recruiter_red_flags", "Recruiter red flags", 12.0),
    ("bias_discrimination", "Bias and discrimination", 6.0),
    ("seniority_impact", "Seniority and impact", 14.0),
)

CATEGORY_WEIGHTS: Dict[str, float] = {
    category: weight for category, _label, weight in CATEGORY_SPECS
}

CHECK_SPECS: Tuple[CheckSpec, ...] = (
    CheckSpec("file_format_size", "File format and size", "ats_essentials", 4.0, "_check_file_format_size"),
    CheckSpec("design", "Machine-readable design", "ats_essentials", 4.0, "_check_simple_design"),
    CheckSpec("professional_email", "Professional email", "ats_essentials", 3.0, "_check_professional_email"),
    CheckSpec("header_links", "Header links", "ats_essentials", 2.0, "_check_header_links"),
    CheckSpec("filename", "Professional filename", "ats_essentials", 2.0, "_check_professional_filename"),
    CheckSpec("date_link_consistency", "Date and link consistency", "ats_essentials", 3.0, "_check_date_link_consistency"),
    CheckSpec("essential_sections", "Essential sections", "sections", 4.0, "_check_essential_sections"),
    CheckSpec("contact", "Contact details", "sections", 4.0, "_check_contact_details"),
    CheckSpec("section_order", "Section order", "sections", 4.0, "_check_section_order"),
    CheckSpec("parse_rate", "Resume text parse rate", "content", 6.0, "_check_text_parse_rate"),
    CheckSpec("quantified_impact", "Quantified impact", "content", 5.0, "_check_quantified_impact"),
    CheckSpec("repetition", "Content repetition", "content", 3.0, "_check_content_repetition"),
    CheckSpec("spelling_grammar", "Spelling and grammar heuristics", "content", 2.0, "_check_spelling_grammar"),
    CheckSpec("bullet_length_consistency", "Bullet length and consistency", "content", 4.0, "_check_bullet_length_consistency"),
    CheckSpec("hard_skills", "Hard-skill alignment", "job_tailoring", 7.0, "_check_hard_skill_alignment"),
    CheckSpec("soft_skills", "Soft-skill alignment", "job_tailoring", 3.0, "_check_soft_skill_alignment"),
    CheckSpec("action_verbs", "Action verbs", "job_tailoring", 4.0, "_check_action_verbs"),
    CheckSpec("tailored_title", "Tailored title", "job_tailoring", 4.0, "_check_tailored_title"),
    CheckSpec("credibility", "Claim credibility signals", "recruiter_red_flags", 4.0, "_check_claim_credibility"),
    CheckSpec("interview_risk", "Interview-risk evidence", "recruiter_red_flags", 3.0, "_check_interview_readiness"),
    CheckSpec("peer_benchmark_proxy", "Peer benchmark proxy", "recruiter_red_flags", 3.0, "_check_peer_benchmark_proxy"),
    CheckSpec("linkedin_match", "LinkedIn match", "recruiter_red_flags", 2.0, "_check_linkedin_consistency"),
    CheckSpec("age_date_bias", "Age/date bias safeguards", "bias_discrimination", 3.0, "_check_optional_sensitive_data"),
    CheckSpec("employment_gaps", "Employment-gap visibility", "bias_discrimination", 3.0, "_check_employment_gaps"),
    CheckSpec("career_progression", "Career progression", "seniority_impact", 5.0, "_check_career_progression"),
    CheckSpec("skills_evidence", "Skills backed by evidence", "seniority_impact", 5.0, "_check_skills_evidence"),
    CheckSpec("leadership_signals", "Leadership and ownership signals", "seniority_impact", 4.0, "_check_leadership_signals"),
)

CHECK_WEIGHTS: Dict[str, float] = {spec.id: spec.max_score for spec in CHECK_SPECS}

if len(CHECK_SPECS) != 27:
    raise RuntimeError("The Carivyo ATS contract requires exactly 27 checks")
if round(sum(CHECK_WEIGHTS.values()), 8) != 100.0:
    raise RuntimeError("Carivyo ATS check weights must total 100")
for _category, _label, _weight in CATEGORY_SPECS:
    if round(
        sum(spec.max_score for spec in CHECK_SPECS if spec.category == _category),
        8,
    ) != _weight:
        raise RuntimeError(f"ATS category weights do not match for {_category}")


SECTION_ALIASES = {
    "summary": "summary",
    "professional summary": "summary",
    "profile": "summary",
    "objective": "summary",
    "experience": "experience",
    "work experience": "experience",
    "professional experience": "experience",
    "employment history": "experience",
    "work history": "experience",
    "projects": "projects",
    "selected projects": "projects",
    "personal projects": "projects",
    "skills": "skills",
    "technical skills": "skills",
    "core skills": "skills",
    "technologies": "skills",
    "education": "education",
    "academic background": "education",
    "certifications": "certifications",
    "licenses and certifications": "certifications",
    "achievements": "achievements",
    "awards": "achievements",
    "leadership": "leadership",
    "publications": "publications",
    "volunteering": "volunteering",
    "languages": "languages",
    "interests": "interests",
}

EMAIL_RE = re.compile(r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")
URL_RE = re.compile(
    r"(?i)(?<![@\w])(?:https?://|www\.)[^\s<>{}\[\]|]+"
    r"|(?<![@\w])(?:linkedin\.com/in|github\.com)/[A-Za-z0-9_.~%/-]+"
)
BULLET_RE = re.compile(r"^\s*(?:[-*•●▪◦‣]|\d{1,2}[.)])\s+")

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
MONTH_PATTERN = "(?:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + ")"
MONTH_RANGE_RE = re.compile(
    rf"\b({MONTH_PATTERN})\.?\s+((?:19|20)\d{{2}})\s*"
    rf"(?:-|–|—|to)\s*(?:({MONTH_PATTERN})\.?\s+((?:19|20)\d{{2}})|(present|current|now))",
    re.IGNORECASE,
)
YEAR_RANGE_RE = re.compile(
    r"\b((?:19|20)\d{2})\s*(?:-|–|—|to)\s*((?:19|20)\d{2}|present|current|now)\b",
    re.IGNORECASE,
)

METRIC_RE = re.compile(
    r"(?i)(?:"
    r"(?:[$£€₹]\s?\d[\d,.]*|\d[\d,.]*\s?(?:%|x\b|users?\b|customers?\b|"
    r"requests?\b|transactions?\b|records?\b|services?\b|teams?\b|engineers?\b|"
    r"hours?\b|days?\b|weeks?\b|months?\b|ms\b|seconds?\b|million\b|billion\b|k\b))"
    r"|(?:reduced|increased|improved|grew|saved|cut|lowered|raised)\b[^.\n]{0,60}\b\d[\d,.]*"
    r")"
)

ACTION_VERBS = {
    "accelerated", "achieved", "analyzed", "architected", "assessed", "authored",
    "automated", "built", "coached", "collaborated", "configured", "contributed",
    "created", "cut", "debugged", "delivered", "deployed", "designed", "developed",
    "documented", "drove", "enabled", "engineered", "established", "expanded",
    "implemented", "improved", "increased", "integrated", "launched", "led",
    "maintained", "managed", "mentored", "migrated", "monitored", "optimized",
    "orchestrated", "owned", "partnered", "planned", "prototyped", "published",
    "reduced", "refactored", "researched", "resolved", "reviewed", "scaled",
    "secured", "shipped", "simplified", "spearheaded", "streamlined", "strengthened",
    "supported", "tested", "transformed", "unified", "upgraded", "validated",
    "verified", "wrote",
}

LEADERSHIP_TERMS = (
    "led", "mentored", "coached", "managed", "owned", "drove", "spearheaded",
    "coordinated", "guided", "reviewed", "architected", "technical direction",
    "cross-functional", "stakeholders", "roadmap", "hiring", "onboarded",
)

HARD_SKILLS: Mapping[str, Tuple[str, ...]] = {
    "Python": ("python",),
    "Java": ("java",),
    "JavaScript": ("javascript",),
    "TypeScript": ("typescript",),
    "C++": ("c++",),
    "C#": ("c#",),
    "Go": ("golang", "go language"),
    "Rust": ("rust",),
    "SQL": ("sql",),
    "PostgreSQL": ("postgresql", "postgres"),
    "MySQL": ("mysql",),
    "SQLite": ("sqlite",),
    "MongoDB": ("mongodb",),
    "Redis": ("redis",),
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
    "Machine Learning": ("machine learning",),
    "Deep Learning": ("deep learning",),
    "PyTorch": ("pytorch",),
    "TensorFlow": ("tensorflow",),
    "scikit-learn": ("scikit-learn", "sklearn"),
    "LLM": ("llm", "large language model"),
    "RAG": ("rag", "retrieval augmented generation", "retrieval-augmented generation"),
    "LangChain": ("langchain",),
    "Selenium": ("selenium",),
    "Playwright": ("playwright",),
    "OpenAPI": ("openapi",),
    "OAuth": ("oauth", "oauth2", "oauth 2.0"),
    "Microservices": ("microservices", "microservice"),
}

SOFT_SKILLS: Mapping[str, Tuple[str, ...]] = {
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

# ATS v2 uses the shared requirement normalizer so discovery, matching, resume
# design, and analysis cannot silently disagree about recognized terminology.
HARD_SKILLS = STRUCTURED_HARD_SKILLS
SOFT_SKILLS = STRUCTURED_SOFT_SKILLS

COMMON_TYPOS = {
    "acheived": "achieved",
    "alot": "a lot",
    "collaberated": "collaborated",
    "developement": "development",
    "enviroment": "environment",
    "experiance": "experience",
    "implimented": "implemented",
    "mangement": "management",
    "recieved": "received",
    "responsibile": "responsible",
    "succesfully": "successfully",
    "teh": "the",
}

ROLE_WORDS = {
    "engineer", "developer", "architect", "manager", "lead", "consultant",
    "analyst", "scientist", "specialist", "intern", "director", "administrator",
    "designer", "researcher", "programmer", "officer",
}

ROLE_STOP_WORDS = {
    "a", "an", "and", "at", "for", "in", "is", "of", "or", "our", "the",
    "to", "we", "with", "hiring", "looking", "position", "role", "seeking",
}

SENSITIVE_FIELD_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("date of birth", re.compile(r"(?i)\b(?:date of birth|birth date|d\.o\.b\.?|dob)\s*[:\-]")),
    ("explicit age", re.compile(r"(?i)\bage\s*[:\-]\s*\d{1,3}\b")),
    ("marital status", re.compile(r"(?i)\bmarital status\s*[:\-]")),
    ("gender", re.compile(r"(?i)\bgender\s*[:\-]")),
    ("religion", re.compile(r"(?i)\breligion\s*[:\-]")),
    ("caste", re.compile(r"(?i)\bcaste\s*[:\-]")),
    ("nationality", re.compile(r"(?i)\bnationality\s*[:\-]")),
)

CRITICAL_CHECK_IDS = {
    "file_format_size",
    "professional_email",
    "essential_sections",
    "contact",
    "parse_rate",
}


class ATSAnalyzer:
    """Deterministic, evidence-constrained resume quality analyzer.

    ``metadata`` can include ``filename``, ``file_format``, ``size_bytes``,
    layout signals such as ``column_count``/``has_tables``/``image_only``, a
    ``job_title``, and an independently supplied ``linkedin_url``. Missing
    evidence produces ``not_applicable`` where a responsible judgment cannot be
    made. No network calls or model-generated facts are used.
    """

    version = ANALYZER_VERSION

    def analyze(
        self,
        resume_text: Any = "",
        metadata: Optional[Mapping[str, Any]] = None,
        jd_text: Any = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if resume_text in (None, ""):
            resume_text = kwargs.get(
                "text", kwargs.get("source_text", kwargs.get("pdf_text", resume_text))
            )
        if metadata is None and isinstance(kwargs.get("file_metadata"), Mapping):
            metadata = kwargs["file_metadata"]
        if jd_text is None:
            jd_text = kwargs.get("job_description", kwargs.get("job_description_text", ""))
        try:
            safe_metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
        except (TypeError, ValueError):
            safe_metadata = {}
        text = _safe_text(resume_text)
        job_description = _safe_text(jd_text)
        sections, section_order = _split_sections(text)
        context = AnalysisContext(
            text=text,
            lower=text.casefold(),
            raw_lines=tuple(text.splitlines()),
            lines=tuple(_normalize_line(line) for line in text.splitlines() if _normalize_line(line)),
            sections=sections,
            section_order=section_order,
            metadata=safe_metadata,
            jd_text=job_description,
            jd_lower=job_description.casefold(),
        )

        checks: List[Dict[str, Any]] = []
        for spec in CHECK_SPECS:
            outcome = getattr(self, spec.checker)(context)
            checks.append(self._serialize_check(spec, outcome))

        applicable = [check for check in checks if check["status"] != "not_applicable"]
        applicable_max = round(sum(check["max_score"] for check in applicable), 2)
        earned_points = round(sum(check["score"] for check in applicable), 2)
        overall_score = (
            round(earned_points / applicable_max * 100.0, 1) if applicable_max else 0.0
        )
        parse_rate = _parse_rate(context)

        category_summaries = []
        for category_id, label, configured_max in CATEGORY_SPECS:
            category_checks = [check for check in checks if check["category"] == category_id]
            category_applicable = [
                check for check in category_checks if check["status"] != "not_applicable"
            ]
            category_max = round(
                sum(check["max_score"] for check in category_applicable), 2
            )
            category_earned = round(
                sum(check["score"] for check in category_applicable), 2
            )
            category_summaries.append(
                {
                    "id": category_id,
                    "label": label,
                    "score": category_earned,
                    "max_score": category_max,
                    "configured_max_score": configured_max,
                    "percentage": round(category_earned / category_max * 100.0, 1)
                    if category_max
                    else None,
                    "applicable_checks": len(category_applicable),
                    "total_checks": len(category_checks),
                }
            )

        not_applicable_ids = [
            check["id"] for check in checks if check["status"] == "not_applicable"
        ]
        status_counts = {
            status: sum(1 for check in checks if check["status"] == status)
            for status in ("pass", "warning", "fail", "not_applicable")
        }
        ordered_issues = sorted(
            (
                check
                for check in checks
                if check["status"] in {"fail", "warning"}
            ),
            key=lambda check: (
                0 if check["status"] == "fail" else 1,
                -(check["max_score"] - check["score"]),
                check["id"],
            ),
        )
        strongest = sorted(
            (check for check in checks if check["status"] == "pass"),
            key=lambda check: (-check["max_score"], check["id"]),
        )
        readiness = (
            "blocked"
            if any(
                check["id"] in CRITICAL_CHECK_IDS and check["status"] == "fail"
                for check in checks
            )
            else "needs_focus"
            if status_counts["fail"]
            else "review"
            if status_counts["warning"]
            else "strong"
        )
        job_alignment = _job_alignment_report(context)
        recruiter_insights = _recruiter_insight_report(context)
        jd_quality = analyze_job_description(
            job_description,
            _metadata_text(safe_metadata, "job_title", "jd_title", "target_title"),
        )
        structured_alignment = match_requirements(
            jd_quality["requirements"], context.sections
        )
        compatibility = _perspective_summary(
            "compatibility",
            "Submission compatibility",
            checks,
            {
                "file_format_size",
                "design",
                "professional_email",
                "header_links",
                "filename",
                "date_link_consistency",
                "essential_sections",
                "contact",
                "section_order",
                "parse_rate",
            },
        )
        content_quality = _perspective_summary(
            "content_quality",
            "Content quality",
            checks,
            {
                "quantified_impact",
                "repetition",
                "spelling_grammar",
                "bullet_length_consistency",
                "action_verbs",
                "credibility",
                "interview_risk",
                "skills_evidence",
            },
        )
        alignment_status = (
            "insufficient_data"
            if jd_quality["status"] != "complete"
            else "strong"
            if (structured_alignment.get("score") or 0) >= 80
            else "review"
            if (structured_alignment.get("score") or 0) >= 55
            else "needs_focus"
        )
        evidence_alignment = {
            "id": "evidence_alignment",
            "label": "Evidence-backed job alignment",
            "status": alignment_status,
            "score": (
                structured_alignment.get("score")
                if jd_quality["status"] == "complete"
                else None
            ),
            "confidence": jd_quality["confidence"],
            "required_score": structured_alignment.get("required_score"),
            "preferred_score": structured_alignment.get("preferred_score"),
            "responsibility_score": structured_alignment.get("responsibility_score"),
            "counts": structured_alignment.get("counts", {}),
            "requirement_count": jd_quality["requirement_count"],
            "note": (
                "No job-fit score is produced until a complete official job description is available."
                if jd_quality["status"] != "complete"
                else "Required, preferred, and responsibility evidence are reported separately."
            ),
        }
        assessment_status = (
            "blocked"
            if compatibility["status"] == "blocked"
            else "insufficient_data"
            if jd_quality["status"] != "complete"
            else "needs_focus"
            if "needs_focus"
            in {compatibility["status"], content_quality["status"], alignment_status}
            else "review"
            if "review"
            in {compatibility["status"], content_quality["status"], alignment_status}
            else "strong"
        )
        return {
            "overall_score": overall_score,
            "parse_rate": parse_rate,
            "category_summaries": category_summaries,
            "checks": checks,
            "critical_failures": [
                check["id"]
                for check in checks
                if check["id"] in CRITICAL_CHECK_IDS and check["status"] == "fail"
            ],
            "analyzer_version": self.version,
            "disclaimer": DISCLAIMER,
            "scoring": {
                "configured_max_score": 100.0,
                "applicable_max_score": applicable_max,
                "earned_points": earned_points,
                "normalization_factor": round(100.0 / applicable_max, 6)
                if applicable_max
                else 0.0,
                "not_applicable_check_ids": not_applicable_ids,
                "rule": (
                    "overall_score = earned_points / applicable_max_score * 100; "
                    "not_applicable checks contribute neither earned nor available points"
                ),
            },
            "protected_trait_policy": (
                "Only explicitly labeled optional sensitive fields are detected. "
                "Carivyo does not infer age or any other protected trait from dates, "
                "names, language, location, education, or employment history."
            ),
            "report_summary": {
                "readiness": readiness,
                "status_counts": status_counts,
                "priority_actions": [
                    {
                        "check_id": check["id"],
                        "label": check["label"],
                        "severity": check["status"],
                        "evidence": check["evidence"],
                        "suggestion": check["suggestion"],
                    }
                    for check in ordered_issues[:5]
                ],
                "strengths": [
                    {
                        "check_id": check["id"],
                        "label": check["label"],
                        "evidence": check["evidence"],
                    }
                    for check in strongest[:5]
                ],
            },
            "methodology": {
                "feature_contract": "27 transparent checks across seven public resume-review categories",
                "score_scope": "diagnostic summary over applicable deterministic checks",
                "calibration_scope": (
                    "Observable report categories and controlled examples only; no claim is made "
                    "to reproduce a third party's proprietary model or numeric score."
                ),
                "human_review_required": True,
            },
            "job_alignment": job_alignment,
            "recruiter_insights": recruiter_insights,
            "jd_quality": jd_quality,
            "structured_alignment": structured_alignment,
            "assessment": {
                "version": "carivyo-ats-perspectives-2.0.0",
                "status": assessment_status,
                "confidence": (
                    "high"
                    if jd_quality["confidence"] == "high"
                    and compatibility["coverage"] >= 0.9
                    else "medium"
                    if jd_quality["status"] == "complete"
                    else "unavailable"
                ),
                "compatibility": compatibility,
                "evidence_alignment": evidence_alignment,
                "content_quality": content_quality,
                "legacy_overall_score": overall_score,
                "legacy_score_deprecated": True,
                "explanation": (
                    "Carivyo does not combine parser compatibility, job alignment, and "
                    "content quality into one universal ATS score."
                ),
            },
        }

    @staticmethod
    def _serialize_check(spec: CheckSpec, outcome: CheckOutcome) -> Dict[str, Any]:
        if outcome.ratio is None:
            status = "not_applicable"
            score = 0.0
        else:
            ratio = min(1.0, max(0.0, float(outcome.ratio)))
            score = round(spec.max_score * ratio, 2)
            status = outcome.status or (
                "pass" if ratio >= 0.8 else "warning" if ratio >= 0.4 else "fail"
            )
        return {
            "id": spec.id,
            "label": spec.label,
            "category": spec.category,
            "status": status,
            "score": score,
            "max_score": spec.max_score,
            "evidence": list(outcome.evidence),
            "suggestion": outcome.suggestion,
        }

    def _check_file_format_size(self, context: AnalysisContext) -> CheckOutcome:
        filename = _metadata_text(
            context.metadata, "filename", "file_name", "original_name", "name"
        )
        format_value = _metadata_text(
            context.metadata,
            "file_format",
            "format",
            "extension",
            "mime_type",
            "content_type",
        ).casefold()
        if not format_value and filename:
            format_value = Path(filename).suffix.casefold().lstrip(".")
        format_value = format_value.removeprefix(".")
        aliases = {
            "application/pdf": "pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
            "text/plain": "txt",
            "text/markdown": "md",
        }
        format_value = aliases.get(format_value, format_value)
        size = _metadata_number(
            context.metadata, "size_bytes", "file_size_bytes", "file_size", "size"
        )
        if not format_value and size is None:
            return _na(
                "Supply the original filename or format and byte size to evaluate this check.",
                "No file-format or size metadata was supplied.",
            )

        ratios: List[float] = []
        evidence: List[str] = []
        if format_value:
            if format_value in {"pdf", "docx"}:
                ratios.append(1.0)
                evidence.append(f"The declared .{format_value} format is broadly ATS-readable.")
            elif format_value in {"txt", "rtf", "md", "markdown", "tex"}:
                ratios.append(0.6)
                evidence.append(
                    f"The declared .{format_value} source is text-readable but is not a typical submission format."
                )
            else:
                ratios.append(0.0)
                evidence.append(f"The declared format ({format_value}) is not in the supported ATS-safe set.")
        if size is not None:
            if size <= 0:
                ratios.append(0.0)
                evidence.append("The supplied file size is zero or invalid.")
            elif size <= 5 * 1024 * 1024:
                ratios.append(1.0)
                evidence.append(f"File size is {_format_bytes(size)}, within the 5 MB guideline.")
            elif size <= 10 * 1024 * 1024:
                ratios.append(0.5)
                evidence.append(f"File size is {_format_bytes(size)}, above the 5 MB guideline.")
            else:
                ratios.append(0.0)
                evidence.append(f"File size is {_format_bytes(size)}, above 10 MB.")
        return CheckOutcome(
            sum(ratios) / len(ratios),
            tuple(evidence),
            "Submit a text-based PDF or DOCX under 5 MB unless the employer requests another format.",
        )

    def _check_simple_design(self, context: AnalysisContext) -> CheckOutcome:
        metadata = context.metadata
        observed = False
        ratio = 1.0
        evidence: List[str] = []
        image_only = _metadata_bool(metadata, "image_only", "is_image_only", "scanned_pdf")
        if image_only is not None:
            observed = True
            if image_only:
                ratio = 0.0
                evidence.append("Layout metadata marks the resume as image-only or scanned.")
            else:
                evidence.append("Layout metadata confirms selectable text rather than an image-only file.")
        columns = _metadata_number(metadata, "column_count", "columns", "detected_columns")
        if columns is not None:
            observed = True
            if columns > 1:
                ratio -= 0.35
                evidence.append(f"Layout metadata reports {int(columns)} columns.")
            else:
                evidence.append("Layout metadata reports a single-column structure.")
        for keys, label, penalty in (
            (("has_tables", "tables_detected"), "tables", 0.2),
            (("has_text_boxes", "text_boxes_detected"), "text boxes", 0.2),
            (("has_header_footer_content", "header_footer_content"), "header/footer content", 0.15),
        ):
            value = _metadata_bool(metadata, *keys)
            if value is not None:
                observed = True
                if value:
                    ratio -= penalty
                    evidence.append(f"Layout metadata reports {label}, which can disrupt reading order.")
        if not observed:
            return _na(
                "Supply PDF layout metadata (columns, tables, text boxes, and scan status) for this check.",
                "No reliable layout evidence was supplied; extracted text alone cannot prove visual simplicity.",
            )
        return CheckOutcome(
            max(0.0, ratio),
            tuple(evidence or ["No risky layout flags were supplied."]),
            "Prefer selectable text, one column, standard headings, and no text boxes or layout tables.",
        )

    def _check_professional_email(self, context: AnalysisContext) -> CheckOutcome:
        emails = EMAIL_RE.findall(context.text)
        if not emails:
            return CheckOutcome(
                0.0,
                ("No syntactically valid email address was found.",),
                "Add a monitored, professional email address near the top of the resume.",
            )
        suspicious = []
        for email in emails:
            local = email.split("@", 1)[0].casefold()
            if re.search(r"(?:sexy|hot|cool|crazy|princess|king|gamer|rockstar|420|69)", local):
                suspicious.append(email)
        header = "\n".join(context.lines[:10]).casefold()
        in_header = any(email.casefold() in header for email in emails)
        ratio = 1.0
        if suspicious:
            ratio -= 0.6
        if not in_header:
            ratio -= 0.25
        evidence = [f"Found {len(emails)} syntactically valid email address(es)."]
        if in_header:
            evidence.append("A valid email appears in the resume header.")
        if suspicious:
            evidence.append("The email username contains an informal term.")
        return CheckOutcome(
            max(0.0, ratio),
            tuple(evidence),
            "Use a name-based email address and keep it in the header.",
        )

    def _check_header_links(self, context: AnalysisContext) -> CheckOutcome:
        header_text = "\n".join(context.lines[:10])
        links = _extract_urls(header_text)
        if not links:
            if not _has_meaningful_text(context.text):
                return CheckOutcome(
                    0.0,
                    ("No resume header text was available.",),
                    "Add a readable header before adding relevant professional links.",
                )
            mentions = re.search(r"(?i)\b(?:linkedin|github|portfolio)\b", header_text)
            return CheckOutcome(
                0.25 if mentions else 0.5,
                (
                    "A link label was found without a machine-readable URL."
                    if mentions
                    else "No portfolio, GitHub, or LinkedIn URL was found in the header."
                ,),
                "Add only relevant, complete profile or portfolio URLs in the header.",
            )
        valid = [link for link in links if _normalized_url(link)]
        professional = [
            link
            for link in valid
            if any(host in (_normalized_url(link) or "") for host in ("linkedin.com/", "github.com/"))
        ]
        ratio = 1.0 if professional else 0.75 if valid else 0.0
        return CheckOutcome(
            ratio,
            (
                f"Found {len(valid)} valid header URL(s).",
                f"{len(professional)} recognized professional profile URL(s) were found.",
            ),
            "Use complete HTTPS links and remove links that do not support the application.",
        )

    def _check_professional_filename(self, context: AnalysisContext) -> CheckOutcome:
        filename = _metadata_text(
            context.metadata, "filename", "file_name", "original_name", "name"
        )
        if not filename:
            return _na(
                "Supply the original filename to evaluate this check.",
                "No filename metadata was supplied.",
            )
        stem = Path(filename).stem
        lowered = stem.casefold()
        noisy = bool(
            re.search(r"(?:final\s*final|copy\s*\d*|new\s*resume|untitled|document\s*\d*)", lowered)
        )
        safe_characters = bool(re.fullmatch(r"[A-Za-z0-9 _.-]+", stem))
        tokens = re.findall(r"[a-z]+", lowered)
        includes_resume = any(token in {"resume", "cv"} for token in tokens)
        generic_only = set(tokens) <= {"resume", "cv", "final", "latest", "updated"}
        if noisy or not safe_characters:
            ratio = 0.2
        elif generic_only:
            ratio = 0.55
        elif includes_resume and len(tokens) >= 2:
            ratio = 1.0
        else:
            ratio = 0.75
        return CheckOutcome(
            ratio,
            (f"Evaluated the supplied filename pattern: {Path(filename).name}.",),
            "Use a clear filename such as Firstname_Lastname_Resume.pdf.",
        )

    def _check_date_link_consistency(self, context: AnalysisContext) -> CheckOutcome:
        styles = _date_styles(context.text)
        links = _extract_urls(context.text)
        intervals = _extract_date_intervals(context.text.splitlines())
        components: List[float] = []
        evidence: List[str] = []
        if styles:
            components.append(1.0 if len(styles) == 1 else 0.55)
            evidence.append("Detected date styles: " + ", ".join(styles) + ".")
        if links:
            valid_count = sum(1 for link in links if _normalized_url(link))
            https_count = sum(1 for link in links if link.casefold().startswith("https://"))
            components.append((valid_count / len(links) + https_count / len(links)) / 2)
            evidence.append(
                f"{valid_count}/{len(links)} links are syntactically valid and {https_count}/{len(links)} use explicit HTTPS."
            )
        reversed_ranges = sum(
            1 for start, end, _line in intervals if end is not None and end < start
        )
        if intervals:
            components.append(0.0 if reversed_ranges else 1.0)
            evidence.append(
                f"Found {len(intervals)} parseable date range(s); {reversed_ranges} are reversed."
            )
        if not components:
            return _na(
                "Use one date style and complete HTTPS links when those elements are present.",
                "No parseable dates or links were available for a consistency judgment.",
            )
        return CheckOutcome(
            sum(components) / len(components),
            tuple(evidence),
            "Use one month/year convention, verify range order, and use complete HTTPS URLs.",
        )

    def _check_essential_sections(self, context: AnalysisContext) -> CheckOutcome:
        essential = ("experience", "skills", "education")
        present = [section for section in essential if context.sections.get(section)]
        return CheckOutcome(
            len(present) / len(essential),
            ("Detected essential sections: " + (", ".join(present) if present else "none") + ".",),
            "Include clearly labeled Experience, Skills, and Education sections; projects may supplement experience.",
        )

    def _check_contact_details(self, context: AnalysisContext) -> CheckOutcome:
        header = "\n".join(context.lines[:10])
        has_email = bool(EMAIL_RE.search(header))
        has_phone = bool(PHONE_RE.search(header))
        has_link = bool(_extract_urls(header))
        ratio = (0.5 if has_email else 0.0) + (0.35 if has_phone else 0.0) + (0.15 if has_link else 0.0)
        return CheckOutcome(
            ratio,
            (
                "Header contact signals: "
                f"email={'yes' if has_email else 'no'}, phone={'yes' if has_phone else 'no'}, "
                f"link={'yes' if has_link else 'no'}.",
            ),
            "Place an email and phone number in the header; add a relevant profile link when useful.",
        )

    def _check_section_order(self, context: AnalysisContext) -> CheckOutcome:
        order = list(context.section_order)
        if not order:
            return CheckOutcome(
                0.0,
                ("No recognized section headings were found.",),
                "Use conventional, standalone section headings in a logical reading order.",
            )
        if len(order) == 1:
            return CheckOutcome(
                0.25,
                (f"Only one recognized section heading was found: {order[0]}.",),
                "Separate the resume into conventional sections with Experience before Education.",
            )
        rules: List[bool] = []
        positions = {name: index for index, name in enumerate(order)}
        for before, after in (
            ("summary", "experience"),
            ("summary", "education"),
            ("experience", "education"),
            ("projects", "education"),
        ):
            if before in positions and after in positions:
                rules.append(positions[before] < positions[after])
        ratio = sum(rules) / len(rules) if rules else 0.7
        return CheckOutcome(
            ratio,
            ("Recognized order: " + " → ".join(order) + ".",),
            "Lead with the most relevant summary/skills, then experience or projects, with education later.",
        )

    def _check_text_parse_rate(self, context: AnalysisContext) -> CheckOutcome:
        rate = _parse_rate(context)
        ratio = rate / 100.0
        evidence = (
            f"Deterministic parse rate is {rate:.1f}% based on supplied extraction counts or readable-character signals.",
        )
        return CheckOutcome(
            ratio,
            evidence,
            "Export selectable text and inspect the extracted text if the parse rate is below 90%.",
        )

    def _check_quantified_impact(self, context: AnalysisContext) -> CheckOutcome:
        lines = _achievement_lines(context)
        if not lines:
            return CheckOutcome(
                0.0,
                ("No experience, project, or achievement statements were available.",),
                "Add evidence-backed accomplishment bullets before adding metrics.",
            )
        quantified = [line for line in lines if _has_metric(line)]
        target = min(3, len(lines))
        ratio = min(1.0, len(quantified) / target)
        return CheckOutcome(
            ratio,
            (f"Found supported numeric outcome signals in {len(quantified)}/{len(lines)} accomplishment statements.",),
            "Where source evidence exists, add scale, latency, revenue, adoption, quality, or time outcomes.",
        )

    def _check_content_repetition(self, context: AnalysisContext) -> CheckOutcome:
        candidates = [
            _normalized_for_comparison(line)
            for line in _body_lines(context)
            if len(line.split()) >= 4
        ]
        if not candidates:
            return CheckOutcome(
                0.0,
                ("There was not enough body content to measure repetition.",),
                "Add distinct, evidence-backed statements for each role or project.",
            )
        duplicate_count = len(candidates) - len(set(candidates))
        repeated_openers = _repeated_openers(candidates)
        penalty = duplicate_count / len(candidates) + min(0.35, repeated_openers * 0.08)
        return CheckOutcome(
            max(0.0, 1.0 - penalty),
            (
                f"Found {duplicate_count} duplicate line(s) across {len(candidates)} body lines.",
                f"Found {repeated_openers} overused opening word(s).",
            ),
            "Remove duplicate claims and vary sentence openings only when the evidence supports distinct actions.",
        )

    def _check_spelling_grammar(self, context: AnalysisContext) -> CheckOutcome:
        body = "\n".join(_body_lines(context))
        if not body.strip():
            return CheckOutcome(
                0.0,
                ("No body text was available for deterministic language checks.",),
                "Add resume content, then run a human spelling and grammar review.",
            )
        issues: List[str] = []
        for typo, replacement in COMMON_TYPOS.items():
            if re.search(rf"(?i)\b{re.escape(typo)}\b", body):
                issues.append(f"possible typo '{typo}' (consider '{replacement}')")
        repeated_words = re.findall(r"(?i)\b([a-z]{2,})\s+\1\b", body)
        if repeated_words:
            issues.append(f"{len(repeated_words)} repeated adjacent word(s)")
        punctuation_spacing = len(re.findall(r"\s+[,.!?;:]", body))
        if punctuation_spacing:
            issues.append(f"{punctuation_spacing} punctuation-spacing issue(s)")
        unmatched = sum(abs(body.count(left) - body.count(right)) for left, right in (("(", ")"), ("[", "]"), ("{", "}")))
        if unmatched:
            issues.append(f"{unmatched} unmatched bracket(s)")
        line_count = max(1, len(_body_lines(context)))
        ratio = max(0.0, 1.0 - len(issues) / max(2.0, line_count * 0.25))
        return CheckOutcome(
            ratio,
            tuple(issues[:5]) if issues else ("No issue matched the limited deterministic typo, repetition, spacing, or bracket rules.",),
            "Treat this as a limited heuristic and complete a human language review before applying.",
        )

    def _check_bullet_length_consistency(self, context: AnalysisContext) -> CheckOutcome:
        bullets = [line for line in context.raw_lines if BULLET_RE.match(line)]
        if not bullets:
            statements = _achievement_lines(context)
            if not statements:
                return CheckOutcome(
                    0.0,
                    ("No accomplishment bullets or statements were found.",),
                    "Use concise bullets for experience and project accomplishments.",
                )
            words = [len(line.split()) for line in statements]
            acceptable = sum(1 for count in words if 6 <= count <= 35)
            return CheckOutcome(
                0.5 * acceptable / len(words),
                (f"No explicit bullet markers were found; {acceptable}/{len(words)} statements are 6–35 words long.",),
                "Use a consistent bullet marker and keep most bullets between roughly 6 and 35 words.",
            )
        cleaned = [BULLET_RE.sub("", line).strip() for line in bullets]
        word_counts = [len(line.split()) for line in cleaned]
        length_ratio = sum(1 for count in word_counts if 6 <= count <= 35) / len(word_counts)
        markers = [BULLET_RE.match(line).group(0).strip() for line in bullets if BULLET_RE.match(line)]
        marker_ratio = max(markers.count(marker) for marker in set(markers)) / len(markers)
        punctuation = [bool(re.search(r"[.!?]$", line)) for line in cleaned]
        punctuation_ratio = max(punctuation.count(True), punctuation.count(False)) / len(punctuation)
        ratio = length_ratio * 0.6 + marker_ratio * 0.25 + punctuation_ratio * 0.15
        return CheckOutcome(
            ratio,
            (
                f"{sum(1 for count in word_counts if 6 <= count <= 35)}/{len(bullets)} bullets are 6–35 words long.",
                f"Bullet-marker consistency is {marker_ratio * 100:.0f}% and ending-punctuation consistency is {punctuation_ratio * 100:.0f}%.",
            ),
            "Use one bullet style and revise unusually short or long bullets without inventing details.",
        )

    def _check_hard_skill_alignment(self, context: AnalysisContext) -> CheckOutcome:
        if not context.jd_text:
            return _na(
                "Supply the target job description to measure hard-skill alignment.",
                "No job description was supplied.",
            )
        jd_quality = analyze_job_description(
            context.jd_text, _target_job_title(context)
        )
        technical_requirements = [
            item
            for item in jd_quality["requirements"]
            if item.get("category") == "technical_skill"
        ]
        if not technical_requirements:
            return _na(
                "Obtain a complete official job description before judging technical alignment.",
                "No structured technical requirement was available for comparison.",
            )
        alignment = match_requirements(technical_requirements, context.sections)
        values = {
            "direct": 1.0,
            "listed_only": 0.65,
            "transferable": 0.5,
            "unsupported": 0.0,
        }
        matched = [
            item
            for item in alignment["requirements"]
            if item["match_status"] != "unsupported"
        ]
        demonstrated = [
            item
            for item in alignment["requirements"]
            if item["match_status"] == "direct"
        ]
        ratio = sum(
            values.get(item["match_status"], 0.0)
            for item in alignment["requirements"]
        ) / len(alignment["requirements"])
        return CheckOutcome(
            ratio,
            (
                f"Matched {len(matched)}/{len(technical_requirements)} structured technical requirements.",
                f"{len(demonstrated)} requirement(s) are demonstrated outside the Skills list.",
                "Unsupported: "
                + (
                    "; ".join(
                        item["text"]
                        for item in alignment["requirements"]
                        if item["match_status"] == "unsupported"
                    )[:500]
                    or "none"
                )
                + ".",
            ),
            "Add only missing hard skills that are supported by the candidate's actual experience.",
        )

    def _check_soft_skill_alignment(self, context: AnalysisContext) -> CheckOutcome:
        if not context.jd_text:
            return _na(
                "Supply the target job description to measure soft-skill alignment.",
                "No job description was supplied.",
            )
        jd_quality = analyze_job_description(
            context.jd_text, _target_job_title(context)
        )
        soft_requirements = [
            item
            for item in jd_quality["requirements"]
            if item.get("category") == "soft_skill"
        ]
        if not soft_requirements:
            return _na(
                "No explicit soft-skill requirement was recognized in the job description.",
                "No recognized soft-skill requirement was available for comparison.",
            )
        alignment = match_requirements(soft_requirements, context.sections)
        values = {
            "direct": 1.0,
            "listed_only": 0.65,
            "transferable": 0.5,
            "unsupported": 0.0,
        }
        matched = [
            item
            for item in alignment["requirements"]
            if item["match_status"] != "unsupported"
        ]
        return CheckOutcome(
            sum(
                values.get(item["match_status"], 0.0)
                for item in alignment["requirements"]
            )
            / len(alignment["requirements"]),
            (
                f"Matched {len(matched)}/{len(soft_requirements)} structured soft-skill requirements.",
                "Matched evidence fields: "
                + (", ".join(sorted({str(item.get('best_field')) for item in matched if item.get('best_field')})) or "none")
                + ".",
            ),
            "Demonstrate requested soft skills through truthful actions and outcomes, not unsupported keyword lists.",
        )

    def _check_action_verbs(self, context: AnalysisContext) -> CheckOutcome:
        statements = _explicit_achievement_bullets(
            context, {"experience", "projects"}
        ) or _achievement_lines(context)
        if not statements:
            return CheckOutcome(
                0.0,
                ("No accomplishment statements were available to inspect.",),
                "Start accomplishment bullets with precise verbs that reflect the candidate's actual contribution.",
            )
        action_count = sum(1 for line in statements if _first_word(line) in ACTION_VERBS)
        return CheckOutcome(
            action_count / len(statements),
            (f"{action_count}/{len(statements)} accomplishment statements begin with a recognized action verb.",),
            "Replace vague openings with accurate action verbs while preserving the underlying evidence.",
        )

    def _check_tailored_title(self, context: AnalysisContext) -> CheckOutcome:
        if not context.jd_text:
            return _na(
                "Supply the target job description and, when available, job_title metadata.",
                "No job description was supplied.",
            )
        job_title = _target_job_title(context)
        if not job_title:
            return _na(
                "Supply job_title metadata when the title cannot be reliably parsed from the description.",
                "No reliable target title was available.",
            )
        title_tokens = _role_tokens(job_title)
        header_text = " ".join(context.sections.get("header", ())[:6])
        header_tokens = set(_tokenize_words(header_text))
        matched = title_tokens & header_tokens
        ratio = len(matched) / len(title_tokens) if title_tokens else 0.0
        if job_title.casefold() in header_text.casefold():
            ratio = 1.0
        return CheckOutcome(
            ratio,
            (
                f"Target title evidence: {job_title}.",
                f"Matched {len(matched)}/{len(title_tokens)} meaningful target-title tokens in the header.",
            ),
            "Use the target title in the header only when it truthfully describes the candidate's background or objective.",
        )

    def _check_claim_credibility(self, context: AnalysisContext) -> CheckOutcome:
        if not _has_meaningful_text(context.text):
            return CheckOutcome(
                0.0,
                ("No claims were available to inspect.",),
                "Add specific, supportable claims and retain source evidence for each one.",
            )
        patterns = {
            "guaranteed outcome": r"(?i)\bguaranteed\b",
            "unqualified best-in-world claim": r"(?i)\b(?:world'?s best|best in the world)\b",
            "unqualified number-one claim": r"(?i)(?:^|\s)#\s*1\b|\bnumber one in the world\b",
            "single-handed claim": r"(?i)\bsingle[- ]handedly\b",
            "unbounded expertise claim": r"(?i)\bexpert (?:at|in) (?:all|everything)\b",
        }
        hits = [label for label, pattern in patterns.items() if re.search(pattern, context.text)]
        reversed_ranges = sum(
            1
            for start, end, _line in _extract_date_intervals(context.text.splitlines())
            if end is not None and end < start
        )
        if reversed_ranges:
            hits.append(f"{reversed_ranges} reversed date range(s)")
        ratio = max(0.0, 1.0 - 0.45 * len(hits))
        return CheckOutcome(
            ratio,
            tuple(hits) if hits else ("No claim matched the limited absolute-claim or reversed-date rules.",),
            "Qualify absolute claims and keep interview-ready source evidence; this check does not verify factual truth.",
        )

    def _check_interview_readiness(self, context: AnalysisContext) -> CheckOutcome:
        statements = _achievement_lines(context)
        if not statements:
            return CheckOutcome(
                0.0,
                ("No accomplishment statements were available as interview evidence.",),
                "Add concise problem-action-outcome statements that can be supported in an interview.",
            )
        specific = []
        for line in statements:
            has_action = _first_word(line) in ACTION_VERBS
            has_metric = _has_metric(line)
            has_skill = bool(_extract_catalog_terms(line, HARD_SKILLS))
            has_scope = bool(re.search(r"(?i)\b(?:api|service|system|pipeline|product|platform|model|application|workflow|database|team)\b", line))
            if sum((has_action, has_metric, has_skill, has_scope)) >= 2:
                specific.append(line)
        return CheckOutcome(
            len(specific) / len(statements),
            (f"{len(specific)}/{len(statements)} statements contain at least two concrete action, skill, scope, or outcome signals.",),
            "Strengthen vague statements with truthful context, contribution, and outcome details that can be discussed.",
        )

    def _check_peer_benchmark_proxy(self, context: AnalysisContext) -> CheckOutcome:
        if not _has_meaningful_text(context.text):
            return CheckOutcome(
                0.0,
                ("No resume content was available for the completeness proxy.",),
                "Add essential sections and evidence-backed accomplishments.",
            )
        essential_present = sum(
            1 for section in ("experience", "skills", "education") if context.sections.get(section)
        ) / 3
        statements = _achievement_lines(context)
        impact = (
            min(1.0, sum(1 for line in statements if _has_metric(line)) / min(3, len(statements)))
            if statements
            else 0.0
        )
        evidence_density = (
            sum(
                1
                for line in statements
                if _first_word(line) in ACTION_VERBS or _extract_catalog_terms(line, HARD_SKILLS)
            )
            / len(statements)
            if statements
            else 0.0
        )
        ratio = essential_present * 0.4 + impact * 0.3 + evidence_density * 0.3
        return CheckOutcome(
            ratio,
            (
                "This is a transparent completeness proxy only; no peer resumes, hiring decisions, or demographic data were used.",
                f"Proxy components: essential sections {essential_present * 100:.0f}%, quantified impact {impact * 100:.0f}%, evidence density {evidence_density * 100:.0f}%.",
            ),
            "Use the component evidence to improve completeness; do not interpret this proxy as a percentile or hiring prediction.",
        )

    def _check_linkedin_consistency(self, context: AnalysisContext) -> CheckOutcome:
        expected = _expected_linkedin(context.metadata)
        resume_links = [
            link for link in _extract_urls(context.text) if "linkedin.com/in/" in (_normalized_url(link) or "")
        ]
        if not expected:
            return _na(
                "Supply an independently sourced linkedin_url to compare it with the resume; Carivyo will not fetch it.",
                "No independent LinkedIn profile evidence was supplied, so no match claim is made.",
            )
        expected_normalized = _normalized_url(expected)
        if not expected_normalized:
            return _na(
                "Supply a valid independently sourced LinkedIn profile URL.",
                "The supplied independent LinkedIn URL is malformed.",
            )
        if not resume_links:
            return CheckOutcome(
                0.0,
                ("An independent LinkedIn URL was supplied, but no LinkedIn URL appears in the resume.",),
                "Add the verified profile URL to the header if it supports the application.",
            )
        normalized_resume = [_normalized_url(link) for link in resume_links]
        exact = expected_normalized in normalized_resume
        return CheckOutcome(
            1.0 if exact else 0.2,
            (
                "The resume LinkedIn URL matches the independently supplied URL."
                if exact
                else "The resume LinkedIn URL differs from the independently supplied URL."
            ,),
            "Resolve the URL mismatch manually; this analyzer compares URLs only and does not inspect profile content.",
        )

    def _check_optional_sensitive_data(self, context: AnalysisContext) -> CheckOutcome:
        if not _has_meaningful_text(context.text):
            return _na(
                "Do not add optional sensitive personal fields unless they are legally required for the application context.",
                "No resume text was supplied; no protected-trait judgment was made.",
            )
        fields = [label for label, pattern in SENSITIVE_FIELD_PATTERNS if pattern.search(context.text)]
        if fields:
            return CheckOutcome(
                0.2,
                ("Explicitly labeled optional sensitive fields detected: " + ", ".join(fields) + ".",),
                "Consider removing optional sensitive fields. Carivyo does not infer age or other traits from ordinary dates.",
                status="warning",
            )
        return CheckOutcome(
            1.0,
            ("No explicitly labeled optional sensitive field matched; education and employment dates were not used to infer age.",),
            "Keep protected-trait information out of the resume unless explicitly required and appropriate.",
        )

    def _check_employment_gaps(self, context: AnalysisContext) -> CheckOutcome:
        experience_lines = context.sections.get("experience", ())
        intervals = [
            interval
            for interval in _extract_date_intervals(experience_lines)
            if interval[1] is None or interval[1] >= interval[0]
        ]
        if len(intervals) < 2:
            return _na(
                "Supply at least two parseable employment date ranges for a mechanical gap check.",
                "Fewer than two employment date ranges were available; no gap was inferred.",
            )
        intervals.sort(key=lambda value: value[0])
        gaps = []
        previous_end = intervals[0][1]
        for start, end, _line in intervals[1:]:
            if previous_end is not None and start - previous_end > 13:
                gaps.append(start - previous_end)
            if end is not None:
                previous_end = max(previous_end or end, end)
        if gaps:
            return CheckOutcome(
                0.45,
                (f"Found {len(gaps)} unexplained calendar gap(s) longer than 12 months in parseable employment ranges.",),
                "Check date accuracy and, if useful, label truthful career breaks without disclosing protected information.",
                status="warning",
            )
        return CheckOutcome(
            1.0,
            (f"No gap over 12 months was found across {len(intervals)} parseable employment ranges.",),
            "Keep employment dates accurate and use one consistent month/year format.",
        )

    def _check_career_progression(self, context: AnalysisContext) -> CheckOutcome:
        roles = _dated_roles(context.sections.get("experience", ()))
        if len(roles) < 2:
            return _na(
                "Provide at least two roles with parseable dates and titles for a progression check.",
                "Fewer than two dated role-title signals were available; progression was not inferred.",
            )
        roles.sort(key=lambda item: item[0])
        earliest = roles[0]
        latest = roles[-1]
        ratio = 1.0 if latest[2] >= earliest[2] else 0.6
        return CheckOutcome(
            ratio,
            (
                f"Observed dated title sequence from '{earliest[1]}' to '{latest[1]}'.",
                "Only explicit title words and date ranges were compared; responsibility growth was not inferred.",
            ),
            "Make promotions or scope growth explicit only when supported by employment records.",
        )

    def _check_skills_evidence(self, context: AnalysisContext) -> CheckOutcome:
        skill_lines = context.sections.get("skills", ())
        if not skill_lines:
            return CheckOutcome(
                0.0,
                ("No recognized Skills section content was found.",),
                "Add a concise skills section and retain only skills supported elsewhere in the resume.",
            )
        listed = _extract_catalog_terms("\n".join(skill_lines), HARD_SKILLS)
        if not listed:
            return CheckOutcome(
                0.25,
                ("A Skills section exists, but no term matched this version's public hard-skill dictionary.",),
                "Use standard skill names and support them with truthful experience or project statements.",
            )
        evidence_text = "\n".join(
            line
            for section, lines in context.sections.items()
            if section not in {"header", "skills"}
            for line in lines
        )
        evidenced_terms = set(_extract_catalog_terms(evidence_text, HARD_SKILLS))
        evidenced = [term for term in listed if term in evidenced_terms]
        return CheckOutcome(
            len(evidenced) / len(listed),
            (
                f"{len(evidenced)}/{len(listed)} recognized listed skills also appear in experience, projects, or other evidence sections.",
                "Evidence-backed skills: " + (", ".join(evidenced) if evidenced else "none") + ".",
            ),
            "Remove unsupported skill keywords or add truthful project/experience evidence for them.",
        )

    def _check_leadership_signals(self, context: AnalysisContext) -> CheckOutcome:
        evidence_text = "\n".join(_achievement_lines(context)).casefold()
        if not evidence_text:
            return CheckOutcome(
                0.0,
                ("No accomplishment statements were available for leadership or ownership signals.",),
                "Add truthful ownership, mentoring, coordination, or decision-scope evidence where applicable.",
            )
        signals = [term for term in LEADERSHIP_TERMS if _contains_term(evidence_text, term)]
        ratio = min(1.0, 0.2 + len(signals) * 0.25)
        return CheckOutcome(
            ratio,
            ("Explicit leadership/ownership signals: " + (", ".join(signals) if signals else "none") + ".",),
            "Leadership need not mean people management; include only supported ownership, mentoring, or coordination scope.",
        )


def analyze_resume(
    resume_text: Any = "",
    metadata: Optional[Mapping[str, Any]] = None,
    jd_text: Any = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Convenience entry point for Carivyo's first-party ATS analyzer."""

    return ATSAnalyzer().analyze(resume_text, metadata, jd_text, **kwargs)


def _perspective_summary(
    perspective_id: str,
    label: str,
    checks: Sequence[Mapping[str, Any]],
    check_ids: set[str],
) -> Dict[str, Any]:
    selected = [check for check in checks if check.get("id") in check_ids]
    configured = sum(float(check.get("max_score") or 0) for check in selected)
    applicable = [
        check for check in selected if check.get("status") != "not_applicable"
    ]
    available = sum(float(check.get("max_score") or 0) for check in applicable)
    earned = sum(float(check.get("score") or 0) for check in applicable)
    score = round(earned / available * 100, 1) if available else None
    critical_failures = [
        str(check.get("id"))
        for check in applicable
        if check.get("id") in CRITICAL_CHECK_IDS and check.get("status") == "fail"
    ]
    failures = sum(check.get("status") == "fail" for check in applicable)
    warnings = sum(check.get("status") == "warning" for check in applicable)
    status = (
        "blocked"
        if critical_failures
        else "needs_focus"
        if failures
        else "review"
        if warnings or available < configured
        else "strong"
    )
    return {
        "id": perspective_id,
        "label": label,
        "status": status,
        "score": score,
        "coverage": round(available / configured, 3) if configured else 0.0,
        "applicable_checks": len(applicable),
        "total_checks": len(selected),
        "critical_failures": critical_failures,
        "issues": [
            str(check.get("id"))
            for check in applicable
            if check.get("status") in {"fail", "warning"}
        ],
    }


analyze_ats = analyze_resume
ATSService = ATSAnalyzer


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    elif isinstance(value, str):
        text = value
    else:
        try:
            text = str(value)
        except Exception:
            return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = "".join(character for character in text if character in "\n\t" or ord(character) >= 32)
    return text[:MAX_INPUT_CHARACTERS].strip()


def _has_meaningful_text(value: str) -> bool:
    return bool(re.search(r"[A-Za-z0-9]", value))


def _normalize_line(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip(" \t•●▪◦‣")).strip()


def _normalized_for_comparison(value: str) -> str:
    value = BULLET_RE.sub("", value)
    return re.sub(r"[^a-z0-9+#]+", " ", value.casefold()).strip()


def _split_sections(text: str) -> Tuple[Mapping[str, Tuple[str, ...]], Tuple[str, ...]]:
    sections: Dict[str, List[str]] = {"header": []}
    order: List[str] = []
    current = "header"
    for raw_line in text.splitlines():
        line = _normalize_line(raw_line)
        if not line:
            continue
        candidate = re.sub(r"\s+", " ", line.casefold().rstrip(":"))
        heading = SECTION_ALIASES.get(candidate) if len(candidate) <= 45 else None
        if heading:
            current = heading
            sections.setdefault(current, [])
            if heading not in order:
                order.append(heading)
            continue
        sections.setdefault(current, []).append(line)
    return {key: tuple(values) for key, values in sections.items()}, tuple(order)


def _body_lines(context: AnalysisContext) -> List[str]:
    return [
        line
        for section, lines in context.sections.items()
        if section not in {"header", "skills"}
        for line in lines
    ]


def _achievement_lines(context: AnalysisContext) -> List[str]:
    explicit_bullets = _explicit_achievement_bullets(context)
    if explicit_bullets:
        return explicit_bullets
    lines = [
        line
        for section in ("experience", "projects", "achievements", "leadership")
        for line in context.sections.get(section, ())
        if len(line.split()) >= 4 and not _looks_like_date_or_title(line)
    ]
    if lines:
        return lines
    if context.section_order:
        return []
    return [
        line
        for line in context.lines[1:]
        if len(line.split()) >= 5
        and not EMAIL_RE.search(line)
        and not PHONE_RE.search(line)
        and not _extract_urls(line)
    ]


def _explicit_achievement_bullets(
    context: AnalysisContext,
    included_sections: Optional[set[str]] = None,
) -> List[str]:
    """Reconstruct explicit accomplishment bullets without counting wrapped lines."""

    bullets: List[str] = []
    current_section = "header"
    current_parts: List[str] = []

    def flush() -> None:
        if current_parts:
            statement = _normalize_line(" ".join(current_parts))
            if statement:
                bullets.append(statement)
            current_parts.clear()

    for raw_line in context.raw_lines:
        normalized = _normalize_line(raw_line)
        if not normalized:
            continue
        heading_key = re.sub(r"\s+", " ", normalized.casefold().rstrip(":"))
        heading = SECTION_ALIASES.get(heading_key) if len(heading_key) <= 45 else None
        if heading:
            flush()
            current_section = heading
            continue
        allowed_sections = included_sections or {
            "experience",
            "projects",
            "achievements",
            "leadership",
        }
        if current_section not in allowed_sections:
            continue
        if BULLET_RE.match(raw_line):
            flush()
            current_parts.append(BULLET_RE.sub("", raw_line).strip())
        elif current_parts:
            current_parts.append(normalized)
    flush()
    return bullets


def _looks_like_date_or_title(line: str) -> bool:
    word_count = len(line.split())
    has_range = bool(MONTH_RANGE_RE.search(line) or YEAR_RANGE_RE.search(line))
    has_role = bool(ROLE_WORDS & set(_tokenize_words(line)))
    return has_range and word_count <= 12 or has_role and word_count <= 5


def _first_word(value: str) -> str:
    cleaned = BULLET_RE.sub("", value).strip()
    match = re.search(r"[A-Za-z]+", cleaned)
    return match.group(0).casefold() if match else ""


def _metadata_text(metadata: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, (str, Path)) and str(value).strip():
            return str(value).strip()
    return ""


def _metadata_number(metadata: Mapping[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, bool) or value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            continue
    return None


def _metadata_bool(metadata: Mapping[str, Any], *keys: str) -> Optional[bool]:
    for key in keys:
        if key not in metadata:
            continue
        value = metadata.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().casefold()
            if normalized in {"true", "yes", "1", "present", "detected"}:
                return True
            if normalized in {"false", "no", "0", "absent", "none", "not_detected"}:
                return False
    return None


def _format_bytes(value: float) -> str:
    if value < 1024:
        return f"{int(value)} bytes"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value / (1024 * 1024):.1f} MB"


def _extract_urls(text: str) -> List[str]:
    return [match.group(0).rstrip(".,;:!?)") for match in URL_RE.finditer(text)]


def _normalized_url(value: str) -> Optional[str]:
    candidate = value.strip().rstrip("/")
    if not re.match(r"(?i)^https?://", candidate):
        candidate = "https://" + candidate.removeprefix("www.")
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None
    hostname = (parsed.hostname or "").casefold()
    if not hostname or "." not in hostname or any(char.isspace() for char in candidate):
        return None
    path = re.sub(r"/+", "/", parsed.path).rstrip("/").casefold()
    return hostname.removeprefix("www.") + path


def _date_styles(text: str) -> List[str]:
    styles = []
    if re.search(rf"(?i)\b{MONTH_PATTERN}\.?\s+(?:19|20)\d{{2}}", text):
        styles.append("month name + year")
    if re.search(r"\b(?:0?[1-9]|1[0-2])[/-](?:19|20)\d{2}\b", text):
        styles.append("numeric month/year")
    if re.search(r"\b(?:19|20)\d{2}\s*(?:-|–|—|to)\s*(?:(?:19|20)\d{2}|present|current)\b", text, re.IGNORECASE):
        styles.append("year only")
    return styles


def _extract_date_intervals(lines: Sequence[str]) -> List[Tuple[int, Optional[int], str]]:
    intervals: List[Tuple[int, Optional[int], str]] = []
    for line in lines:
        month_matches = list(MONTH_RANGE_RE.finditer(line))
        if month_matches:
            for match in month_matches:
                start_month = MONTHS[match.group(1).casefold().rstrip(".")]
                start = int(match.group(2)) * 12 + start_month - 1
                if match.group(5):
                    end = None
                else:
                    end_month = MONTHS[match.group(3).casefold().rstrip(".")]
                    end = int(match.group(4)) * 12 + end_month - 1
                intervals.append((start, end, line))
            continue
        for match in YEAR_RANGE_RE.finditer(line):
            start = int(match.group(1)) * 12
            end_value = match.group(2).casefold()
            end = None if end_value in {"present", "current", "now"} else int(end_value) * 12 + 11
            intervals.append((start, end, line))
    return intervals


def _parse_rate(context: AnalysisContext) -> float:
    direct = _metadata_number(context.metadata, "parse_rate", "text_parse_rate")
    if direct is not None:
        direct = direct * 100 if 0 <= direct <= 1 else direct
        return round(min(100.0, max(0.0, direct)), 1)
    source_count = _metadata_number(context.metadata, "source_char_count", "source_character_count")
    extracted_count = _metadata_number(context.metadata, "extracted_char_count", "extracted_character_count")
    if source_count is not None and extracted_count is not None and source_count > 0:
        return round(min(100.0, max(0.0, extracted_count / source_count * 100.0)), 1)
    if not context.text:
        return 0.0
    total = len(context.text)
    invalid = sum(
        1
        for character in context.text
        if character == "\ufffd" or (not character.isprintable() and character not in "\n\t")
    )
    readable = 1.0 - invalid / total
    if not re.search(r"[A-Za-z0-9]", context.text):
        readable *= 0.2
    return round(min(100.0, max(0.0, readable * 100.0)), 1)


def _has_metric(line: str) -> bool:
    without_dates = MONTH_RANGE_RE.sub("", line)
    without_dates = YEAR_RANGE_RE.sub("", without_dates)
    return bool(METRIC_RE.search(without_dates))


def _repeated_openers(lines: Sequence[str]) -> int:
    counts: Dict[str, int] = {}
    for line in lines:
        opener = " ".join(line.split()[:2])
        if opener:
            counts[opener] = counts.get(opener, 0) + 1
    return sum(1 for count in counts.values() if count >= 3)


def _contains_term(text: str, term: str) -> bool:
    return bool(re.search(r"(?<![A-Za-z0-9])" + re.escape(term.casefold()) + r"(?![A-Za-z0-9])", text.casefold()))


def _extract_catalog_terms(text: str, catalog: Mapping[str, Tuple[str, ...]]) -> List[str]:
    return [
        canonical
        for canonical, aliases in catalog.items()
        if any(_contains_term(text, alias) for alias in aliases)
    ]


def _tokenize_words(text: str) -> List[str]:
    return re.findall(r"[a-z][a-z0-9+#.-]*", text.casefold())


def _role_tokens(text: str) -> set[str]:
    return {
        token.rstrip("s")
        for token in _tokenize_words(text)
        if token not in ROLE_STOP_WORDS and len(token) >= 2
    }


def _target_job_title(context: AnalysisContext) -> str:
    direct = _metadata_text(context.metadata, "job_title", "jd_title", "target_title")
    if direct:
        return direct[:120]
    lines = [_normalize_line(line) for line in context.jd_text.splitlines() if _normalize_line(line)]
    if lines:
        first = lines[0].rstrip(":")
        tokens = set(_tokenize_words(first))
        if len(first.split()) <= 8 and tokens & ROLE_WORDS:
            return first[:120]
    match = re.search(
        r"(?i)\b(?:hiring|seeking|looking for|position|role)\s+(?:an?\s+)?"
        r"([a-z][a-z0-9/+# .-]{2,60}?(?:engineer|developer|architect|manager|lead|analyst|scientist|specialist|intern))\b",
        context.jd_text,
    )
    return _normalize_line(match.group(1))[:120] if match else ""


def _job_alignment_report(context: AnalysisContext) -> Dict[str, Any]:
    if not context.jd_text:
        return {
            "available": False,
            "target_title": None,
            "hard_skills": {"required": [], "matched": [], "missing": []},
            "soft_skills": {"required": [], "matched": [], "missing": []},
            "action_verbs_present": [],
            "note": "No job description was supplied; no job-fit claim is made.",
        }

    jd_quality = analyze_job_description(
        context.jd_text, _target_job_title(context)
    )
    structured = match_requirements(jd_quality["requirements"], context.sections)
    required_hard = extract_structured_catalog_terms(
        context.jd_text, STRUCTURED_HARD_SKILLS
    )
    resume_hard = set(_extract_catalog_terms(context.text, HARD_SKILLS))
    matched_hard = [term for term in required_hard if term in resume_hard]
    required_soft = extract_structured_catalog_terms(
        context.jd_text, STRUCTURED_SOFT_SKILLS
    )
    resume_soft = set(_extract_catalog_terms(context.text, SOFT_SKILLS))
    matched_soft = [term for term in required_soft if term in resume_soft]
    action_verbs = sorted(
        {
            _first_word(statement)
            for statement in _explicit_achievement_bullets(
                context, {"experience", "projects"}
            )
            if _first_word(statement) in ACTION_VERBS
        }
    )
    return {
        "available": True,
        "target_title": _target_job_title(context) or None,
        "hard_skills": {
            "required": required_hard,
            "matched": matched_hard,
            "missing": [term for term in required_hard if term not in resume_hard],
        },
        "soft_skills": {
            "required": required_soft,
            "matched": matched_soft,
            "missing": [term for term in required_soft if term not in resume_soft],
        },
        "action_verbs_present": action_verbs,
        "jd_quality": {
            key: value
            for key, value in jd_quality.items()
            if key != "requirements"
        },
        "structured": structured,
        "note": (
            "A missing term is a review cue, not permission to add it. Only supported "
            "candidate evidence may enter the resume."
        ),
    }


def _recruiter_insight_report(context: AnalysisContext) -> Dict[str, Any]:
    statements = _achievement_lines(context)
    interview_probes: List[Dict[str, str]] = []
    seen_evidence: set[str] = set()
    high_ownership = {
        "architected",
        "built",
        "designed",
        "drove",
        "led",
        "owned",
        "spearheaded",
    }

    def add_probe(kind: str, evidence: str, question: str, safe_action: str) -> None:
        normalized = _normalized_for_comparison(evidence)
        if not normalized or normalized in seen_evidence or len(interview_probes) >= 5:
            return
        seen_evidence.add(normalized)
        interview_probes.append(
            {
                "kind": kind,
                "evidence": evidence[:320],
                "question": question,
                "safe_action": safe_action,
            }
        )

    for statement in statements:
        if _has_metric(statement):
            add_probe(
                "measurement_method",
                statement,
                "How was this result measured, what was the baseline, and what part was your contribution?",
                "Keep the metric only when its source, baseline, method, and ownership can be explained truthfully.",
            )
    for statement in statements:
        if _first_word(statement) in high_ownership:
            add_probe(
                "ownership_scope",
                statement,
                "Which decisions and implementation were yours, and which were shared with the team?",
                "Clarify individual versus team contribution without weakening supported evidence.",
            )
    for statement in statements:
        if re.search(r"(?i)\b\d[\d,.+]*\s*(?:users?|engineers?|teams?|customers?|shops?|portals?)\b", statement):
            add_probe(
                "scope_validation",
                statement,
                "How was this scope counted, over what period, and how did the work affect those people or systems?",
                "Retain only verifiable scope and avoid adding outcomes that are not already supported.",
            )

    listed_skills = _extract_catalog_terms(
        "\n".join(context.sections.get("skills", ())), HARD_SKILLS
    )
    evidence_text = "\n".join(
        line
        for section, lines in context.sections.items()
        if section not in {"header", "skills"}
        for line in lines
    )
    evidence_skills = set(_extract_catalog_terms(evidence_text, HARD_SKILLS))
    backed = [term for term in listed_skills if term in evidence_skills]
    unbacked = [term for term in listed_skills if term not in evidence_skills]
    hidden = [
        term
        for term in _extract_catalog_terms(evidence_text, HARD_SKILLS)
        if term not in set(listed_skills)
    ]

    return {
        "credibility_scope": (
            "Interview preparation only. Carivyo flags claims that merit evidence review; "
            "it does not decide whether a claim is true."
        ),
        "interview_probes": interview_probes,
        "skill_evidence": {
            "listed": listed_skills,
            "backed": backed,
            "needs_evidence_review": unbacked,
            "demonstrated_but_unlisted": hidden,
        },
        "safe_fix_policy": (
            "Suggestions may clarify or remove a claim. They must never invent metrics, "
            "team sizes, ownership, dates, or adoption evidence."
        ),
    }


def _expected_linkedin(metadata: Mapping[str, Any]) -> str:
    direct = _metadata_text(metadata, "linkedin_url", "expected_linkedin_url")
    if direct:
        return direct
    links = metadata.get("profile_links")
    if isinstance(links, Mapping):
        value = links.get("linkedin") or links.get("linkedin_url")
        return str(value).strip() if isinstance(value, str) else ""
    if isinstance(links, Sequence) and not isinstance(links, (str, bytes)):
        for value in links:
            if isinstance(value, str) and "linkedin.com/in/" in value.casefold():
                return value.strip()
    return ""


def _dated_roles(lines: Sequence[str]) -> List[Tuple[int, str, int]]:
    roles: List[Tuple[int, str, int]] = []
    for index, line in enumerate(lines):
        intervals = _extract_date_intervals((line,))
        if not intervals:
            continue
        candidates = [line]
        if index > 0:
            candidates.append(lines[index - 1])
        title = next(
            (candidate for candidate in candidates if ROLE_WORDS & set(_tokenize_words(candidate))),
            "",
        )
        if not title:
            continue
        level = _seniority_level(title)
        roles.append((intervals[0][0], _strip_date_range(title), level))
    return roles


def _strip_date_range(value: str) -> str:
    value = MONTH_RANGE_RE.sub("", value)
    value = YEAR_RANGE_RE.sub("", value)
    return _normalize_line(value.strip(" |,-–—"))[:100] or "dated role"


def _seniority_level(title: str) -> int:
    lowered = title.casefold()
    if re.search(r"\b(?:principal|director|head|vp|vice president)\b", lowered):
        return 5
    if re.search(r"\b(?:staff|lead|manager|architect)\b", lowered):
        return 4
    if re.search(r"\bsenior\b|\bsr\.?\b", lowered):
        return 3
    if re.search(r"\b(?:junior|associate|jr\.?)\b", lowered):
        return 1
    if re.search(r"\b(?:intern|trainee|apprentice)\b", lowered):
        return 0
    return 2


def _na(suggestion: str, evidence: str) -> CheckOutcome:
    return CheckOutcome(None, (evidence,), suggestion, status="not_applicable")


__all__ = [
    "ANALYZER_VERSION",
    "ATSAnalyzer",
    "ATSService",
    "CATEGORY_WEIGHTS",
    "CHECK_WEIGHTS",
    "DISCLAIMER",
    "analyze_ats",
    "analyze_resume",
]
