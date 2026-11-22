"""The hand-off to alerts-migration: which alerts it can migrate, the links that open them there,
and which of their rules it has already migrated.

Readers still only send GETs. The one outbound call asks alerts-migration which rule UIDs are
migrated, once per page and bounded by a timeout; when it fails the page shows plain "Migrate"
links.
"""

from __future__ import annotations

import json
import re
import urllib.request
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import quote, urlencode, urlparse

from alerts_bi_shared.logging_setup import log
from alerts_bi_shared.ui.html import safe_link

from .queries import AlertRow

__all__ = [
    "MAX_STATUS_UIDS",
    "STATUS_PATH",
    "MigrationStatus",
    "MigrationView",
    "migratable_rule_url",
    "rule_uid",
]

STATUS_PATH: Final = "/api/rules/migration-status"
#: The status endpoint accepts at most this many UIDs per call.
MAX_STATUS_UIDS: Final = 100
_MAX_RESPONSE_BYTES: Final = 256 * 1024
# Grafana rule pages, as migration-compliance parses them, without its last-segment fallback.
_RULE_PATHS: Final = (
    re.compile(r"/alerting/grafana/(?P<uid>[^/]+)/(?:view|edit)"),
    re.compile(r"/alerting/(?P<uid>[^/]+)/(?:view|edit)"),
)
_RESERVED: Final = frozenset({"view", "edit", "new", "grafana", "alerting"})


def migratable_rule_url(alert: AlertRow) -> str | None:
    """The rule URL to hand over, for a v1 Grafana alert with an http(s) rule link."""
    if alert.alert_schema != "v1" or (alert.provider or "").lower() != "grafana":
        return None
    return safe_link(alert.alert_rule_url)


def rule_uid(rule_url: str) -> str | None:
    """The Grafana rule UID in a rule page URL; None for any other URL."""
    try:
        path = urlparse(rule_url).path.rstrip("/")
    except ValueError:
        return None
    for pattern in _RULE_PATHS:
        match = pattern.search(path)
        if match and match.group("uid") not in _RESERVED:
            return match.group("uid")
    return None


@dataclass(frozen=True, slots=True)
class MigrationView:
    """What a page needs to draw the hand-off: the web app and the rules already migrated."""

    url: str
    migrated: frozenset[str] = frozenset()

    def href(self, rule_url: str) -> str:
        return f"{self.url}/?{urlencode({'rule_url': rule_url}, quote_via=quote)}"

    def is_migrated(self, rule_url: str) -> bool:
        uid = rule_uid(rule_url)
        return uid is not None and uid in self.migrated


class _StatusError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect fails the call: following it would send the token on."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class MigrationStatus:
    """Asks alerts-migration which rules it has migrated, at most ``timeout`` seconds per page."""

    def __init__(self, api_url: str, token: str, timeout: float) -> None:
        self._endpoint = api_url + STATUS_PATH
        self._token = token
        self._timeout = timeout
        self._opener = urllib.request.build_opener(_NoRedirect())
        # The socket timeout does not bound DNS or a slow body, so the page waits on a future.
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="migration-status")

    def migrated(self, rule_urls: Iterable[str]) -> frozenset[str]:
        """The UIDs among these rules that are migrated; empty when alerts-migration fails."""
        uids = list(dict.fromkeys(uid for url in rule_urls if (uid := rule_uid(url))))
        if not uids:
            return frozenset()
        future = self._pool.submit(self._ask, uids[:MAX_STATUS_UIDS])
        try:
            return future.result(timeout=self._timeout)
        except FutureTimeout:
            future.cancel()
            log.warn(
                "portal.migration_status_unavailable",
                "alerts-migration did not answer within {timeout}s; showing Migrate links",
                timeout=self._timeout,
            )
        except Exception as exc:
            log.warn(
                "portal.migration_status_unavailable",
                "alerts-migration status failed; showing Migrate links",
                exc=exc,
            )
        return frozenset()

    def _ask(self, uids: list[str]) -> frozenset[str]:
        request = urllib.request.Request(
            self._endpoint,
            data=json.dumps({"rule_uids": uids}).encode("utf-8"),
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
            method="POST",
        )
        with self._opener.open(request, timeout=self._timeout) as response:
            if response.status != 200:
                raise _StatusError(f"HTTP {response.status}")
            body = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise _StatusError("the response is too large")
        payload = json.loads(body)
        migrated = payload.get("migrated") if isinstance(payload, dict) else None
        if not isinstance(migrated, list) or not all(isinstance(uid, str) for uid in migrated):
            raise _StatusError("the response has no list of migrated rule UIDs")
        return frozenset(migrated) & frozenset(uids)

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
