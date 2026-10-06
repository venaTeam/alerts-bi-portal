"""The standalone reader loads only shared SQL and reader settings."""

from pathlib import Path

import pytest
from alerts_bi_shared.config.sql import load_sql_config
from src.config import load_portal_settings


def test_portal_uses_the_exact_shared_sql_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQL_DATABASE", "shared_db")
    monkeypatch.setenv("SQL_USER", "shared_login")
    monkeypatch.setenv("SQL_PASSWORD", "test-placeholder")
    monkeypatch.setenv("PORTAL_DATABASE", "ignored")
    monkeypatch.setenv("PORTAL_SQL_USER", "ignored")
    monkeypatch.setenv("PORTAL_SQL_PASSWORD", "ignored")
    sql = load_sql_config()
    settings = load_portal_settings(sql)
    assert settings.sql is sql
    assert settings.database == sql.database == "shared_db"
    assert settings.sql.user == "shared_login"


def test_portal_loads_dotenv_without_pipeline_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SQL_DATABASE", raising=False)
    monkeypatch.setenv("ES_PAGE_SIZE", "not-an-integer")
    monkeypatch.setenv("LLM_TIMEOUT_MS", "not-an-integer")
    (tmp_path / ".env").write_text("SQL_DATABASE=reader_database\n", encoding="utf-8")
    settings = load_portal_settings()
    assert settings.database == "reader_database"


def test_process_configuration_wins_over_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SQL_DATABASE", "process_database")
    (tmp_path / ".env").write_text("SQL_DATABASE=ignored_database\n", encoding="utf-8")
    assert load_portal_settings().database == "process_database"
