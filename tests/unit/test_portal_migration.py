"""The hand-off to alerts-migration: Migrate links, "Migrate selected" and "✓ Migrated".

Off unless PORTAL_MIGRATION_URL is set. Only v1 Grafana alerts with an http(s) rule link get a
link; the selection form is standalone and the checkboxes join it with ``form=``; the CSP lets
forms submit only to alerts-migration's origin besides the portal; and the migrated status is
one bounded call per page that never breaks the page.
"""

from __future__ import annotations

import html
import json
import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from urllib.parse import parse_qs, quote, urlsplit

import pytest
from alerts_bi_shared.config.sql import load_sql_config
from alerts_bi_shared.db.connection import Database
from alerts_bi_shared.team_urls import encode_team_id
from fastapi.testclient import TestClient
from src import app, queries, tabs
from src.app import SECURITY_HEADERS, build_portal, security_headers
from src.assets import MIGRATE_SELECTION_SCRIPT, MIGRATE_SELECTION_SCRIPT_PATH
from src.config import PortalSettings, load_portal_settings
from src.migration import (
    MAX_STATUS_UIDS,
    MigrationStatus,
    MigrationView,
    migratable_rule_url,
    rule_uid,
)
from src.queries import AlertDetail, AlertRow, WorklistPage

from tests.unit.test_portal_tabs import REVIEWS, SELECTED, summary, visible, work_alert

MIGRATION = "https://migrate.example.test"
RULE = "https://grafana.example.test/alerting/grafana/abc123/view?orgId=1&tab=query"
HOSTILE_RULE = "https://grafana.example.test/alerting/grafana/q\"<x>/view?a=1&b='2'"
SETTINGS = PortalSettings(sql=load_sql_config(), database="alerts_bi_test")
TOKEN = "test-token-placeholder"


def v1(rule_url: str | None = RULE, **overrides: Any) -> AlertRow:
    values: dict[str, Any] = {
        "alert_schema": "v1",
        "provider": "grafana",
        "alert_rule_url": rule_url,
        "message": f"Disk full {rule_url}",
        "key_field": f"key {rule_url}",
        "readiness_rule_ids": (),
        **overrides,
    }
    return work_alert(**values)


ALERTS = [v1(), v1(HOSTILE_RULE), work_alert(), v1(provider="api", alert_rule_url=None)]


def fix(migration: MigrationView | None, alerts: list[AlertRow] = ALERTS) -> str:
    return tabs.fix_page(
        REVIEWS,
        SELECTED,
        summary(),
        WorklistPage(alerts, len(alerts), 1, 25),
        {},
        {"attention": len(alerts), "all": len(alerts)},
        show="attention",
        schema="all",
        state="all",
        rule="",
        migration=migration,
    )


def alert_page(alert: AlertRow, migration: MigrationView | None) -> str:
    return tabs.alert_page(REVIEWS, SELECTED, AlertDetail(alert, {}), migration=migration)


def checkboxes(page: str) -> list[str]:
    return re.findall(r'<input type="checkbox" name="rule_url"[^>]*>', page)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    """No .env file and no migration setting from the shell."""
    monkeypatch.chdir(tmp_path)
    for name in (
        "PORTAL_MIGRATION_URL",
        "PORTAL_MIGRATION_API_URL",
        "PORTAL_MIGRATION_STATUS_TOKEN",
        "PORTAL_MIGRATION_STATUS_TIMEOUT",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """The test backend is local: never send it through a proxy from the environment."""
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "*")


