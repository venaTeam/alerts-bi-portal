"""The hand-off to alerts-migration: which alerts it can migrate, the links that open them there,
and which of their rules it has already migrated.

Readers still only send GETs. The one outbound call asks alerts-migration which rule UIDs are
migrated, once per page (in parallel chunks when the page has more UIDs than one call takes)
and bounded by a timeout; for a chunk that fails, the page shows plain "Migrate" links.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from threading import Thread
from typing import Any, Final
from urllib.parse import quote, urlencode, urlparse

from alerts_bi_shared.logging_setup import log
from alerts_bi_shared.ui.html import safe_link

from .queries import AlertRow

__all__ = [
    "MAX_LINK_RULES",
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
#: alerts-migration opens at most this many rule_url values per link (its MAX_LINK_RULES).
MAX_LINK_RULES: Final = 50
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


class _Call:
    """One status request on its own daemon thread, so no page waits behind another page's
    call and a stuck call never holds up shutdown."""

    def __init__(self, ask: Callable[[list[str]], frozenset[str]], uids: list[str]) -> None:
        self.uids = uids
        self.migrated: frozenset[str] | None = None
        self.failure: str | None = None
        self._thread = Thread(target=self._run, args=(ask,), name="migration-status", daemon=True)
        self._thread.start()

    def _run(self, ask: Callable[[list[str]], frozenset[str]]) -> None:
        try:
            self.migrated = ask(self.uids)
        except Exception as exc:
            self.failure = _reason(exc)

    def wait(self, deadline: float) -> None:
        self._thread.join(max(0.0, deadline - time.monotonic()))


def _reason(exc: BaseException) -> str:
    """Why a call failed, without the exception's text: it can quote the request headers."""
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, _StatusError):
        return str(exc)
    return type(exc).__name__


class MigrationStatus:
    """Asks alerts-migration which rules it has migrated, at most ``timeout`` seconds per page."""

    def __init__(self, api_url: str, token: str, timeout: float) -> None:
        self._endpoint = api_url + STATUS_PATH
        self._token = token
        self._timeout = timeout
        self._opener = urllib.request.build_opener(_NoRedirect())

    def migrated(self, rule_urls: Iterable[str]) -> frozenset[str]:
        """The UIDs among these rules that are migrated. Never raises: a chunk that fails or
        misses the deadline counts as not migrated."""
        try:
            uids = list(dict.fromkeys(uid for url in rule_urls if (uid := rule_uid(url))))
            deadline = time.monotonic() + self._timeout
            calls = [
                _Call(self._ask, uids[start : start + MAX_STATUS_UIDS])
                for start in range(0, len(uids), MAX_STATUS_UIDS)
            ]
            for call in calls:
                call.wait(deadline)
            # Read each answer once: a late call may still finish while this runs.
            answers = [call.migrated for call in calls]
            migrated = frozenset[str]().union(*(a for a in answers if a is not None))
            failures = [
                call.failure or f"no answer within {self._timeout}s"
                for call, answer in zip(calls, answers, strict=True)
                if answer is None
            ]
        except Exception as exc:
            migrated, failures = frozenset(), [_reason(exc)]
        if failures:
            log.warn(
                "portal.migration_status_unavailable",
                "alerts-migration status failed ({reasons}); showing Migrate links for those rules",
                reasons=sorted(set(failures)),
            )
        return migrated

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
