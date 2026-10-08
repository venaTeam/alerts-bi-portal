"""Explicit, bookmarkable application scope shared by every team tab."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request


@dataclass(frozen=True, slots=True)
class ApplicationFilter:
    # None means all; an empty tuple is an explicitly empty selection.
    selected: tuple[str, ...] | None = None
    options: tuple[str, ...] = ()

    @property
    def active(self) -> bool:
        return self.selected is not None

    @property
    def params(self) -> dict[str, Any]:
        return {} if self.selected is None else {"scope": "selected", "apps": self.selected}


ALL_APPLICATIONS = ApplicationFilter()


def from_request(request: Request) -> ApplicationFilter:
    values = request.query_params.getlist("apps")
    mode = request.query_params.get("scope")
    if mode not in (None, "selected") or len(values) > 1000 or any(len(v) > 256 for v in values):
        raise HTTPException(422, "Invalid application filter.")
    selected = tuple(sorted(set(values))) if values or mode == "selected" else None
    return ApplicationFilter(selected)


def predicate(scope: ApplicationFilter, column: str = "application") -> tuple[str, dict[str, Any]]:
    """Only internal column names are accepted; every application value is bound."""
    if column not in ("application", "a.application"):
        raise ValueError("Unexpected application column")
    if scope.selected is None:
        return "1 = 1", {}
    if not scope.selected:
        return "1 = 0", {}
    params = {f"app{i}": value for i, value in enumerate(scope.selected)}
    return f"{column} IN ({', '.join(':' + name for name in params)})", params
