"""Configuration for the review portal (design section 7.10).

The portal has its own listener and client allowlist, but uses the pipeline's exact SQL
connection settings, including its database and login.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from alerts_bi_shared.config.env import load_dotenv, read_int, read_str
from alerts_bi_shared.config.sql import SqlConfig, load_sql_config
from alerts_bi_shared.ui.html import safe_link

__all__ = [
    "DEFAULT_ALLOWED_NETWORKS",
    "DEFAULT_MIGRATION_STATUS_TIMEOUT",
    "DEFAULT_PORTAL_HOST",
    "DEFAULT_PORTAL_PORT",
    "IpNetwork",
    "PortalSettings",
    "load_portal_settings",
    "parse_networks",
]

IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

DEFAULT_PORTAL_HOST = "127.0.0.1"
DEFAULT_PORTAL_PORT = 8100

#: Loopback plus the private address ranges: reachable from a company network, refused from
#: anywhere else. Behind a reverse proxy the client address is the proxy's, so narrow this to
#: the proxy there.
DEFAULT_ALLOWED_NETWORKS = (
    "127.0.0.0/8",
    "::1/128",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "fc00::/7",
)

#: Seconds a page waits for alerts-migration's status answer before showing plain buttons.
DEFAULT_MIGRATION_STATUS_TIMEOUT = 1.0
MAX_MIGRATION_STATUS_TIMEOUT = 10.0
#: scheme://host[:port], lower case; anything else would not be a safe CSP source.
_ORIGIN = re.compile(r"^https?://(\[[0-9a-f:.]+\]|[a-z0-9.-]+)(:[0-9]{1,5})?$")


def parse_networks(values: tuple[str, ...]) -> tuple[IpNetwork, ...]:
    """Parse an allowlist, refusing an empty one and any entry that is not a network."""
    if not values:
        raise ValueError("PORTAL_ALLOWED_NETWORKS is empty; the portal would refuse everyone")
    networks: list[IpNetwork] = []
    for value in values:
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError as exc:
            raise ValueError(f"PORTAL_ALLOWED_NETWORKS entry {value!r} is not a network") from exc
    return tuple(networks)


def url_origin(url: str) -> str:
    """scheme://host[:port] of an absolute http(s) URL."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


def parse_base_url(name: str, value: str) -> str | None:
    """An optional http(s) base URL, without a trailing slash; empty means unset."""
    value = value.strip()
    if not value:
        return None
    parts = urlsplit(value)
    if (
        safe_link(value) is None
        or parts.query
        or parts.fragment
        or "@" in parts.netloc
        or not _ORIGIN.match(url_origin(value))
    ):
        raise ValueError(
            f"{name} must be an http(s) URL with a host and no user, query or fragment"
        )
    return value.rstrip("/")


@dataclass(frozen=True, slots=True)
class PortalSettings:
    """Where the portal listens, whom it admits, and its SQL connection."""

    sql: SqlConfig
    database: str
    host: str = DEFAULT_PORTAL_HOST
    port: int = DEFAULT_PORTAL_PORT
    allowed_networks: tuple[str, ...] = DEFAULT_ALLOWED_NETWORKS
    page_size: int = 25
    #: The alerts-migration web app; None hides every migration link.
    migration_url: str | None = None
    #: Where its API is; None means migration_url, which proxies /api to the backend.
    migration_api_url: str | None = None
    migration_status_token: str | None = field(default=None, repr=False)
    migration_status_timeout: float = DEFAULT_MIGRATION_STATUS_TIMEOUT

    def networks(self) -> tuple[IpNetwork, ...]:
        return parse_networks(self.allowed_networks)

    @property
    def migration_origin(self) -> str | None:
        return None if self.migration_url is None else url_origin(self.migration_url)

    @property
    def migration_status_url(self) -> str | None:
        """The API base for the migrated-rules call, when the links are on and a token is set."""
        if self.migration_url is None or not self.migration_status_token:
            return None
        return self.migration_api_url or self.migration_url


def load_portal_settings(
    sql: SqlConfig | None = None,
    host: str | None = None,
    port: int | None = None,
) -> PortalSettings:
    """Read portal settings while reusing the application's SQL connection exactly."""
    load_dotenv()
    resolved = sql or load_sql_config()
    networks = tuple(
        part.strip()
        for part in read_str("PORTAL_ALLOWED_NETWORKS", ",".join(DEFAULT_ALLOWED_NETWORKS)).split(
            ","
        )
        if part.strip()
    )
    parse_networks(networks)
    page_size = read_int("PORTAL_PAGE_SIZE", 25)
    if not 1 <= page_size <= 200:
        raise ValueError(f"PORTAL_PAGE_SIZE must be between 1 and 200, got {page_size}")
    migration_url = parse_base_url("PORTAL_MIGRATION_URL", read_str("PORTAL_MIGRATION_URL"))
    migration_api_url = parse_base_url(
        "PORTAL_MIGRATION_API_URL", read_str("PORTAL_MIGRATION_API_URL")
    )
    timeout_text = read_str(
        "PORTAL_MIGRATION_STATUS_TIMEOUT", str(DEFAULT_MIGRATION_STATUS_TIMEOUT)
    )
    try:
        timeout = float(timeout_text)
    except ValueError:
        timeout = -1.0
    if not 0 < timeout <= MAX_MIGRATION_STATUS_TIMEOUT:
        raise ValueError(
            "PORTAL_MIGRATION_STATUS_TIMEOUT must be seconds above 0 and at most "
            f"{MAX_MIGRATION_STATUS_TIMEOUT:g}, got {timeout_text!r}"
        )
    return PortalSettings(
        sql=resolved,
        database=resolved.database,
        host=host or read_str("PORTAL_HOST", DEFAULT_PORTAL_HOST),
        port=port or read_int("PORTAL_PORT", DEFAULT_PORTAL_PORT),
        allowed_networks=networks,
        page_size=page_size,
        migration_url=migration_url,
        migration_api_url=migration_api_url or migration_url,
        migration_status_token=read_str("PORTAL_MIGRATION_STATUS_TOKEN").strip() or None,
        migration_status_timeout=timeout,
    )
