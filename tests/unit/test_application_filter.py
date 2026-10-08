"""Application scope must survive URLs without becoming SQL or executable HTML."""

from __future__ import annotations

import dataclasses
import html
import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from alerts_bi_shared.insights.summary import summarize
from alerts_bi_shared.ui.slides import render_slides
from fastapi import HTTPException, Request
from src import tabs
from src.application_filter import ApplicationFilter, from_request, predicate
from src.pages import tab_url
from src.summary_queries import _application_totals, _schema_totals

from tests.unit.test_portal_tabs import END, review, summary


def request(query: str) -> Request:
    return Request({"type": "http", "query_string": query.encode("utf-8")})


def test_all_empty_and_multiple_are_distinct() -> None:
    assert from_request(request("")).selected is None
    assert from_request(request("scope=selected")).selected == ()
    assert from_request(request("apps=b&apps=a&apps=b")).selected == ("a", "b")
    assert predicate(ApplicationFilter(())) == ("1 = 0", {})


@pytest.mark.parametrize("query", ["scope=unknown", "apps=" + "x" * 257, "apps=a&" * 1001])
def test_rejects_invalid_or_excessive_scope(query: str) -> None:
    with pytest.raises(HTTPException) as error:
        from_request(request(query))
    assert error.value.status_code == 422


def test_hostile_names_are_bound_and_round_trip() -> None:
    names = ("a&b+service", "' OR 1=1--", '<script>"&</script>', "עברית")
    scope = ApplicationFilter(names)
    clause, params = predicate(scope)
    assert all(value not in clause for value in names)
    assert tuple(params.values()) == names
    url = tab_url("team", END.date(), "fix", **scope.params)
    assert parse_qs(urlsplit(url).query)["apps"] == list(names)
    assert from_request(request(urlencode(scope.params, doseq=True))).selected == tuple(
        sorted(names)
    )


def test_every_tab_and_week_link_preserves_selection_and_escapes_options() -> None:
    scope = ApplicationFilter(("cart", 'other <script>"'), ("cart", 'other <script>"', "queue"))
    selected = review(applications=scope)
    page = tabs.overview_page([selected], selected, summary())
    navigation = re.search(r'<nav class="tabs".*?</nav>', page)
    assert navigation is not None
    for url in re.findall(r'href="([^"]+)"', navigation.group()):
        assert parse_qs(urlsplit(html.unescape(url)).query)["apps"] == list(scope.selected or ())
    assert 'value="other &lt;script&gt;&quot;" checked' in page
    assert 'value="queue" checked' not in page
    assert 'method="get"' in page
    assert 'name="scope" value="selected"' in page
    assert "<script>" not in page and 'style="' not in page
    href = tabs._alert_href(selected, "v1", "cart", "key")
    assert parse_qs(urlsplit(href).query)["apps"] == list(scope.selected or ())
    removed = dataclasses.replace(selected, applications=ApplicationFilter(()))
    assert "No applications selected" in tabs.overview_page([removed], removed, summary())


def test_subset_totals_count_matches_without_inventing_union_or_unseen_events() -> None:
    alerts = [
        {
            "alert_schema": "v1",
            "row_count": 20,
            "unseen": True,
            "quality_state": "rule_flagged",
            "core_rule_ids": "R1,R5",
            "readiness_rule_ids": "",
            "findings_evidence": json.dumps(
                [{"rule_id": "R1", "matched_rows": 3}, {"rule_id": "R5", "matched_rows": 7}]
            ),
        }
    ]
    totals, rules = _application_totals(alerts, [{"alert_schema": "v1", "unseen": 99}])
    schemas = _schema_totals(totals)
    assert (schemas["v1"].events, schemas["v1"].distinct_alerts) == (20, 1)
    assert schemas["v1"].suppressed == 7
    assert schemas["v1"].rule_flagged_events is None
    assert schemas["v1"].unseen is None and schemas["v1"].unseen_alerts == 1
    assert schemas["v2"].events == 0
    assert [(r["rule_id"], r["events"]) for r in rules] == [("R1", 3), ("R5", 7)]


def test_filtered_slides_label_missing_metrics_and_team_context() -> None:
    inputs = summary().inputs
    inputs = dataclasses.replace(
        inputs,
        applications=("etl-loader",),
        daily=(),
        schemas={
            s: dataclasses.replace(t, rule_flagged_events=None, unseen=None)
            for s, t in inputs.schemas.items()
        },
    )
    page = render_slides(summarize(inputs))
    assert "Application breakdown unavailable" in page
    assert "event share unavailable" in page
    assert "Applications: etl-loader" in page
    assert "Team: Phase" in page
    assert "No v1 alerts this week" not in page