# ------------------------------------------------------------------ which alerts


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, RULE),
        ({"provider": "Grafana"}, RULE),
        ({"alert_rule_url": f"  {RULE} "}, RULE),
        ({"alert_schema": "v2"}, None),
        ({"provider": "api"}, None),
        ({"provider": None}, None),
        ({"alert_rule_url": None}, None),
        ({"alert_rule_url": ""}, None),
        ({"alert_rule_url": "javascript:alert(1)"}, None),
        ({"alert_rule_url": "ftp://grafana.example.test/alerting/grafana/a/view"}, None),
        ({"alert_rule_url": "/alerting/grafana/abc123/view"}, None),
    ],
)
def test_only_v1_grafana_alerts_with_an_http_rule_link_can_be_migrated(
    overrides: dict[str, Any], expected: str | None
) -> None:
    assert migratable_rule_url(v1(**overrides)) == expected


@pytest.mark.parametrize(
    ("url", "uid"),
    [
        (RULE, "abc123"),
        ("https://g.example/alerting/grafana/abc123/edit", "abc123"),
        ("https://g.example/alerting/abc123/view", "abc123"),
        ("https://g.example/grafana/alerting/grafana/abc-1_2/view/", "abc-1_2"),
        ("https://g.example/alerting/grafana/abc123/view?uid=other#x", "abc123"),
        ("https://g.example/alerting/list", None),
        ("https://g.example/alerting/grafana/view", None),
        ("https://g.example/alerting/new/edit", None),
        ("https://g.example/d/dash-uid/my-dashboard", None),
        ("https://g.example/alerting/grafana/abc123", None),
        ("https://g.example/", None),
    ],
)
def test_rule_uids_come_only_from_grafana_rule_pages(url: str, uid: str | None) -> None:
    # The compliance service's patterns, without its last-segment fallback.
    assert rule_uid(url) == uid


def test_the_migrate_link_carries_the_percent_encoded_rule_url() -> None:
    href = MigrationView(MIGRATION).href(RULE)
    assert href == f"{MIGRATION}/?rule_url={quote(RULE, safe='')}"
    assert "&tab" not in href and "%26tab%3Dquery" in href
    assert parse_qs(urlsplit(href).query) == {"rule_url": [RULE]}


# ------------------------------------------------------------------ hidden when unset


def test_nothing_about_migration_is_shown_when_the_setting_is_unset() -> None:
    for page in (
        fix(None),
        alert_page(v1(), None),
        tabs.migration_page(REVIEWS, SELECTED, summary()),
    ):
        assert "Migrate" not in page and "alerts-migration" not in page
        assert not checkboxes(page)
        assert MIGRATE_SELECTION_SCRIPT_PATH not in page
    assert fix(None).count("<form") == 1


def test_the_settings_leave_the_hand_off_off_by_default(env: pytest.MonkeyPatch) -> None:
    settings = load_portal_settings()
    assert settings.migration_url is None and settings.migration_origin is None
    assert settings.migration_status_url is None
    assert settings.migration_status_timeout == 1.0
    assert security_headers(settings) == SECURITY_HEADERS


# ------------------------------------------------------------------ the Fix list


def test_eligible_rows_get_a_migrate_link_that_opens_a_new_tab() -> None:
    page = fix(MigrationView(MIGRATION))
    links = re.findall(r'<a class="button migrate" href="([^"]+)" ([^>]*)>', page)
    assert [html.unescape(href) for href, _ in links] == [
        MigrationView(MIGRATION).href(RULE),
        MigrationView(MIGRATION).href(HOSTILE_RULE),
    ]
    assert all(attrs == 'target="_blank" rel="noopener noreferrer"' for _, attrs in links)
    assert "<x>" not in page
    assert ">Migrate <span" in page and " style=" not in page


