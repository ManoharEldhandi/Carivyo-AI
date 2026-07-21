from __future__ import annotations

import asyncio
import html
import re
from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

import httpx

from app.security import sanitize_untrusted_text


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def html_to_text(value: str) -> str:
    parser = TextExtractor()
    parser.feed(value or "")
    return sanitize_untrusted_text(html.unescape("\n".join(parser.parts)))


def parse_iso(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


@dataclass
class JobCandidate:
    connector_id: str
    external_id: str
    title: str
    company: str
    description: str
    location: str
    work_mode: Optional[str]
    employment_type: Optional[str]
    posted_at: Optional[str]
    posted_semantics: Optional[str]
    apply_url: str
    source_url: str
    source_family: str
    raw: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConnectorFetchResult(Sequence[JobCandidate]):
    """Candidates plus whether absence is authoritative for this observation."""

    candidates: List[JobCandidate]
    complete: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.metadata = {**self.metadata, "complete": self.complete}

    @property
    def is_complete(self) -> bool:
        return self.complete

    @property
    def completeness(self) -> Dict[str, Any]:
        return dict(self.metadata)

    def __iter__(self) -> Iterator[JobCandidate]:
        return iter(self.candidates)

    def __len__(self) -> int:
        return len(self.candidates)

    def __getitem__(self, index: Any) -> Any:
        return self.candidates[index]

    @classmethod
    def coerce(
        cls,
        value: "ConnectorFetchResult | Sequence[JobCandidate]",
    ) -> "ConnectorFetchResult":
        if isinstance(value, cls):
            return value
        return cls(candidates=list(value))


class ConnectorError(RuntimeError):
    pass


class ConnectorNotFound(ConnectorError):
    pass


class OfficialConnector(ABC):
    family: str
    source_domain: str
    parser_version = "1.0"

    def __init__(
        self,
        connector_id: str,
        name: str,
        company: str,
        config: Dict[str, Any],
    ):
        self.connector_id = connector_id
        self.name = name
        self.company = company
        self.config = config

    @abstractmethod
    async def fetch(self, client: httpx.AsyncClient) -> ConnectorFetchResult:
        raise NotImplementedError

    async def fetch_job(
        self,
        client: httpx.AsyncClient,
        external_id: str,
    ) -> Optional[JobCandidate]:
        result = ConnectorFetchResult.coerce(await self.fetch(client))
        current = next(
            (
                candidate
                for candidate in result.candidates
                if candidate.external_id == external_id
            ),
            None,
        )
        if current is None and not result.complete:
            raise ConnectorError(
                f"{self.name} returned an incomplete result while revalidating {external_id}"
            )
        return current

    async def request_json(
        self,
        client: httpx.AsyncClient,
        url: str,
        attempts: int = 3,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        error: Optional[Exception] = None
        for attempt in range(attempts):
            try:
                response = await client.get(
                    url,
                    params=params,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "Carivyo/0.1 local job verifier",
                    },
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    raise ConnectorNotFound(
                        f"{self.name} resource was not found: {url}"
                    ) from exc
                status_code = exc.response.status_code
                if status_code not in {408, 429} and status_code < 500:
                    raise ConnectorError(
                        f"{self.name} rejected the request with HTTP {status_code}"
                    ) from exc
                error = exc
                if attempt + 1 < attempts:
                    retry_after = exc.response.headers.get("Retry-After")
                    try:
                        delay = min(5.0, max(0.0, float(retry_after or "")))
                    except ValueError:
                        delay = 0.25 * (2**attempt)
                    await asyncio.sleep(delay)
            except (httpx.HTTPError, ValueError) as exc:
                error = exc
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.25 * (2**attempt))
        raise ConnectorError(f"{self.name} failed: {error}")


def infer_work_mode(location: str, explicit: Optional[str] = None) -> Optional[str]:
    def classify(value: Optional[str]) -> Optional[str]:
        normalized = re.sub(r"\s+", " ", value or "").strip().casefold()
        if not normalized:
            return None
        if re.search(r"\bremote\b|\bwork[ -]from[ -]home\b|\bwfh\b", normalized):
            return "remote"
        if re.search(r"\bhybrid\b", normalized):
            return "hybrid"
        if re.search(
            r"\bon[ -]?site\b|\bin[ -]office\b|\boffice[ -]based\b|"
            r"\bwork[ -]from[ -]office\b|\bwfo\b",
            normalized,
        ):
            return "onsite"
        return None

    explicit_mode = classify(explicit)
    if explicit_mode:
        return explicit_mode
    location_mode = classify(location)
    if location_mode:
        return location_mode
    return None


def clean_description(*parts: Optional[str]) -> str:
    value = "\n".join(part for part in parts if part)
    if "<" in value and ">" in value:
        value = html_to_text(value)
    return sanitize_untrusted_text(re.sub(r"\n{3,}", "\n\n", value))
