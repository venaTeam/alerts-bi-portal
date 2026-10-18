"""Exercise HTTP routing with query boundaries mocked; SQL isolation is tested in design."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import cast
from unittest.mock import Mock

import pytest
from alerts_bi_shared.config.sql import load_sql_config
from alerts_bi_shared.db.connection import Database
from alerts_bi_shared.team_urls import decode_team_id, encode_team_id
from fastapi.testclient import TestClient
from src import app, pages, queries, tabs
from src.config import PortalSettings

WEEK = date(2026, 10, 12)
VECTORS = [
    ("team-a", "team-a"),
    ("Team-A", "Team-A"),
    ("team/a", "~7465616d2f61"),
    ("a%2Fb", "~6125324662"),
    ("team a", "~7465616d2061"),
    ("é", "~c3a9"),
    ("..", "~2e2e"),
    ("~61", "~7e3631"),
]
SUFFIXES = ["", "/weeks", "/weeks/2026-10-12"] + [
    f"/weeks/2026-10-12/{tab}"
    for tab in ("fix", "volume", "dashboards", "migration", "history", "slides", "alert")
]


@pytest.mark.parametrize(("team", "segment"), VECTORS)
def test_installed_codec_and_link_builders_preserve_identity(team: str, segment: str) -> None:
    assert encode_team_id(team) == segment
    assert decode_team_id(segment) == team
    assert pages.team_url(team) == f"/teams/{segment}"
    assert pages.week_url(team, WEEK) == f"/teams/{segment}/weeks/{WEEK}"
    assert pages.tab_url(team, WEEK, "fix") == f"/teams/{segment}/weeks/{WEEK}/fix"
    assert pages.alert_url(team, WEEK, "v1", "app", "key").startswith(
        f"/teams/{segment}/weeks/{WEEK}/alert?"
    )


@pytest.fixture
def routed_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Mock]]:
    @contextmanager
    def connect(*args: object, **kwargs: object) -> Iterator[Database]:
        yield Mock(spec=Database)

    def reviews(db: Database, team: str, applications: object) -> list[Mock]:
        review = Mock(team_id=team, run_id=f"run:{team}", week=WEEK)
        review.applications.selected = None
        review.applications.params = {}
        return [review]

    def render(reviews: object, selected: Mock, *args: object, **kwargs: object) -> str:
        return str(selected.team_id)

    monkeypatch.setattr("alerts_bi_shared.db.connection.WebDatabasePool.connect", connect)
    lookup = Mock(side_effect=reviews)
    monkeypatch.setattr(queries, "team_reviews", lookup)
    for name in ("worklist", "worklist_counts", "latest_decisions", "alert_detail"):
        monkeypatch.setattr(queries, name, Mock())
    monkeypatch.setattr(app, "load_portal_summary", Mock())
    monkeypatch.setattr(app, "summarize", Mock())
    for tab in (
        "overview",
        "fix",
        "volume",
        "dashboards",
        "migration",
        "history",
        "slides",
        "alert",
    ):
        monkeypatch.setattr(tabs, f"{tab}_page", render)
    settings = PortalSettings(sql=load_sql_config(), database="alerts_bi_test")
    with TestClient(app.build_portal(settings), client=("127.0.0.1", 50000)) as client:
        yield client, lookup


@pytest.mark.parametrize(("team", "segment"), VECTORS)
@pytest.mark.parametrize("suffix", SUFFIXES)
def test_every_team_route_decodes_before_querying(
    routed_client: tuple[TestClient, Mock], team: str, segment: str, suffix: str
) -> None:
    client, lookup = routed_client
    response = client.get(
        f"/teams/{segment}{suffix}",
        params=(
            {"schema": "v1", "application": "app", "key": "key"}
            if suffix.endswith("/alert")
            else {"week": str(WEEK)}
        ),
    )
    assert response.status_code == 200
    assert response.text == team
    assert lookup.call_args.args[1] == team
    if suffix.endswith("/alert"):
        assert cast(Mock, queries.alert_detail).call_args.args[1] == f"run:{team}"


@pytest.mark.parametrize("segment", ["~", "~ff", "~0", "~zz", "~61"])
@pytest.mark.parametrize("suffix", SUFFIXES)
def test_malformed_tokens_are_404_before_any_team_query(
    routed_client: tuple[TestClient, Mock], segment: str, suffix: str
) -> None:
    client, lookup = routed_client
    response = client.get(
        f"/teams/{segment}{suffix}",
        params=(
            {"schema": "v1", "application": "app", "key": "key"}
            if suffix.endswith("/alert")
            else {"week": str(WEEK)}
        ),
    )
    assert response.status_code == 404
    lookup.assert_not_called()


def test_legacy_filter_redirect_preserves_the_encoded_team(
    routed_client: tuple[TestClient, Mock],
) -> None:
    client, lookup = routed_client
    for team, segment in VECTORS:
        response = client.get(f"/teams/{segment}?show=all", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == f"/teams/{segment}/weeks/{WEEK}/fix?show=all#alerts"
        assert lookup.call_args.args[1] == team