def test_each_eligible_row_has_a_checkbox_for_the_standalone_form() -> None:
    page = fix(MigrationView(MIGRATION))
    boxes = checkboxes(page)
    assert len(boxes) == 2, "the v2 and API rows have none"
    assert all('form="migrate-selected"' in box for box in boxes)
    assert f'value="{html.escape(RULE)}"' in boxes[0]
    assert 'value="https://grafana.example.test/alerting/grafana/q&quot;&lt;x&gt;/view' in boxes[1]
    assert "?a=1&amp;b=&#x27;2&#x27;" in boxes[1]
    forms = re.findall(r"<form[^>]*>.*?</form>", page, flags=re.DOTALL)
    assert len(forms) == 2, "the application filter and the migrate form"
    migrate = next(form for form in forms if 'id="migrate-selected"' in form)
    assert migrate.startswith(
        f'<form class="migrate-bar" id="migrate-selected" method="get" action="{MIGRATION}/" '
        'target="_blank" rel="noopener noreferrer">'
    )
    assert '<button class="button migrate" type="submit">Migrate selected' in migrate
    assert not any(checkboxes(form) for form in forms), "no checkbox sits inside a form"
    alerts = page.index('id="alerts"')
    assert alerts < page.index('id="migrate-selected"') < page.index("<table", alerts)


def test_the_selection_script_is_local_and_only_on_pages_with_checkboxes() -> None:
    page = fix(MigrationView(MIGRATION))
    assert page.count("<script") == 2
    assert f'<script src="{MIGRATE_SELECTION_SCRIPT_PATH}" defer></script>' in page
    assert "migrate-selected" in MIGRATE_SELECTION_SCRIPT
    plain = fix(MigrationView(MIGRATION), [work_alert()])
    assert MIGRATE_SELECTION_SCRIPT_PATH not in plain and "Migrate" not in plain
    with TestClient(build_portal(SETTINGS), client=("10.1.2.3", 50000)) as client:
        response = client.get(MIGRATE_SELECTION_SCRIPT_PATH)
    assert response.status_code == 200 and response.text == MIGRATE_SELECTION_SCRIPT
    assert response.headers["content-type"].startswith("text/javascript")


def test_a_migrated_row_shows_migrated_and_has_no_checkbox() -> None:
    page = fix(MigrationView(MIGRATION, frozenset({"abc123"})))
    assert (
        page.count(
            '<span class="button migrated" aria-disabled="true">'
            '<span aria-hidden="true">✓</span> Migrated</span>'
        )
        == 1
    )
    assert "✓ Migrated" in " ".join(visible(page).split())
    assert html.escape(MigrationView(MIGRATION).href(RULE)) not in page, "no link once migrated"
    boxes = checkboxes(page)
    assert len(boxes) == 1 and "q&quot;" in boxes[0], "only the other rule can be ticked"


def test_a_page_with_every_rule_migrated_has_no_selection() -> None:
    page = fix(MigrationView(MIGRATION, frozenset({"abc123"})), [v1(), work_alert()])
    assert "✓</span> Migrated" in page
    assert not checkboxes(page) and 'id="migrate-selected"' not in page
    assert MIGRATE_SELECTION_SCRIPT_PATH not in page
    assert '<th scope="col" class="pick">' not in page


# ------------------------------------------------------------------ the other pages


def test_the_alert_page_puts_the_button_next_to_the_title() -> None:
    page = alert_page(v1(), MigrationView(MIGRATION))
    head = page[page.index('<div class="alert-head">') :]
    head = head[: head.index("</a></div>")]
    assert '<h2 class="alert-title">' in head
    assert f'href="{html.escape(MigrationView(MIGRATION).href(RULE))}"' in head
    done = alert_page(v1(), MigrationView(MIGRATION, frozenset({"abc123"})))
    assert '<div class="alert-head"><h2 class="alert-title">' in done
    assert "✓</span> Migrated</span></div>" in done and 'class="button migrate"' not in done
    for ineligible in (work_alert(), v1(provider="api"), v1("javascript:alert(1)")):
        assert "alert-head" not in alert_page(ineligible, MigrationView(MIGRATION))


def test_the_migration_tab_points_to_alerts_migration() -> None:
    page = tabs.migration_page(REVIEWS, SELECTED, summary(), migration=MigrationView(MIGRATION))
    assert (
        f'<a href="{MIGRATION}/" target="_blank" rel="noopener noreferrer">alerts-migration' in page
    )
    assert "/weeks/2026-09-28/fix?schema=v1#alerts" in page
    assert "Move v1 Grafana rules with alerts-migration" in " ".join(visible(page).split())


