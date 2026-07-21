from __future__ import annotations

import hmac
import ipaddress
import re
import secrets
import socket
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Iterable, Optional
from urllib.parse import urlparse

from fastapi import Header, HTTPException, Request, status


CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class UnsafeUrl(ValueError):
    pass


class LocalRateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0):
        self.limit = max(1, limit)
        self.window_seconds = window_seconds
        self.events: Dict[str, Deque[float]] = defaultdict(deque)

    def retry_after(self, key: str) -> Optional[int]:
        now = time.monotonic()
        bucket = self.events[key]
        cutoff = now - self.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= self.limit:
            return max(1, int(self.window_seconds - (now - bucket[0])) + 1)
        bucket.append(now)
        return None


def sanitize_untrusted_text(value: str, limit: int = 120_000) -> str:
    return CONTROL_CHARACTERS.sub("", value).strip()[:limit]


def validate_outbound_url(
    url: str,
    allowed_hosts: Optional[Iterable[str]] = None,
    resolve_dns: bool = True,
) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeUrl("Only absolute HTTP(S) URLs are allowed")
    if parsed.username or parsed.password:
        raise UnsafeUrl("Credential-bearing URLs are not allowed")

    hostname = parsed.hostname.rstrip(".").lower()
    if allowed_hosts:
        allowed = {host.rstrip(".").lower() for host in allowed_hosts}
        if hostname not in allowed and not any(
            hostname.endswith("." + host) for host in allowed
        ):
            raise UnsafeUrl("URL host is not allowed")

    try:
        literal = ipaddress.ip_address(hostname)
        addresses = [literal]
    except ValueError:
        addresses = []
        if resolve_dns:
            try:
                addresses = [
                    ipaddress.ip_address(item[4][0])
                    for item in socket.getaddrinfo(hostname, parsed.port or 443)
                ]
            except socket.gaierror as exc:
                raise UnsafeUrl("URL hostname could not be resolved") from exc

    for address in addresses:
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise UnsafeUrl("Private and local network targets are not allowed")
    return url


@dataclass(frozen=True)
class SessionSecurity:
    allowed_origins: tuple[str, ...]
    token: str
    bootstrap_token: str

    @classmethod
    def create(
        cls,
        allowed_origins: Iterable[str],
        bootstrap_token: Optional[str] = None,
    ) -> "SessionSecurity":
        return cls(
            tuple(allowed_origins),
            secrets.token_urlsafe(32),
            bootstrap_token or secrets.token_urlsafe(32),
        )

    @staticmethod
    def _require_loopback_peer(request: Request) -> None:
        host = request.client.host if request.client else ""
        if host == "testclient":
            return
        try:
            if ipaddress.ip_address(host).is_loopback:
                return
        except ValueError:
            pass
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Carivyo accepts only loopback clients",
        )

    def validate_origin(self, request: Request) -> None:
        self._require_loopback_peer(request)
        origin = request.headers.get("origin")
        if origin is None:
            if request.client and request.client.host in {"127.0.0.1", "::1", "testclient"}:
                return
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Missing Origin header",
            )
        if origin not in self.allowed_origins:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Origin is not allowed",
            )

    def require_bootstrap(
        self,
        request: Request,
        supplied_token: Optional[str],
    ) -> None:
        self.validate_origin(request)
        if not supplied_token or not hmac.compare_digest(
            supplied_token, self.bootstrap_token
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Carivyo's launch session expired. Restart Carivyo.",
            )

    def require_session(
        self,
        request: Request,
        x_carivyo_session: Optional[str] = Header(default=None),
    ) -> None:
        self.validate_origin(request)
        if not x_carivyo_session or not hmac.compare_digest(
            x_carivyo_session, self.token
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid local session token",
            )
