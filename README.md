# Alerts BI review portal

The independent GET-only reader app renders published weeks from eleven `portal_*`
SQL Server views. It keeps the existing network allowlist, publication
isolation and weekly totals. It cannot execute runs, publish reviews or record decisions.

Each team week has seven tabs: Overview, Fix list, Volume, Dashboards, Migration,
History and Slides. Problems have plain-language names. The week menu keeps the selected
tab, and older work-list links redirect to the Fix list with their filters intact.

Python 3.12+ and Poetry 2.3.1 are required. From this repository:

```powershell
poetry sync --no-root
poetry run python -m ensurepip --upgrade
poetry run python -m pip install --no-deps -e .
Copy-Item .env.example .env
# Set SQL_* to the same database and login used by alerts-bi-admin.
poetry run alerts-bi-portal
```

Open `http://127.0.0.1:8100`. `--host` and `--port` override the listener settings.
`PORTAL_ALLOWED_NETWORKS` is a comma-separated client allowlist; narrow it to the proxy
when using a reverse proxy. The app queries only approved views even though the shared
SQL credential can have broader privileges. Obsolete `PORTAL_SQL_*` and `PORTAL_DATABASE`
settings have no effect. Elasticsearch and model configuration are unnecessary.

`GET /healthz` checks every required column of all eleven reader views with `SELECT TOP 0`.
It returns 503 if a view or required column is unavailable, without reading alert rows,
querying database metadata or applying migrations. The packaged column contract matches
the pinned design snapshot; deployment must still use the release's supported migration set.

The database and migrations belong to `venaTeam/alerts-bi-admin`; apply its migrations
before starting the portal. This repository never migrates or seeds the database.
There is no runtime dependency on a sibling checkout. The immutable shared wheel in
`vendor/` and the committed `poetry.lock` make an isolated clone installable.

```powershell
poetry run ruff format --check .
poetry run ruff check .
poetry run mypy
poetry run pytest -q
poetry build
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
`alerts-bi-shared` 0.1.8 wheel. Standalone imports and schema readiness remain intact.
Shared 0.1.7 with pymssql 2.4.4 applies `SQL_ENCRYPT=true` as required TLS (the server
certificate is not validated, so it stops passive reading but not an active interceptor),
rejects unknown `SQL_ENCRYPT` values and `SQL_TRUST_SERVER_CERTIFICATE=false` at startup, and
logs `sql.unencrypted` once at startup when encryption is off.

Summaries use exact stored aggregates and bounded examples. Fix lists use seek pagination
and fetch evidence only for the visible page; existing numbered-page links still work.
Each web process owns a bounded SQL connection pool. Publication is checked on every request.
Deploy after admin migrations 012 and 013; see `docs/upstream/read-path-performance.md`.

The application selector above the team tabs filters alerts and weekly summaries across
every tab. Choose several applications and Apply, remove individual chips, or Show all.
Search within the dropdown without losing checked applications outside the results.
Cancel, Escape and outside-click discard pending edits without reloading. Applying an
unchanged all-applications view keeps **All applications**. Explicit subsets stay explicit.
Selections show the first three chips with **Show more** / **Show less** for the rest.
One static same-origin script enhances search, discard and unchanged-all submission;
CSP continues to block inline scripts, eval and third-party scripts. GET filters,
native Cancel dismissal and chip disclosure remain usable without scripting.
Selections persist in the URL through weeks, alert details and Fix list pagination.
An empty selection shows no alerts. Daily charts and event shares that cannot be split by
application are labeled unavailable; published phase, readiness percentage and notes remain
explicitly whole-team context. The feature remains GET-only and requires no schema migration.


Application code lives directly in `src/`. Local tests import `src`, while setuptools
maps that directory to the service's distinct installed Python package. The console
command and Docker listener are unchanged. `poetry sync --no-root` installs the
locked dependencies; `poetry run python -m ensurepip --upgrade` bootstraps pip
in existing uv-created environments before `poetry run python -m pip install
--no-deps -e .` installs the editable setuptools mapping. Keep these three setup
commands together: Poetry's own editable installer does not map `src` to the service
namespace. `poetry build` uses the declared setuptools backend to produce the
independently installable wheel and source archive. Docker installs that wheel.
Run `poetry check --lock` to validate the committed lockfile. `docs/upstream/`
is a pinned historical snapshot; current service commands are listed here.

When updating the vendored shared wheel, finish the artifact first, then run
`poetry update alerts-bi-shared --lock --no-cache`. The unit suite checks the actual
archive hash against the lock. Also verify `poetry sync --only main --no-root` in a
fresh environment: `poetry check --lock` does not validate the vendored file's bytes.

Shared-library source and migration/mock tooling are maintained in alerts-bi-admin. Portal remains independently installable with its pinned shared wheel and requires no admin source, engine, operations library or registry. See docs/upstream/runs-retirement.md for the coordinated source retirement.

Team links preserve legacy slugs and encode other IDs as a single `~`-prefixed UTF-8 hex
segment. Shared 0.1.8 supplies the codec for all week, tab and alert links. Deploy with
admin migration `017_case_sensitive_teams` so case-distinct team IDs stay separate in
published views. Migration and registry rollout belong to admin; rollback must also restore
an older-validator-compatible registry, while retaining the binary team columns.
