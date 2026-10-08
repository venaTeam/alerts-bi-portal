# Alerts BI review portal

The independent GET-only reader app renders published weeks from the six `portal_*`
SQL Server views. It keeps the existing network allowlist, script-free pages, publication
isolation and weekly totals. It cannot execute runs, publish reviews or record decisions.

Each team week has seven tabs: Overview, Fix list, Volume, Dashboards, Migration,
History and Slides. Problems have plain-language names. The week menu keeps the selected
tab, and older work-list links redirect to the Fix list with their filters intact.

Python 3.12+ and `uv` are required. From this repository:

```powershell
uv sync --frozen
Copy-Item .env.example .env
# Set SQL_* to the same database and login used by alerts-bi-runs.
uv run --frozen alerts-bi-portal
```

Open `http://127.0.0.1:8100`. `--host` and `--port` override the listener settings.
`PORTAL_ALLOWED_NETWORKS` is a comma-separated client allowlist; narrow it to the proxy
when using a reverse proxy. The app queries only approved views even though the shared
SQL credential can have broader privileges. Obsolete `PORTAL_SQL_*` and `PORTAL_DATABASE`
settings have no effect. Elasticsearch and model configuration are unnecessary.

`GET /healthz` checks every required column of all six reader views with `SELECT TOP 0`.
It returns 503 if a view or required column is unavailable, without reading alert rows,
querying database metadata or applying migrations. The packaged column contract matches
the pinned design snapshot; deployment must still use the release's supported migration set.

The database and migrations belong to `venaTeam/alerts-bi-runs`; apply its migrations
before starting the portal. This repository never migrates or seeds the database.
There is no runtime dependency on a sibling checkout. The immutable shared wheel in
`vendor/` and the committed `uv.lock` make an isolated clone installable.

```powershell
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen mypy
uv run --frozen pytest -q
uv build
docker build -t alerts-bi-portal:local .
```

The default container listener remains loopback. A deployment may explicitly set
`PORTAL_HOST=0.0.0.0` when it provides the intended network boundary and allowlist.
Images contain no credentials or database migrations.

Canonical product decisions and coordinated SQL integration/acceptance tests live in
`venaTeam/alerts-bi-design`. The pinned snapshot in `docs/upstream/` allows agents to work
from this clone alone. Update the shared wheel with its source release and contract pin;
never edit a released wheel in place.

Imported from `venaTeam/alerts-bi` at `c518eeaeb5a3ecb35b5348828300454379e7d535`.
The merged portal-tab update from `a9e4495` (PR #12) was restored on 2026-10-08;
the initial extraction used code from before that update. Shared presentation is supplied by the vendored
`alerts-bi-shared` 0.1.1 wheel. Standalone imports and schema readiness remain intact.


Application code lives directly in `src/`. Local tests import `src`, while setuptools
maps that directory to the service's distinct installed Python package. The console
command and Docker listener are unchanged. `uv sync --frozen` installs the editable
mapping; `uv build` produces the independently installable wheel and source archive.
