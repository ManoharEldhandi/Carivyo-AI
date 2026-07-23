from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List

from app.db import Database
from app.services.profile import ProfileService
from app.services.preference_intelligence import interpret_preference_message
from app.utils import json_dumps, json_loads, new_id, stable_hash, utcnow


ROLE_ALIASES = {
    "backend": [
        "backend engineer",
        "backend developer",
        "api engineer",
        "server engineer",
        "software engineer",
        "software developer",
        "applications developer",
    ],
    "software": [
        "software engineer",
        "software developer",
        "sde",
        "associate software engineer",
        "software engineer i",
        "software developer i",
        "applications developer",
        "application development associate",
        "programmer analyst",
        "technology analyst",
        "engineering analyst",
        "graduate engineer trainee",
        "project engineer",
        "systems engineer",
        "member of technical staff",
        "associate member of technical staff",
        "amts",
        "ai engineer",
        "llm engineer",
        "machine learning engineer",
        "applied ai engineer",
    ],
    "sde": [
        "software engineer",
        "software engineer i",
        "software developer",
        "sde",
        "sde i",
        "associate software engineer",
    ],
    "associate": [
        "associate software engineer",
        "software engineer i",
        "sde i",
        "applications developer",
        "programmer analyst",
        "technology analyst",
        "engineering analyst",
        "graduate engineer trainee",
        "project engineer",
        "systems engineer",
        "associate member of technical staff",
        "amts",
    ],
    "full-stack": [
        "full stack engineer",
        "full-stack engineer",
        "frontend engineer",
        "backend engineer",
        "software engineer",
    ],
    "ai": [
        "ai engineer",
        "llm engineer",
        "generative ai engineer",
        "machine learning engineer",
        "applied ai engineer",
        "ai software engineer",
        "research engineer",
    ],
    "machine learning": [
        "machine learning engineer",
        "ml engineer",
        "applied scientist",
        "data scientist",
        "research engineer",
    ],
    "platform": ["platform engineer", "devops", "infrastructure", "sre"],
    "qa": ["sdet", "qa automation", "test automation"],
}


def _freshness_hours(value: Any, default: int = 48) -> int:
    candidates = value if isinstance(value, (list, tuple)) else [value]
    for candidate in candidates:
        try:
            parsed = int(candidate)
        except (TypeError, ValueError):
            continue
        return max(1, min(168, parsed))
    return default


def _string_list(value: Any) -> List[str]:
    values = value.split(",") if isinstance(value, str) else value
    if not isinstance(values, list):
        return []
    result: List[str] = []
    seen = set()
    for item in values:
        if not isinstance(item, str):
            continue
        cleaned = " ".join(item.split())
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def normalize_search_plan(value: Any) -> Dict[str, Any]:
    """Normalize persisted legacy plans at the read boundary without rewriting history."""

    plan = dict(value) if isinstance(value, dict) else {}
    plan["freshness_hours"] = _freshness_hours(plan.get("freshness_hours"))
    plan["locations"] = _string_list(
        plan.get("locations", plan.get("preferred_locations", []))
    )
    plan["target_roles"] = _string_list(plan.get("target_roles", []))
    work_modes = plan.get("work_modes", plan.get("work_mode", []))
    if isinstance(work_modes, str):
        lowered = work_modes.casefold()
        work_modes = [
            mode for mode in ("remote", "hybrid", "onsite") if mode in lowered
        ]
    plan["work_modes"] = _string_list(work_modes)
    for key in (
        "role_aliases",
        "skills",
        "excluded_keywords",
        "excluded_locations",
        "preferred_industries",
        "preferred_companies",
        "excluded_companies",
        "priority_skills",
        "employment_types",
        "source_families",
    ):
        plan[key] = _string_list(plan.get(key, []))
    if not plan["source_families"]:
        plan["source_families"] = [
            "greenhouse",
            "lever",
            "ashby",
            "smartrecruiters",
            "company_portal",
        ]
    plan["location_policy"] = plan.get("location_policy") or "preference_order"
    plan["role_policy"] = plan.get("role_policy") or "expanded_early_career"
    plan["freshness_policy"] = plan.get("freshness_policy") or "ranking"
    plan["metadata_policy"] = plan.get("metadata_policy") or "include_unknown"
    plan["seniority_policy"] = plan.get("seniority_policy") or "early_career"
    plan["source_policy"] = plan.get("source_policy") or "official_direct"
    return plan