# ------------------------------------------------------------------ settings and CSP


def test_the_migration_settings_are_read_and_the_token_never_shown(
    env: pytest.MonkeyPatch,
) -> None:
    monkeypatch = env
    monkeypatch.setenv("PORTAL_MIGRATION_URL", " https://Migrate.Example.test:8443/app/ ")
    monkeypatch.setenv("PORTAL_MIGRATION_STATUS_TIMEOUT", "0.5")
    settings = load_portal_settings()
    assert settings.migration_url == "https://Migrate.Example.test:8443/app"
    assert settings.migration_origin == "https://migrate.example.test:8443"
    assert settings.migration_api_url == settings.migration_url
    assert settings.migration_status_url is None, "no token, no status call"
    assert settings.migration_status_timeout == 0.5
    monkeypatch.setenv("PORTAL_MIGRATION_STATUS_TOKEN", TOKEN)
    monkeypatch.setenv("PORTAL_MIGRATION_API_URL", "http://migration-backend:8080")
    settings = load_portal_settings()
    assert settings.migration_status_url == "http://migration-backend:8080"
    assert TOKEN not in repr(settings)
    monkeypatch.delenv("PORTAL_MIGRATION_URL")
    assert load_portal_settings().migration_status_url is None, "no links, no status call"


@pytest.mark.parametrize(
    "value",
    [
        "migrate.example.test",
        "ftp://migrate.example.test",
        "https://",
        "https://migrate.example.test/?a=1",
        "https://migrate.example.test/#x",
        "https://user:pw@migrate.example.test",
        "https://migrate example.test",
        "https://migrate.example.test;script-src",
        "javascript:alert(1)",
    ],
)
def test_a_migration_url_that_is_not_a_plain_http_base_is_refused(
    env: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch = env
    for name in ("PORTAL_MIGRATION_URL", "PORTAL_MIGRATION_API_URL"):
        monkeypatch.setenv(name, value)
        with pytest.raises(ValueError, match=f"{name} must be an http"):
            load_portal_settings()
        monkeypatch.delenv(name)


@pytest.mark.parametrize("value", ["0", "-1", "10.5", "soon", "nan"])
def test_a_status_timeout_out_of_range_is_refused(env: pytest.MonkeyPatch, value: str) -> None:
    env.setenv("PORTAL_MIGRATION_STATUS_TIMEOUT", value)
    with pytest.raises(ValueError, match="PORTAL_MIGRATION_STATUS_TIMEOUT must be"):
        load_portal_settings()


def test_forms_may_submit_only_here_and_to_alerts_migration() -> None:
    policy = SECURITY_HEADERS["Content-Security-Policy"]
    assert "form-action 'self';" in policy
    settings = PortalSettings(
        sql=load_sql_config(),
        database="alerts_bi_test",
        migration_url="https://Migrate.Example.test:8443/app",
    )
    headers = security_headers(settings)
    expected = policy.replace(
        "form-action 'self';", "form-action 'self' https://migrate.example.test:8443;"
    )
    assert headers["Content-Security-Policy"] == expected
    assert {k: v for k, v in headers.items() if k != "Content-Security-Policy"} == {
        k: v for k, v in SECURITY_HEADERS.items() if k != "Content-Security-Policy"
    }
    with TestClient(build_portal(settings), client=("8.8.8.8", 50000)) as client:
        assert client.get("/").headers["content-security-policy"] == expected
    with TestClient(build_portal(SETTINGS), client=("8.8.8.8", 50000)) as client:
        assert client.get("/").headers["content-security-policy"] == policy


# ------------------------------------------------------------------ the status call


class _Backend(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.requests: list[tuple[str, str, dict[str, str], bytes]] = []
        self.status = 200
        self.body: bytes = b'{"migrated": []}'
        self.headers: dict[str, str] = {}
        self.hold = False
        self.release = threading.Event()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class _Handler(BaseHTTPRequestHandler):
    server: _Backend

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        self.server.requests.append(
            (self.command, self.path, dict(self.headers), self.rfile.read(length))
        )
        if self.server.hold:
            self.server.release.wait(5)
        self.send_response(self.server.status)
        for name, value in self.server.headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(self.server.body)))
        self.end_headers()
        self.wfile.write(self.server.body)

    do_GET = do_POST

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture
def backend(no_proxy: None) -> Iterator[_Backend]:
    server = _Backend()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.release.set()
        server.shutdown()
        server.server_close()


