from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.profile import ProfileService
from app.services.preference_intelligence import (
    LOCATION_ALIASES,
    canonical_location,
    excluded_term_matches,
)
from app.utils import tokenize


class MatchingService:
    def __init__(self, profiles: ProfileService):
        self.profiles = profiles

    def score(
        self,
        job: Dict[str, Any],
        freshness_class: str,
        plan: Dict[str, Any],
    ) -> Dict[str, Any]:
        profile_row = self.profiles.active_profile()
        if not profile_row:
            raise ValueError("Profile is required for matching")
        evidence = self.profiles.approved_evidence()
        description = f"{job['title']} {job['description']}".casefold()
        title_tokens = set(tokenize(job["title"]))
        role_tokens = set(tokenize(" ".join(plan.get("role_aliases", []))))
        role_overlap = title_tokens & role_tokens
        role_score = min(25.0, 8.0 + len(role_overlap) * 5.5) if role_overlap else 5.0

        skills = profile_row["profile"].get("skills", [])
        mentioned_profile_skills = [
            skill for skill in skills if skill.casefold() in description
        ]
        evidence_by_skill = {
            skill: self._evidence_for_skills(evidence, [skill])
            for skill in mentioned_profile_skills
        }
        matched_skills = [
            skill for skill in mentioned_profile_skills if evidence_by_skill[skill]
        ]
        skill_score = min(22.0, len(matched_skills) * 3.2)

        required_years = self._required_years(job["description"])
        experience_score = (
            13.0
            if required_years is None or required_years <= 2
            else 8.0
            if required_years == 3
            else 4.0
        )

        location_score, location_reason, location_risk = self._location_score(
            job.get("location", ""), job.get("work_mode"), plan.get("locations", [])
        )
        freshness_score = {
            "verified_24h": 15.0,
            "verified_48h": 12.0,
            "live_date_unverified": 7.0,
            "older_live": 6.0,
            "uncertain": 1.0,
            "closed": 0.0,
        }.get(freshness_class, 0.0)

        excluded = [
            value.casefold() for value in plan.get("excluded_keywords", []) if value
        ]
        exclusion_hits = [
            value
            for value in excluded
            if excluded_term_matches(job["title"], job["description"], value)
        ]
        preference_score, preference_reasons = self._preference_score(
            job,
            description,
            plan,
        )
        if exclusion_hits:
            preference_score = 2.0
        score = round(
            role_score
            + skill_score
            + experience_score
            + location_score
            + freshness_score
            + preference_score,
            1,
        )

        reasons: List[Dict[str, Any]] = []
        if role_overlap:
            reasons.append(
                {
                    "code": "role_alignment",
                    "text": f"The title aligns with your selected {', '.join(sorted(role_overlap))} direction.",
                    "evidence_ids": [],
                    "job_span": job["title"],
                }
            )
        if matched_skills:
            evidence_ids = list(
                dict.fromkeys(
                    evidence_id
                    for skill in matched_skills
                    for evidence_id in evidence_by_skill[skill]
                )
            )[:8]
            reasons.append(
                {
                    "code": "skill_evidence",
                    "text": "Approved resume evidence supports "
                    + ", ".join(matched_skills[:4])
                    + ".",
                    "evidence_ids": evidence_ids,
                    "job_span": self._job_span(job["description"], matched_skills),
                }
            )
        reasons.extend(preference_reasons)
        if location_reason:
            reasons.append(
                {
                    "code": "location_fit",
                    "text": location_reason,
                    "evidence_ids": [],
                    "job_span": job.get("location", ""),
                }
            )
        if freshness_class in {"verified_24h", "verified_48h"}:
            reasons.append(
                {
                    "code": "freshness",
                    "text": "The official source provides recent posting evidence.",
                    "evidence_ids": [],
                    "job_span": job.get("posted_at") or "",
                }
            )

        risks: List[str] = []
        if required_years and required_years > 3:
            risks.append(f"The description asks for about {required_years}+ years of experience.")
        if re.search(
            r"\b(?:sde|engineer|developer)\s*(?:ii|2)\b",
            str(job.get("title") or "").casefold(),
        ):
            risks.append("The title is level II; verify that its experience band is flexible.")
        if location_risk:
            risks.append(location_risk)
        if exclusion_hits:
            risks.append("Possible exclusion match: " + ", ".join(exclusion_hits[:3]))
        if freshness_class == "live_date_unverified":
            risks.append("The official route is live, but its posting time is not proven.")
        if plan.get("work_modes") and not job.get("work_mode"):
            risks.append("The employer did not list a work mode; verify it before applying.")
        if plan.get("employment_types") and not job.get("employment_type"):
            risks.append("The employer did not list an employment type.")
        if plan.get("salary_min") is not None and not job.get("salary"):
            risks.append("Salary is not published; this role remains eligible.")
        if not matched_skills:
            risks.append("No strong skill overlap was found in the approved evidence.")

        tier = "strong" if score >= 78 else "good" if score >= 65 else "possible" if score >= 50 else "low"
        selected_reasons = reasons[:3]
        selected_reason_codes = {reason["code"] for reason in selected_reasons}
        for reason in preference_reasons:
            if reason["code"] not in selected_reason_codes:
                selected_reasons.append(reason)
                selected_reason_codes.add(reason["code"])
        return {
            "score": score,
            "tier": tier,
            "factors": {
                "role_fit": round(role_score, 1),
                "skill_fit": round(skill_score, 1),
                "experience_fit": round(experience_score, 1),
                "location_fit": round(location_score, 1),
                "freshness": round(freshness_score, 1),
                "preference_fit": round(preference_score, 1),
            },
            "reasons": selected_reasons,
            "risks": risks[:3],
            "evidence_ids": list(
                dict.fromkeys(
                    evidence_id
                    for reason in reasons
                    for evidence_id in reason["evidence_ids"]
                )
            ),
        }

    @classmethod
    def _preference_score(
        cls,
        job: Dict[str, Any],
        description: str,
        plan: Dict[str, Any],
    ) -> Tuple[float, List[Dict[str, Any]]]:
        preferred_industries = cls._preference_terms(
            plan.get("preferred_industries", [])
        )
        preferred_companies = cls._preference_terms(
            plan.get("preferred_companies", [])
        )
        priority_skills = cls._preference_terms(plan.get("priority_skills", []))
        active_weights = {
            "preferred_company": 4.0 if preferred_companies else 0.0,
            "preferred_industry": 3.0 if preferred_industries else 0.0,
            "priority_skill": 3.0 if priority_skills else 0.0,
        }
        if not sum(active_weights.values()):
            return 10.0, []

        company = str(job.get("company") or "")
        company_matches = [
            term
            for term in preferred_companies
            if cls._contains_preference_term(company, term)
        ]
        industry_matches = [
            term
            for term in preferred_industries
            if cls._contains_preference_term(description, term)
        ]
        priority_skill_matches = [
            term
            for term in priority_skills
            if cls._contains_preference_term(description, term)
        ]
        matched_weights = (
            active_weights["preferred_company"] if company_matches else 0.0
        ) + (
            active_weights["preferred_industry"] if industry_matches else 0.0
        ) + (active_weights["priority_skill"] if priority_skill_matches else 0.0)
        preference_score = 4.0 + 6.0 * matched_weights / sum(active_weights.values())

        reasons: List[Dict[str, Any]] = []
        if company_matches:
            reasons.append(
                {
                    "code": "preferred_company",
                    "text": f"{company} matches your preferred company list.",
                    "evidence_ids": [],
                    "job_span": company,
                }
            )
        if industry_matches:
            reasons.append(
                {
                    "code": "preferred_industry",
                    "text": "The role aligns with your preferred "
                    + ", ".join(industry_matches[:3])
                    + " industry focus.",
                    "evidence_ids": [],
                    "job_span": cls._job_span(
                        str(job.get("description") or ""), industry_matches
                    ),
                }
            )
        if priority_skill_matches:
            reasons.append(
                {
                    "code": "priority_skill",
                    "text": "The role uses your priority skills: "
                    + ", ".join(priority_skill_matches[:4])
                    + ".",
                    "evidence_ids": [],
                    "job_span": cls._job_span(
                        str(job.get("description") or ""), priority_skill_matches
                    ),
                }
            )
        return preference_score, reasons

    @staticmethod
    def _preference_terms(values: Any) -> List[str]:
        if not isinstance(values, list):
            return []
        return [
            " ".join(value.split())
            for value in values
            if isinstance(value, str) and value.strip()
        ]

    @staticmethod
    def _contains_preference_term(haystack: str, term: str) -> bool:
        normalized_haystack = " ".join(haystack.split()).casefold()
        normalized_term = " ".join(term.split()).casefold()
        if not normalized_term:
            return False
        pattern = re.escape(normalized_term).replace(r"\ ", r"\s+")
        return bool(re.search(rf"(?<!\w){pattern}(?!\w)", normalized_haystack))

    @staticmethod
    def _required_years(description: str) -> Optional[int]:
        normalized = description.casefold()
        values: List[int] = []
        occupied: List[Tuple[int, int]] = []
        for match in re.finditer(
            r"\b(\d{1,2})\s*(?:-|–|—|to)\s*(\d{1,2})\s*(?:years?|yrs?)\b",
            normalized,
        ):
            minimum, maximum = int(match.group(1)), int(match.group(2))
            if minimum <= maximum < 20:
                values.append(minimum)
                occupied.append(match.span())
        for match in re.finditer(
            r"\b(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b",
            normalized,
        ):
            if any(
                match.start() < end and match.end() > start
                for start, end in occupied
            ):
                continue
            value = int(match.group(1))
            if value < 20:
                values.append(value)
        return min(values) if values else None

    @staticmethod
    def _location_score(
        location: str, work_mode: Optional[str], preferences: Sequence[str]
    ) -> Tuple[float, str, str]:
        lowered = " ".join(location.split()).casefold()

        def contains_phrase(phrase: str) -> bool:
            normalized = " ".join(phrase.split()).casefold()
            pattern = re.escape(normalized).replace(r"\ ", r"\s+")
            return bool(re.search(rf"(?<!\w){pattern}(?!\w)", lowered))

        for index, preferred in enumerate(preferences):
            canonical = canonical_location(preferred)
            aliases = LOCATION_ALIASES.get(canonical, (canonical.casefold(),))
            matches = any(contains_phrase(alias) for alias in aliases)
            if canonical == "Remote India":
                india_aliases = LOCATION_ALIASES["India"]
                matches = work_mode == "remote" and any(
                    contains_phrase(alias) for alias in india_aliases
                )
            if matches:
                score = max(8.0, 15.0 - index * 2.0)
                return score, f"{location} matches preference #{index + 1}: {preferred}.", ""
        return 5.0, "", f"{location} is outside your current preferred location order."

    @staticmethod
    def _evidence_for_skills(
        evidence: Sequence[Dict[str, Any]], skills: Sequence[str]
    ) -> List[str]:
        result: List[str] = []
        for claim in evidence:
            lowered = claim["text"].casefold()
            if any(skill.casefold() in lowered for skill in skills):
                result.append(claim["id"])
        return result[:8]

    @staticmethod
    def _job_span(description: str, skills: Sequence[str]) -> str:
        for line in description.splitlines():
            if any(skill.casefold() in line.casefold() for skill in skills):
                return line[:500]
        return description[:500]
