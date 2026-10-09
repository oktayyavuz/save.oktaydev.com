"""URL extraction and validation (blocks requests to internal networks)."""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlsplit

from . import config

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


class InvalidURL(ValueError):
    pass


def find_urls(text: str) -> list[str]:
    return [u.rstrip(").,;!?»”'\"") for u in URL_RE.findall(text or "")]


def _is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


def normalize(url: str) -> str:
    """Return a cleaned URL or raise InvalidURL."""
    url = (url or "").strip()
    if not url:
        raise InvalidURL("empty")
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    if len(url) > 2048:
        raise InvalidURL("too_long")
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise InvalidURL("scheme")
    if parts.username or parts.password:
        raise InvalidURL("credentials")
    host = parts.hostname.lower()
    if not config.ALLOW_PRIVATE_URLS:
        if host in ("localhost",) or host.endswith((".local", ".internal", ".localhost")):
            raise InvalidURL("private")
        try:
            infos = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
        except (socket.gaierror, UnicodeError):
            raise InvalidURL("dns") from None
        for info in infos:
            if not _is_public_ip(info[4][0]):
                raise InvalidURL("private")
    return url


def domain_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host