class SearchPlanService:
    def __init__(self, database: Database, profiles: ProfileService):
        self.database = database
        self.profiles = profiles

    def compile(self) -> Dict[str, Any]:
        profile_row = self.profiles.active_profile()
        if not profile_row:
            raise ValueError("Complete onboarding before searching")
        preferences = self.profiles.preference_map()
        target_roles = preferences.get("target_roles", [])
        if isinstance(target_roles, str):
            target_roles = [target_roles]
        # Saved roles stay first, while resume-supported adjacent tracks prevent a
        # narrow label (for example only "Software Engineer") from hiding AI/LLM
        # or backend roles the candidate is demonstrably qualified to pursue.
        target_roles = list(
            dict.fromkeys(
                [
                    *target_roles,
                    *profile_row["profile"].get("role_families", []),
                ]
            )
        )
        aliases = self._role_aliases(target_roles)
        locations = preferences.get("preferred_locations", ["Remote"])
        if isinstance(locations, str):
            locations = [item.strip() for item in locations.split(",") if item.strip()]
        exclusions = preferences.get("excluded_keywords", [])
        if isinstance(exclusions, str):
            exclusions = [item.strip() for item in exclusions.split(",") if item.strip()]
        preference_version = self.profiles.preference_version()
        work_modes = preferences.get("work_modes", preferences.get("work_mode", []))
        if isinstance(work_modes, str):
            lowered = work_modes.casefold()
            work_modes = [
                mode for mode in ("remote", "hybrid", "onsite") if mode in lowered
            ]
        excluded_locations = preferences.get("excluded_locations", [])
        if isinstance(excluded_locations, str):
            excluded_locations = [excluded_locations]
        preferred_industries = self._list_preference(
            preferences.get("preferred_industries")
        )
        preferred_companies = self._list_preference(
            preferences.get("preferred_companies")
        )
        excluded_companies = self._list_preference(
            preferences.get("excluded_companies")
        )
        priority_skills = self._list_preference(preferences.get("priority_skills"))
        employment_types = self._list_preference(
            preferences.get("employment_types")
        )
        employment_types = list(
            dict.fromkeys(
                self._canonical_employment_type(value)
                for value in employment_types
                if self._canonical_employment_type(value)
            )
        )
        salary_min = preferences.get("salary_min")
        if not isinstance(salary_min, (int, float)) or salary_min < 0:
            salary_min = None
        salary_currency = preferences.get("salary_currency")
        if not (
            isinstance(salary_currency, str)
            and len(salary_currency) == 3
            and salary_currency.isascii()
            and salary_currency.isalpha()
            and salary_currency.isupper()
        ):
            salary_currency = None
        salary_period = preferences.get("salary_period")
        if not isinstance(salary_period, str) or not salary_period:
            salary_period = None
        plan = {
            "target_roles": target_roles or ["Software Engineer"],
            "role_aliases": list(dict.fromkeys(alias for alias in aliases if alias)),
            "skills": profile_row["profile"].get("skills", [])[:30],
            "locations": locations or ["Remote"],
            "work_modes": work_modes,
            "seniority_tolerance": preferences.get("seniority_tolerance"),
            "excluded_keywords": exclusions,
            "excluded_locations": excluded_locations,
            "preferred_industries": preferred_industries,
            "preferred_companies": preferred_companies,
            "excluded_companies": excluded_companies,
            "priority_skills": priority_skills,
            "employment_types": employment_types,
            "salary_min": salary_min,
            "salary_currency": salary_currency,
            "salary_period": salary_period,
            # Ordered preferences affect ranking. They are not exclusions unless a
            # one-time search explicitly asks for strict geography.
            "location_policy": "preference_order",
            "role_policy": "expanded_early_career",
            "freshness_policy": "ranking",
            "metadata_policy": "include_unknown",
            "seniority_policy": "early_career",
            "source_policy": preferences.get("source_policy", "official_direct"),
            "source_families": [
                "greenhouse",
                "lever",
                "ashby",
                "smartrecruiters",
                "company_portal",
            ],
            "freshness_hours": _freshness_hours(
                preferences.get("freshness_hours", 48)
            ),
            "generated_from": {
                "profile_version": profile_row["version"],
                "preference_version": preference_version,
            },
        }
        plan = normalize_search_plan(plan)
        version = stable_hash(plan)
        existing = self.database.fetch_one(
            "SELECT * FROM search_plans WHERE version = ?",
            (version,),
        )
        if not existing:
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE search_plans SET status = 'stale' WHERE status = 'active'"
                )
                connection.execute(
                    """
                    INSERT INTO search_plans(
                        id, version, profile_version, preference_version,
                        plan_json, status, expires_at
                    ) VALUES (?, ?, ?, ?, ?, 'active', ?)
                    """,
                    (
                        new_id(),
                        version,
                        profile_row["version"],
                        preference_version,
                        json_dumps(plan),
                        (utcnow() + timedelta(days=7)).isoformat(),
                    ),
                )
        elif existing["status"] != "active":
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE search_plans SET status = 'stale' WHERE status = 'active'"
                )
                connection.execute(
                    "UPDATE search_plans SET status = 'active' WHERE version = ?",
                    (version,),
                )
        return self.get(version)

    def compile_temporary(self, instruction: str) -> Dict[str, Any]:
        """Compile one explicit search override without mutating saved preferences."""

        normalized = " ".join(instruction.split())
        if not normalized:
            raise ValueError("Describe the one-time search you want to run")
        base = self.compile()
        interpreted = interpret_preference_message(
            normalized, self.profiles.preference_map()
        )
        if not interpreted or not interpreted.get("updates"):
            raise ValueError(
                "Carivyo could not confidently identify roles, locations, work modes, exclusions, or a freshness window"
            )
        plan = dict(base["plan"])
        field_map = {
            "target_roles": "target_roles",
            "preferred_locations": "locations",
            "work_modes": "work_modes",
            "excluded_locations": "excluded_locations",
            "excluded_keywords": "excluded_keywords",
            "freshness_hours": "freshness_hours",
            "location_policy": "location_policy",
        }
        applied: List[Dict[str, Any]] = []
        for update in interpreted["updates"]:
            target = field_map.get(str(update.get("key")))
            if not target:
                continue
            value = update.get("value")
            if target == "freshness_hours":
                value = max(1, min(168, int(value)))
            elif target in {
                "target_roles",
                "locations",
                "work_modes",
                "excluded_locations",
                "excluded_keywords",
            }:
                value = self._list_preference(value)
            plan[target] = value
            applied.append({"field": target, "value": value})
        if not applied:
            raise ValueError("The one-time instruction did not produce a safe search override")
        if "target_roles" in {item["field"] for item in applied}:
            plan["role_aliases"] = self._role_aliases(plan["target_roles"])
            plan["role_policy"] = "strict"
        if "freshness_hours" in {item["field"] for item in applied}:
            plan["freshness_policy"] = "strict"
        plan["temporary_override"] = {
            "instruction": normalized,
            "applied": applied,
            "saved_preferences_changed": False,
        }
        plan["generated_from"] = {
            **plan.get("generated_from", {}),
            "base_plan_version": base["version"],
        }
        version = stable_hash(plan)
        existing = self.database.fetch_one(
            "SELECT version FROM search_plans WHERE version = ?", (version,)
        )
        if not existing:
            self.database.execute(
                """
                INSERT INTO search_plans(
                    id, version, profile_version, preference_version,
                    plan_json, status, expires_at
                ) VALUES (?, ?, ?, ?, ?, 'temporary', ?)
                """,
                (
                    new_id(),
                    version,
                    base["profile_version"],
                    base["preference_version"],
                    json_dumps(plan),
                    (utcnow() + timedelta(hours=24)).isoformat(),
                ),
            )
        return self.get(version)

    @staticmethod
    def _role_aliases(target_roles: List[str]) -> List[str]:
        aliases: List[str] = []
        for role in target_roles:
            lowered = role.casefold()
            aliases.append(role)
            for key, values in ROLE_ALIASES.items():
                if key in lowered:
                    aliases.extend(values)
        return list(dict.fromkeys(alias for alias in aliases if alias))

    @staticmethod
    def _canonical_employment_type(value: Any) -> str:
        normalized = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
        aliases = {
            "fulltime": "full_time",
            "full_time": "full_time",
            "parttime": "part_time",
            "part_time": "part_time",
            "contractor": "contract",
            "contract": "contract",
            "temporary": "contract",
            "intern": "internship",
            "internship": "internship",
        }
        return aliases.get(normalized, "")

    @staticmethod
    def _list_preference(value: Any) -> List[str]:
        if isinstance(value, str):
            values = value.split(",")
        elif isinstance(value, list):
            values = value
        else:
            return []
        normalized: List[str] = []
        seen = set()
        for item in values:
            if not isinstance(item, str):
                continue
            cleaned = " ".join(item.split())
            deduplication_key = cleaned.casefold()
            if not cleaned or deduplication_key in seen:
                continue
            seen.add(deduplication_key)
            normalized.append(cleaned)
        return normalized

    def get(self, version: str) -> Dict[str, Any]:
        row = self.database.fetch_one(
            "SELECT * FROM search_plans WHERE version = ?",
            (version,),
        )
        if not row:
            raise KeyError("Search plan not found")
        return {
            **row,
            "plan": normalize_search_plan(json_loads(row["plan_json"], {})),
        }

    def active(self) -> Dict[str, Any]:
        row = self.database.fetch_one(
            """
            SELECT version FROM search_plans
            WHERE status = 'active' AND preference_version = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (self.profiles.preference_version(),),
        )
        return self.get(row["version"]) if row else self.compile()
