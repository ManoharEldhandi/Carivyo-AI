from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional


LOCATION_ALIASES: Dict[str, tuple[str, ...]] = {
    "Bengaluru": ("bengaluru", "bangalore"),
    "Hyderabad": ("hyderabad",),
    "Chennai": ("chennai", "madras"),
    "Pune": ("pune",),
    "Mumbai": ("mumbai", "bombay"),
    "Delhi NCR": ("delhi ncr", "new delhi", "delhi", "gurugram", "gurgaon", "noida"),
    "Remote India": (
        "remote india",
        "india remote",
        "remote within india",
        "remote in india",
        "work from home india",
    ),
    "India": ("anywhere in india", "across india", "pan india", "india"),
    "Singapore": ("singapore",),
    "Paris": ("paris",),
    "London": ("london",),
    "United States": ("united states", "usa", "u.s.", "us only"),
}

WORK_MODES = {
    "remote": ("remote", "work from home", "wfh"),
    "hybrid": ("hybrid",),
    "onsite": ("on-site", "onsite", "in office", "office based"),
}

# These words usually describe a job family, not a forbidden word anywhere in
# a job description. For example, avoiding "support roles" must not remove a
# software-engineering job merely because it mentions production support.
TITLE_SCOPED_EXCLUSIONS = {
    "business development",
    "customer success",
    "customer support",
    "data analyst",
    "devops",
    "devops engineer",
    "front end",
    "frontend",
    "frontend engineer",
    "frontend developer",
    "marketing",
    "qa",
    "recruiter",
    "recruiting",
    "sales",
    "support",
    "testing",
}

STRICT_LOCATION_PHRASES = (
    "only selected location",
    "only selected area",
    "outside selected",
    "outside my selected",
    "other location",
    "other area",
    "elsewhere",
    "nothing outside",
    "no jobs outside",
    "don't include jobs from outside",
    "do not include jobs from outside",
    "dont include jobs from outside",
    "keep the location policy strict",
    "keep location policy strict",
    "location policy strict",
    "strict location policy",
)