@contextmanager
def status_client(url: str, timeout: float = 2.0) -> Iterator[MigrationStatus]:
    status = MigrationStatus(url, TOKEN, timeout)
    try:
        yield status
    finally:
        status.close()


def test_the_status_call_sends_the_page_uids_once_with_the_token(backend: _Backend) -> None:
    backend.body = b'{"migrated": ["abc123", "not-asked"]}'
    other = "https://grafana.example.test/alerting/def456/edit"
    with status_client(backend.url) as status:
        migrated = status.migrated([RULE, other, RULE, "https://g.example/d/x/y"])
    assert migrated == frozenset({"abc123"}), "only UIDs the page asked about"
    assert len(backend.requests) == 1
    method, path, headers, body = backend.requests[0]
    assert (method, path) == ("POST", "/api/rules/migration-status")
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert headers["Content-Type"] == "application/json"
    assert json.loads(body) == {"rule_uids": ["abc123", "def456"]}


def test_no_rule_uid_means_no_call(backend: _Backend) -> None:
    with status_client(backend.url) as status:
        assert status.migrated([]) == frozenset()
        assert status.migrated(["https://g.example/d/x/y"]) == frozenset()
    assert backend.requests == []


def test_at_most_the_endpoint_limit_of_uids_is_sent(backend: _Backend) -> None:
    urls = [f"https://g.example/alerting/grafana/r{n}/view" for n in range(MAX_STATUS_UIDS + 5)]
    with status_client(backend.url) as status:
        status.migrated(urls)
    assert len(json.loads(backend.requests[0][3])["rule_uids"]) == MAX_STATUS_UIDS


@pytest.mark.parametrize(
    ("status", "body", "headers"),
    [
        (500, b'{"migrated": ["abc123"]}', {}),
        (401, b'{"detail": "no"}', {}),
        (204, b"", {}),
        (302, b"", {"Location": "/elsewhere"}),
        (200, b"not json", {}),
        (200, b'{"migrated": "abc123"}', {}),
        (200, b'{"migrated": [1]}', {}),
        (200, b'["abc123"]', {}),
    ],
)
def test_a_failed_status_call_shows_migrate_links_and_logs_no_token(
    backend: _Backend,
    capsys: pytest.CaptureFixture[str],
    status: int,
    body: bytes,
    headers: dict[str, str],
) -> None:
    backend.status, backend.body, backend.headers = status, body, headers
    with status_client(backend.url) as client:
        assert client.migrated([RULE]) == frozenset()
    assert [path for _, path, _, _ in backend.requests] == ["/api/rules/migration-status"]
    err = capsys.readouterr().err
    assert "portal.migration_status_unavailable" in err
    assert TOKEN not in err


def test_a_slow_status_call_is_abandoned_at_the_timeout(
    backend: _Backend, capsys: pytest.CaptureFixture[str]
) -> None:
    backend.hold = True
    backend.body = b'{"migrated": ["abc123"]}'
    with status_client(backend.url, timeout=0.2) as status:
        started = time.monotonic()
        assert status.migrated([RULE]) == frozenset()
        assert time.monotonic() - started < 1.0
    assert "portal.migration_status_unavailable" in capsys.readouterr().err


