from dataclasses import asdict, replace

import pytest
from alerts_bi_shared.insights.stored import build_facts
from alerts_bi_shared.ui.explain import r6_next_step
from src import tabs
from src.pages import h
from src.queries import WorklistPage

from tests.unit.test_portal_summary_view import alert, build_summary, render
from tests.unit.test_portal_tabs import REVIEWS, SELECTED


@pytest.mark.parametrize("surface", ["portal", "admin"])
@pytest.mark.parametrize("stored", [False, True])
def test_r6_guidance_follows_most_alerts_even_when_another_pattern_has_more_events(
    surface: str, stored: bool
) -> None:
    stuck = alert(key_field="stuck", row_count=2000)
    spam = tuple(
        alert(key_field=f"spam-{i}", provider="api", fire_pattern="spamming", row_count=100)
        for i in range(10)
    )
    full = (stuck, *spam)
    summary = build_summary(surface=surface, alerts=full)
    if stored:
        rows = []
        for member in full:
            row = asdict(member)
            row["alert_schema"] = row.pop("schema")
            row["core_rule_ids"] = ",".join(member.core_rule_ids)
            row["readiness_rule_ids"] = ",".join(member.readiness_rule_ids)
            rows.append(row)
        summary = replace(
            summary,
            inputs=replace(summary.inputs, facts=build_facts(rows), alerts=(stuck,)),
        )

    page = render(summary)
    findings = page[page.index("Key findings") : page.index("Noisy alerts by application")]
    table = page[page.index("Flagged by rule") : page.index("Hidden by your own panels")]
    assert h(r6_next_step("spamming")) in findings
    assert h(r6_next_step("spamming")) in table
    assert tabs._r6_pattern(summary) == "spamming"
    banner = tabs.fix_page(
        REVIEWS,
        SELECTED,
        summary,
        WorklistPage([], 0, 1, 25),
        {},
        {"attention": 11, "all": 11},
        show="attention",
        schema="all",
        state="all",
        rule="R6",
    )
    assert "Send it once when it fires and once when it clears." in banner