def unique(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = re.sub(r"\s+", " ", value).strip(" ,.;")
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def canonical_location(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip(" ,.;").casefold()
    for canonical, aliases in LOCATION_ALIASES.items():
        if normalized == canonical.casefold() or normalized in aliases:
            return canonical
    return value.strip(" ,.;").title()


def parse_locations(text: str) -> List[str]:
    """Extract ordered location intent without treating prose as a keyword list."""
    lowered = re.sub(r"\s+", " ", text).casefold()
    mentions: List[tuple[int, str]] = []
    for canonical, aliases in LOCATION_ALIASES.items():
        positions = [lowered.find(alias) for alias in aliases if lowered.find(alias) >= 0]
        if positions:
            mentions.append((min(positions), canonical))
    if mentions:
        # Remote India is more specific than India when both match the same phrase.
        ordered = [value for _, value in sorted(mentions)]
        if "Remote India" in ordered:
            ordered = [value for value in ordered if value != "India"]
        return unique(ordered)

    cleaned = re.sub(
        r"\b(?:only|first|preferred?|prioriti[sz]e|locations?|cities|areas?|jobs?|roles?|in|from)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    parts = re.split(r"\s*(?:,|;|\||\bthen\b|\band\b)\s*", cleaned)
    return unique(canonical_location(part) for part in parts if part.strip())


def parse_known_locations(text: str) -> List[str]:
    """Return only catalog-backed geographic mentions, never arbitrary prose."""

    lowered = re.sub(r"\s+", " ", text).casefold()
    mentions: List[tuple[int, str]] = []
    for canonical, aliases in LOCATION_ALIASES.items():
        positions = [
            lowered.find(alias)
            for alias in aliases
            if lowered.find(alias) >= 0
        ]
        if positions:
            mentions.append((min(positions), canonical))
    ordered = [value for _, value in sorted(mentions)]
    if "Remote India" in ordered:
        ordered = [value for value in ordered if value != "India"]
    return unique(ordered)


def parse_roles(text: str) -> List[str]:
    cleaned = re.sub(
        r"\b(?:find|show|search|for|me|more|only|first|prioriti[sz]e|roles?|jobs?)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    cleaned = re.split(r"\b(?:in|from|within|located)\b", cleaned, maxsplit=1, flags=re.IGNORECASE)[0]
    parts = re.split(r"\s*(?:,|;|\||\bthen\b|\band\b|\bor\b)\s*", cleaned)
    return unique(part.strip().title() for part in parts if len(part.strip()) >= 2)


def parse_work_modes(text: str) -> List[str]:
    lowered = text.casefold()
    return [
        mode
        for mode, aliases in WORK_MODES.items()
        if any(alias in lowered for alias in aliases)
    ]


def parse_freshness_hours(text: str, default: int = 48) -> int:
    lowered = text.casefold()
    hour = re.search(r"(?:last|within|under)\s+(\d{1,3})\s*(?:hours?|hrs?)", lowered)
    if hour:
        return max(1, min(168, int(hour.group(1))))
    day = re.search(r"(?:last|within|under)\s+(\d{1,2})\s*days?", lowered)
    if day:
        return max(1, min(168, int(day.group(1)) * 24))
    if "today" in lowered or "last day" in lowered:
        return 24
    return default


def split_exclusions(text: str) -> List[str]:
    cleaned = re.sub(
        r"^(?:stop showing|avoid|exclude|do not include|don't include|dont include|no)\s+",
        "",
        text.strip(),
        flags=re.IGNORECASE,
    )
    parts = re.split(
        r"\s*(?:,|;|\||\band\b|\bor\b|(?<=[.!?])\s+)\s*",
        cleaned,
        flags=re.IGNORECASE,
    )
    values: List[str] = []
    for part in parts:
        lowered = re.sub(r"\s+", " ", part).strip().casefold()
        if not lowered:
            continue
        if any(phrase in lowered for phrase in STRICT_LOCATION_PHRASES):
            continue
        if re.search(r"\b(?:keep|make|set)\b.*\blocations?\b.*\bstrict\b", lowered):
            continue
        value = re.sub(r"\b(?:roles?|jobs?)\b", " ", lowered, flags=re.IGNORECASE)
        value = re.sub(r"^(?:avoid|exclude|no|do not include|don't include|dont include)\s+", "", value)
        if value.strip(" ,.;"):
            values.append(value)
    return unique(values)


def excluded_term_matches(title: str, description: str, term: str) -> bool:
    """Apply role-like exclusions to titles and other exclusions to all job text."""

    normalized_term = _match_text(term)
    if not normalized_term:
        return False
    role_term = re.sub(
        r"\b(?:heavy|focused|only)\b",
        " ",
        normalized_term,
    )
    role_term = re.sub(r"\s+", " ", role_term).strip()
    haystack = _match_text(title) if role_term in TITLE_SCOPED_EXCLUSIONS else _match_text(
        f"{title} {description}"
    )
    phrase = role_term if role_term in TITLE_SCOPED_EXCLUSIONS else normalized_term
    return bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", haystack))


def _match_text(value: str) -> str:
    return re.sub(r"[^a-z0-9+#.]+", " ", value.casefold()).strip()


def interpret_onboarding_answer(
    question_id: str,
    answer: str,
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    normalized = answer.strip()
    decide = normalized.casefold() in {
        "decide for me",
        "you decide",
        "skip",
        "not sure",
    }
    if question_id == "role_focus":
        roles = summary.get("role_tracks", ["Software Engineer"])[:3] if decide else parse_roles(normalized)
        return {"key": "target_roles", "value": roles, "kind": "hard", "source": "explicit"}
    if question_id == "preferred_locations":
        locations = ["Remote India"] if decide else parse_locations(normalized)
        return {"key": "preferred_locations", "value": locations, "kind": "hard", "source": "explicit"}
    if question_id == "work_mode":
        modes = ["remote", "hybrid"] if decide else parse_work_modes(normalized)
        return {"key": "work_modes", "value": modes, "kind": "hard", "source": "explicit"}
    if question_id == "seniority":
        value = "matching current evidence with modest stretch" if decide else normalized
        return {"key": "seniority_tolerance", "value": value, "kind": "hard", "source": "explicit"}
    exclusions = [] if decide else split_exclusions(normalized)
    return {"key": "excluded_keywords", "value": exclusions, "kind": "negative", "source": "explicit"}


def interpret_preference_message(
    message: str,
    current: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Return high-confidence structured mutations; ambiguous text is left to chat AI."""
    lowered = re.sub(r"\s+", " ", message).strip().casefold()
    updates: List[Dict[str, Any]] = []

    # "Nothing outside X, Y, or Z" defines the allowed location set. Treating
    # those named places as exclusions would invert the user's instruction.
    allowlist_command = re.search(
        r"(?:do not|don't|dont|never|no)\s+(?:include|show|find)?\s*(?:me\s+)?(?:jobs?|roles?)?\s*(?:from\s+)?outside\s+(?P<locations>.+)$",
        message,
        flags=re.IGNORECASE,
    )
    handled_location_allowlist = False
    if allowlist_command:
        locations = parse_known_locations(allowlist_command.group("locations"))
        if locations:
            existing_excluded = current.get("excluded_locations", [])
            if isinstance(existing_excluded, str):
                existing_excluded = [existing_excluded]
            allowed_keys = {location.casefold() for location in locations}
            updates.extend(
                [
                    {
                        "key": "preferred_locations",
                        "value": locations,
                        "kind": "hard",
                        "operation": "replace",
                    },
                    {
                        "key": "excluded_locations",
                        "value": [
                            value
                            for value in existing_excluded
                            if canonical_location(str(value)).casefold() not in allowed_keys
                        ],
                        "kind": "negative",
                        "operation": "replace",
                    },
                    {
                        "key": "location_policy",
                        "value": "strict",
                        "kind": "hard",
                        "operation": "replace",
                    },
                ]
            )
            handled_location_allowlist = True

    strict_location = any(phrase in lowered for phrase in STRICT_LOCATION_PHRASES)
    if strict_location:
        updates.append(
            {"key": "location_policy", "value": "strict", "kind": "hard", "operation": "replace"}
        )

    freshness = parse_freshness_hours(message)
    if re.search(r"\b(?:last|within|under|today)\b", lowered) and re.search(
        r"\b(?:hours?|hrs?|days?|today)\b", lowered
    ):
        updates.append(
            {"key": "freshness_hours", "value": freshness, "kind": "hard", "operation": "replace"}
        )

    explicit_work_modes = parse_work_modes(message)
    if explicit_work_modes and re.search(
        r"\b(?:remote|hybrid|on[ -]?site|in office|office based|wfh)\b",
        lowered,
    ):
        updates.append(
            {
                "key": "work_modes",
                "value": explicit_work_modes,
                "kind": "hard",
                "operation": "replace",
            }
        )

    find_match = re.search(
        r"(?:find|show|search)(?: me)?(?: more)?\s+(?P<role>.+?)(?:\s+(?:roles?|jobs?))?(?:\s+in\s+(?P<location>.+))?$",
        message,
        flags=re.IGNORECASE,
    )
    if find_match:
        role_text = find_match.group("role") or ""
        roles = parse_roles(role_text)
        if roles:
            updates.append(
                {"key": "target_roles", "value": roles, "kind": "hard", "operation": "replace"}
            )
        location_text = find_match.group("location")
        if location_text:
            locations = parse_locations(location_text)
            if locations:
                updates.extend(
                    [
                        {"key": "preferred_locations", "value": locations, "kind": "hard", "operation": "replace"},
                        {"key": "location_policy", "value": "strict", "kind": "hard", "operation": "replace"},
                    ]
                )

    bare_search = re.search(
        r"^\s*(?P<role>.+?)\s+(?:roles?|jobs?)\s+in\s+(?P<location>.+)$",
        message,
        flags=re.IGNORECASE,
    )
    if bare_search and not lowered.startswith(
        ("avoid ", "exclude ", "do not include", "don't include", "dont include", "no ")
    ):
        roles = parse_roles(bare_search.group("role"))
        locations = parse_known_locations(bare_search.group("location"))
        if roles:
            updates.append(
                {"key": "target_roles", "value": roles, "kind": "hard", "operation": "replace"}
            )
        if locations:
            updates.extend(
                [
                    {"key": "preferred_locations", "value": locations, "kind": "hard", "operation": "replace"},
                    {"key": "location_policy", "value": "strict", "kind": "hard", "operation": "replace"},
                ]
            )

    location_command = re.search(
        r"(?:locations?|cities|areas?)\s*(?:are|to|:|=)\s*(?P<locations>.+)$",
        message,
        flags=re.IGNORECASE,
    )
    if location_command:
        locations = parse_locations(location_command.group("locations"))
        if locations:
            updates.extend(
                [
                    {"key": "preferred_locations", "value": locations, "kind": "hard", "operation": "replace"},
                    {"key": "location_policy", "value": "strict", "kind": "hard", "operation": "replace"},
                ]
            )

    starts_exclusion = lowered.startswith(
        ("stop showing", "avoid ", "exclude ", "do not include", "don't include", "dont include", "no ")
    )
    if starts_exclusion and not handled_location_allowlist:
        # A phrase with explicit geographic markers changes location semantics,
        # never the generic keyword bag.
        known_locations = parse_known_locations(message)
        geographic = bool(
            known_locations
            or re.search(r"\b(?:in|from|location|city|area)\b", lowered)
        )
        locations = known_locations if geographic else []
        if locations:
            existing = current.get("excluded_locations", [])
            if isinstance(existing, str):
                existing = [existing]
            updates.append(
                {
                    "key": "excluded_locations",
                    "value": unique([*existing, *locations]),
                    "kind": "negative",
                    "operation": "add",
                }
            )
        else:
            values = split_exclusions(message)
            if values:
                existing = current.get("excluded_keywords", [])
                if isinstance(existing, str):
                    existing = [existing]
                updates.append(
                    {
                        "key": "excluded_keywords",
                        "value": unique([*existing, *values]),
                        "kind": "negative",
                        "operation": "add",
                    }
                )

    if not updates:
        return None
    deduped: Dict[str, Dict[str, Any]] = {}
    for update in updates:
        deduped[update["key"]] = update
    return {
        "updates": list(deduped.values()),
        "confidence": 1.0,
        "search_requested": True,
    }