def test_an_unreachable_backend_shows_migrate_links(
    no_proxy: None, capsys: pytest.CaptureFixture[str]
) -> None:
    server = _Backend()
    url = server.url
    server.server_close()
    with status_client(url) as status:
        assert status.migrated([RULE]) == frozenset()
    assert "portal.migration_status_unavailable" in capsys.readouterr().err


# ------------------------------------------------------------------ through the routes


WEEK = date(2026, 9, 28)


@pytest.fixture
def routed(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Pages from canned queries; returns the stand-in MigrationStatus class."""

    @contextmanager
    def connect(*args: object, **kwargs: object) -> Iterator[Database]:
        yield Mock(spec=Database)

    monkeypatch.setattr("alerts_bi_shared.db.connection.WebDatabasePool.connect", connect)
    monkeypatch.setattr(queries, "team_reviews", Mock(return_value=REVIEWS))
    monkeypatch.setattr(
        queries, "worklist", Mock(return_value=WorklistPage(ALERTS, len(ALERTS), 1, 25))
    )
    monkeypatch.setattr(queries, "worklist_counts", Mock(return_value={"attention": 4, "all": 4}))
    monkeypatch.setattr(queries, "latest_decisions", Mock(return_value={}))
    monkeypatch.setattr(queries, "alert_detail", Mock(return_value=AlertDetail(v1(), {})))
    monkeypatch.setattr(app, "load_portal_summary", Mock())
    monkeypatch.setattr(app, "summarize", Mock(return_value=summary()))
    status = Mock(spec=MigrationStatus)
    status.migrated.return_value = frozenset({"abc123"})
    constructor = Mock(return_value=status)
    monkeypatch.setattr("src.app.MigrationStatus", constructor)
    return constructor


def _get(settings: PortalSettings, path: str, **params: str) -> Any:
    team = encode_team_id(SELECTED.team_id)
    with TestClient(build_portal(settings), client=("10.1.2.3", 50000)) as client:
        return client.get(f"/teams/{team}/weeks/{WEEK}/{path}", params=params)


def test_each_page_asks_once_for_its_own_rules(routed: Mock) -> None:
    settings = PortalSettings(
        sql=load_sql_config(),
        database="alerts_bi_test",
        migration_url=MIGRATION,
        migration_status_token=TOKEN,
    )
    status = routed.return_value
    page = _get(settings, "fix")
    routed.assert_called_once_with(MIGRATION, TOKEN, 1.0)
    assert page.status_code == 200 and page.headers["cache-control"] == "no-store"
    assert "✓</span> Migrated" in page.text and len(checkboxes(page.text)) == 1
    assert f"form-action 'self' {MIGRATION};" in page.headers["content-security-policy"]
    status.migrated.assert_called_once_with([RULE, HOSTILE_RULE])
    status.migrated.reset_mock()
    detail = _get(settings, "alert", schema="v1", application="app", key="key")
    assert detail.status_code == 200 and "✓</span> Migrated" in detail.text
    status.migrated.assert_called_once_with([RULE])
    status.migrated.reset_mock()
    assert "alerts-migration" in _get(settings, "migration").text
    status.migrated.assert_not_called()


def test_without_a_token_the_links_show_and_nothing_is_asked(routed: Mock) -> None:
    settings = PortalSettings(
        sql=load_sql_config(), database="alerts_bi_test", migration_url=MIGRATION
    )
    page = _get(settings, "fix")
    assert page.status_code == 200 and len(checkboxes(page.text)) == 2
    routed.assert_not_called()


def test_without_the_setting_the_routes_render_no_migration(routed: Mock) -> None:
    for path, params in (
        ("fix", {}),
        ("alert", {"schema": "v1", "application": "app", "key": "key"}),
        ("migration", {}),
    ):
        page = _get(SETTINGS, path, **params)
        assert page.status_code == 200
        assert "Migrate" not in page.text and "alerts-migration" not in page.text
    routed.assert_not_called()
