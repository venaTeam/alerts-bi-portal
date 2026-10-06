"""Unit checks for readiness queries and HTTP failures; these do not simulate persistence."""

from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from alerts_bi_shared.config.sql import load_sql_config
from alerts_bi_shared.db.connection import Database
from fastapi.testclient import TestClient

from alerts_bi_portal import app
from alerts_bi_portal.config import PortalSettings
from alerts_bi_portal.readiness import PORTAL_VIEWS, schema_probes


def client_for(monkeypatch: pytest.MonkeyPatch, db: Mock) -> TestClient:
    @contextmanager
    def connect(*args: object, **kwargs: object) -> Iterator[Database]:
        yield cast(Database, db)

    monkeypatch.setattr(app, "connect", connect)
    settings = PortalSettings(sql=load_sql_config(), database="alerts_bi_test")
    return TestClient(app.build_portal(settings), client=("127.0.0.1", 50000))


def test_packaged_contract_matches_the_pinned_design_snapshot() -> None:
    snapshot = Path(__file__).resolve().parents[2] / "docs/upstream/contracts/sql-views.json"
    resource = files("alerts_bi_portal").joinpath("sql-views.json")
    assert resource.read_bytes() == snapshot.read_bytes()


def test_healthy_schema_returns_200_without_reading_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Mock(spec=Database)
    db.query.return_value = []
    with client_for(monkeypatch, db) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    statements = [call.args[0] for call in db.query.call_args_list]
    assert len(statements) == 6
    assert {statement.rsplit(" FROM ", 1)[1] for statement in statements} == {
        f"[{view}]" for view in PORTAL_VIEWS
    }
    assert all(statement.startswith("SELECT TOP 0 ") for statement in statements)
    assert "[open_since]" in " ".join(statements)
    assert "[basis_changed]" in " ".join(statements)
    assert "[flagged_by_rule_distinct]" in " ".join(statements)


@pytest.mark.parametrize("missing", [*sorted(PORTAL_VIEWS), "open_since"])
def test_missing_view_or_column_refuses_readiness_without_error_details(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    db = Mock(spec=Database)

    def query(statement: str) -> list[dict[str, object]]:
        if f"[{missing}]" in statement:
            raise RuntimeError(f"SQL driver: missing {missing}; private connection details")
        return []

    db.query.side_effect = query
    with client_for(monkeypatch, db) as client:
        response = client.get("/healthz")
    assert response.status_code == 503
    assert response.json()["ok"] is False
    assert "private connection" not in response.text
    assert missing not in response.text
    assert db.query.call_count <= len(schema_probes())
