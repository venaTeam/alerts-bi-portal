"""Compile the pinned reader schema without reading rows or inspecting base tables."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from importlib.resources import files

from alerts_bi_shared.db.connection import Database

PORTAL_VIEWS = frozenset(
    {
        "portal_alerts",
        "portal_daily_metrics",
        "portal_decisions",
        "portal_reviews",
        "portal_rule_totals",
        "portal_schema_totals",
    }
)


def schema_probes() -> tuple[str, ...]:
    """Build bounded view queries from the packaged, pinned design contract.

    This resource is copied byte-for-byte from ``contracts/sql-views.json``. No caller or
    environment value can supply SQL identifiers; validation also prevents a mistaken
    contract update from expanding readiness outside the six approved reader views.
    """
    rows = json.loads(files("alerts_bi_portal").joinpath("sql-views.json").read_text("utf-8"))
    columns: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for row in rows:
        view = str(row["view_name"])
        column = str(row["column_name"])
        if view not in PORTAL_VIEWS or re.fullmatch(r"[a-z][a-z0-9_]*", column) is None:
            raise ValueError("Invalid packaged portal schema contract")
        columns[view].append((int(row["position"]), column))
    if set(columns) != PORTAL_VIEWS:
        raise ValueError("Incomplete packaged portal schema contract")
    return tuple(
        "SELECT TOP 0 "
        + ", ".join(f"[{column}]" for _, column in sorted(columns[view]))
        + f" FROM [{view}]"
        for view in sorted(columns)
    )


def check_schema(db: Database) -> None:
    """Raise when required views/columns are absent or unreadable; never fetch alert data."""
    for statement in schema_probes():
        db.query(statement)
