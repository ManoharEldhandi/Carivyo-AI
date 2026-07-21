from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_now() -> str:
    return utcnow().isoformat()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_loads(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def stable_hash(*parts: Any) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(json_dumps(part).encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def estimate_tokens(value: str) -> int:
    if not value:
        return 0
    return max(1, (len(value) + 3) // 4)


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def tokenize(value: str) -> List[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9+#.]{2,}", value.lower())
        if token not in STOP_WORDS
    ]


def unique(items: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for item in items:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


STOP_WORDS = {
    "and",
    "the",
    "for",
    "with",
    "from",
    "that",
    "this",
    "you",
    "your",
    "our",
    "are",
    "will",
    "have",
    "has",
    "into",
    "using",
    "work",
    "role",
    "team",
    "job",
    "about",
    "their",
    "they",
    "who",
    "but",
    "not",
    "all",
    "can",
    "years",
    "year",
}
