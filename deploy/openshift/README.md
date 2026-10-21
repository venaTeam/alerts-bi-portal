# Deploying the Alerts BI portal on OpenShift

This folder holds everything needed to deploy `alerts-bi-portal`, the read-only review portal.
It reads only the published `portal_*` SQL views. It runs no analysis, has no login and never
migrates the database.

Deploy `alerts-bi-admin` first, with `deploy/openshift/README.md` in the `alerts-bi-admin`
repository: it creates the shared configuration this portal reads, and its migrations create
the views. Then follow the sections below in order. You supply only the values listed in
[Values you supply](#3-values-you-supply). Never edit the template to make a deployment work.
When a result differs from the "Expect" line, stop, use [Troubleshooting](#9-troubleshooting)
and continue only once the result matches. Deploying needs authorization from the service owner;
these files do not grant it.

| File | What it is |
|---|---|
| `portal.yaml` | Template: ServiceAccount, Deployment, Service and Route |
| `values.env.example` | Template values: image, route, allowlists, SQL Secret, sizing |
| `check_route_allowlist.py` | Checks `PORTAL_ROUTE_ALLOWLIST`, as `oc` reads it, before applying (sections 3 and 5) |

## 1. What gets deployed

```text
readers --HTTPS--> Route alerts-bi-portal (PORTAL_ROUTE_ALLOWLIST, edge TLS)
           --> Service alerts-bi-portal :8100 --> portal 0.0.0.0:8100 (PORTAL_ALLOWED_NETWORKS)
           --> SQL Server SQL_DATABASE, portal_* views only
```

| Object | Kind | Created by | Purpose |
|---|---|---|---|
| `alerts-bi-portal` | Deployment, Service, Route, ServiceAccount | `portal.yaml` | The portal and its HTTPS entry |
| `alerts-bi-config` | ConfigMap | the admin deployment | `SQL_HOST`, `SQL_PORT`, `SQL_DATABASE`, `SQL_ENCRYPT`, `SQL_TRUST_SERVER_CERTIFICATE`, `SQL_REQUEST_TIMEOUT_MS`, `LOG_LEVEL`, `LOG_FORMAT`, `LOG_FORWARD_URL`, `LOG_FORWARD_LEVEL` |
| `alerts-bi-secrets` | Secret | the admin deployment | `SQL_USER` and `SQL_PASSWORD` (the default `PORTAL_SQL_SECRET`) |
| `alerts-bi-portal-sql` | Secret | you, only for a reader-only login | `SQL_USER` and `SQL_PASSWORD` of that login |
| `alerts-bi-ca-bundle` | ConfigMap | the admin deployment, optional | Mounted so a shared `SSL_CERT_FILE` setting resolves |
| `alerts-bi-pull` | Secret | the admin deployment, optional | Image pull credentials |

The portal is reachable only from the networks in two allowlists. The Route's
`PORTAL_ROUTE_ALLOWLIST` filters the readers' real addresses at the router. Behind the router the
application sees the router's and in-cluster addresses, so `PORTAL_ALLOWED_NETWORKS` must admit
`127.0.0.0/8` and the cluster's pod and node networks.

## 2. Before you start

You need:

- `oc` 4.14 or later, logged in with the `edit` or `admin` role in the project where admin runs.
- A POSIX shell (bash, or Git Bash on Windows). Every command below is bash.
- `python3` 3.8.12 or later (3.9.5 or later on 3.9) for the allowlist check in section 3,
  standard library only. The check refuses to run on earlier releases, whose `ipaddress`
  accepts leading zeros the router refuses.
- The `alerts-bi-portal` checkout at the release commit, and the portal image built by CI from
  that commit. To build by hand: `podman build -t <registry>/<repository>:<commit> .` from the
  repository root, then `podman push <registry>/<repository>:<commit>`.
- A finished admin deployment of the same release: `deployment/alerts-bi-admin` rolled out with
  every migration applied. The portal of a release needs that release's migrations; for example,
  the shared 0.1.8 team links need `017_case_sensitive_teams`, and the Overview operators card
  needs `020_portal_review_operators`.

Set up your shell once per session:

```bash
PORTAL_REPO=/path/to/alerts-bi-portal         # checkout at the release commit
VALUES_DIR=/path/to/private/alerts-bi-values  # the same private directory as for admin
NS=alerts-bi                                  # the project where alerts-bi-admin runs
cd "$PORTAL_REPO/deploy/openshift"
oc get configmap/alerts-bi-config secret/alerts-bi-secrets -n "$NS"
oc rollout status deployment/alerts-bi-admin -n "$NS" --timeout=1m
```

Expect both objects listed and `successfully rolled out`. Otherwise deploy admin first.

## 3. Values you supply

| Value | Required | Where to get it |
|---|---|---|
| `PORTAL_IMAGE` | yes | Digest of the CI image for the release commit; see [Image reference](#image-reference) |
| `PORTAL_ROUTE_HOST` | no | Empty generates a host. Upgrade: the host of the existing portal Route |
| `PORTAL_ROUTE_ALLOWLIST` | yes, never empty (the example holds the private ranges) | The networks readers browse from, separated by single spaces, at most 61 entries. Upgrade: the existing Route's `haproxy.router.openshift.io/ip_allowlist` (or `ip_whitelist`) annotation |
| `PORTAL_ALLOWED_NETWORKS` | no | Keep the default unless the cluster networks are outside it; see below. Upgrade: the running value (the `PORTAL_ALLOWED_NETWORKS` line of `oc set env deployment/<portal> -n "$NS" --list`), plus `127.0.0.0/8` if it is missing |
| `PORTAL_SQL_SECRET` | no | `alerts-bi-secrets` until a reader-only login exists ([section 6](#6-reader-only-sql-login)). Upgrade: if the running portal reads `SQL_USER` from another Secret (`oc get deployment <portal> -n "$NS" -o yaml`), copy that Secret's two keys into `alerts-bi-portal-sql` (section 6) and use that name |
| `PORTAL_PAGE_SIZE` | no | Upgrade: the running value, if set |
| `PORTAL_REPLICAS` | no | Upgrade: the existing portal Deployment's replica count |

The SQL connection itself comes from the admin deployment's `alerts-bi-config` and
`alerts-bi-secrets`; the portal has no separate database settings.

`PORTAL_ALLOWED_NETWORKS` must contain `127.0.0.0/8` and the cluster's pod and node networks.
The default (loopback plus every private range) covers them when they are private addresses.
Check:

```bash
oc get network.config.openshift.io cluster -o jsonpath='{.status.clusterNetwork[*].cidr}{"\n"}'
oc get nodes -o jsonpath='{range .items[*]}{.status.addresses[?(@.type=="InternalIP")].address}{"\n"}{end}'
```

Every network and node address printed must fall inside one `PORTAL_ALLOWED_NETWORKS` entry.
If one does not, add that network to the value (comma-separated, no spaces). These are
cluster-wide reads: if they return `Forbidden`, keep the default and rely on the check in
section 7, which shows any refused address.

On OVN-Kubernetes the router can also connect from the cluster's internal join subnet
(`100.64.0.0/16` unless the cluster changed it), which the default does not include. Section 7
detects this: the pod log shows `portal.client_refused` with a `100.64.` address. Then add
`100.64.0.0/16` to `PORTAL_ALLOWED_NETWORKS` and repeat section 5.

### Prepare the value file

```bash
cp values.env.example "$VALUES_DIR/portal-values.env"
```

Fill in `PORTAL_IMAGE` and any value from the table above.

### Image reference

```bash
oc image info <registry>/<repository>:<tag>
```

Expect a `Digest: sha256:<64 hex>` line. `PORTAL_IMAGE` is `<registry>/<repository>@sha256:<64 hex>`.
Add `--registry-config=<auth.json>` when the registry needs credentials, and
`--filter-by-os=linux/amd64` when the output lists several platforms.

### Check the values

```bash
oc process --local -f portal.yaml --param-file "$VALUES_DIR/portal-values.env" -o yaml > "$VALUES_DIR/portal.rendered.yaml"
grep 'image:' "$VALUES_DIR/portal.rendered.yaml"
```

Expect no error from `oc process` and one `image:` line containing `@sha256:`.
`parameter PORTAL_IMAGE is required and must be specified` means that line is empty; the same
message for `PORTAL_ROUTE_ALLOWLIST` means the allowlist line is empty.

The portal has no login, and the router then admits every client: it sets no client ACL when
the Route's allowlist is empty, has leading or trailing spaces, or has any entry it cannot
parse as an IPv4 or IPv6 address or CIDR. So check every entry before applying. The check reads
the file the way `oc process` does, where the last assignment of a key wins, and accepts only
one plain `PORTAL_ROUTE_ALLOWLIST=<list>` line:

```bash
python3 check_route_allowlist.py "$VALUES_DIR/portal-values.env"
```

Expect `allowlist ok`. Each `STOP:` line names one problem, for example `'10.0.0.0/33' is not
a valid IPv4 or IPv6 address or CIDR`. Fix each one in `portal-values.env`: one to 61 IPv4 or
IPv6 addresses or CIDRs, separated by single spaces with none before or after, and none with a
`/0` prefix, on exactly one `PORTAL_ROUTE_ALLOWLIST=` line with no leading spaces, `export`,
quotes or comment. Then repeat this section.

## 4. Fresh install or upgrade?

```bash
oc get deployment,service,route -n "$NS" -o custom-columns='KIND:.kind,NAME:.metadata.name,IMAGES:.spec.template.spec.containers[*].image,HOST:.spec.host'
```

- No object runs an `alerts-bi-portal` image: fresh install. Continue with section 5.
- `deployment/alerts-bi-portal` exists: upgrade in place. Record it first, then continue with
  section 5:

  ```bash
  mkdir -p "$VALUES_DIR/previous"
  oc get deployment,service,route -n "$NS" -l app=alerts-bi-portal -o yaml > "$VALUES_DIR/previous/portal-objects.yaml"
  oc get deployment alerts-bi-portal -n "$NS" -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}' | tee "$VALUES_DIR/previous/portal-image.txt"
  ```

- A portal runs under another name: record its objects the same way (by name instead of `-l`),
  including the old Route's host (`oc get route <old-route> -n "$NS" -o jsonpath='{.spec.host}'`).
  Leave `PORTAL_ROUTE_HOST` empty for the first deploy, because the old Route still holds that
  host, and run sections 5 and 7 against the generated host. Then move the host over, with the
  service owner's authorization. Changing an existing Route's host needs `update` on
  `routes/custom-host`, which the `edit` and `admin` roles lack, so the temporary Route is
  recreated rather than edited:

  ```bash
  oc delete route/<old-route> route/alerts-bi-portal -n "$NS"
  ```

  Set `PORTAL_ROUTE_HOST` to the old host and repeat section 5 (it creates the Route with that
  host, which the default rights allow) and section 7. Readers see no portal between the delete
  and the apply. Only after section 7 passes on the old host, delete the old Deployment and
  Service.

## 5. Deploy

Run this block as one unit. It checks the allowlist again (section 3), renders, dry-runs, applies
and waits, and the first step that fails stops it: nothing after that step runs, so a refused
allowlist is never rendered or applied. The parentheses keep `set -e` out of your own shell.

```bash
(
  set -e
  python3 check_route_allowlist.py "$VALUES_DIR/portal-values.env"
  oc process --local -f portal.yaml --param-file "$VALUES_DIR/portal-values.env" -o yaml > "$VALUES_DIR/portal.rendered.yaml"
  oc apply -n "$NS" --dry-run=server -f "$VALUES_DIR/portal.rendered.yaml"
  oc apply -n "$NS" -f "$VALUES_DIR/portal.rendered.yaml"
  oc rollout status deployment/alerts-bi-portal -n "$NS" --timeout=10m
)
```

Expect `allowlist ok`, the dry run to list four objects ending in `(server dry run)`, the apply
to list them as `created`, `configured` or `unchanged`, and
`deployment "alerts-bi-portal" successfully rolled out`. Any `STOP:` line or error means the
block stopped there: fix the cause and run the whole block again. Do not run its lines one by
one, and do not add `||` or `&&` after the closing parenthesis, which would switch `set -e` off.

## 6. Reader-only SQL login

By default the portal shares the admin SQL login, as the design requires until the
database-owning team provides a login that belongs only to the `alerts_bi_reader` role. When
that login exists, switch only the portal:

```bash
oc create secret generic alerts-bi-portal-sql -n "$NS" --from-literal=SQL_USER='<reader login>' --from-literal=SQL_PASSWORD='<reader password>'
```

Set `PORTAL_SQL_SECRET=alerts-bi-portal-sql` in `portal-values.env`, repeat section 5 and
section 7. Admin, its migrations and jobs keep the owning login. Record the switch, with its date,
in the design section on the portal SQL login. Rollback: set `PORTAL_SQL_SECRET=alerts-bi-secrets`
and repeat section 5.

## 7. Verify

```bash
oc exec -n "$NS" deploy/alerts-bi-portal -- python -c '
import urllib.error, urllib.request
try:
    response = urllib.request.urlopen("http://127.0.0.1:8100/healthz", timeout=60)
except urllib.error.HTTPError as error:
    response = error
print(response.getcode(), response.read().decode())
'
```

Expect `200 {"ok":true,"version":"..."}`: every required column of the eleven portal views is
readable. `503` means a view or column is missing (admin migrations not applied, or another
database); `403 Forbidden` means `PORTAL_ALLOWED_NETWORKS` lacks `127.0.0.0/8`.

```bash
ROUTE_HOST=$(oc get route alerts-bi-portal -n "$NS" -o jsonpath='{.spec.host}')
curl -sk -o /dev/null -w '%{http_code}\n' "https://$ROUTE_HOST/"
curl -sk -o /dev/null -w '%{http_code}\n' -X POST "https://$ROUTE_HOST/"
```

From a machine inside `PORTAL_ROUTE_ALLOWLIST`, expect `200` and then `405` (the portal is
read-only). Repeat the first `curl` about ten times (the router may connect from different nodes),
then check that nothing was refused:

```bash
oc logs -n "$NS" deploy/alerts-bi-portal --since=10m | grep portal.client_refused
```

Expect no output. A refused address means `PORTAL_ALLOWED_NETWORKS` misses that network
(section 3). Ask a reader to open the portal in a browser: the team directory lists the teams with
published weeks, a team week opens on every tab, and the week published during the admin
verification is visible.

## 8. Day-2 operations

**New release.** Deploy admin first when the release contains migrations. Then set the new
`PORTAL_IMAGE`, check out this folder at the release commit and repeat sections 5 and 7.

**SQL setting or credential change.** These live in the admin deployment's `alerts-bi-config`
and `alerts-bi-secrets` (or `alerts-bi-portal-sql`). After changing them, restart the portal:

```bash
oc rollout restart deployment/alerts-bi-portal -n "$NS"
oc rollout status deployment/alerts-bi-portal -n "$NS" --timeout=10m
```

**SQL encryption.** Follows the admin runbook's "Turn on SQL encryption"; restart the portal
there too.

**Rollback.** Put the previous digest from `previous/portal-image.txt` in `PORTAL_IMAGE` and
repeat section 5 with the previous release's `portal.yaml` (or re-apply
`previous/portal-objects.yaml` after removing `status`, `metadata.resourceVersion`,
`metadata.uid` and `metadata.managedFields`). The portal has no migrations, but a portal older
than the database's migrations may not find the views it expects. Do not roll back to a portal
older than shared 0.1.8 while encoded team links (`/teams/~...`) are in use.

## 9. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `oc process`: `parameter PORTAL_IMAGE is required and must be specified` | Fill `PORTAL_IMAGE` in `portal-values.env` |
| `CreateContainerConfigError` | `alerts-bi-config` or `PORTAL_SQL_SECRET` (with `SQL_USER` and `SQL_PASSWORD`) is missing; `oc describe pod -n "$NS" -l app=alerts-bi-portal` names it |
| `ImagePullBackOff` | Wrong digest or missing credentials: see the admin runbook's pull secret step |
| Container exits: `PORTAL_ALLOWED_NETWORKS entry ... is not a network` | Fix the value: comma-separated CIDRs |
| Container exits: `env SQL_ENCRYPT must be one of ...` or `SQL_TRUST_SERVER_CERTIFICATE=false is not supported` | Fix `alerts-bi-config` (admin runbook, SQL encryption) |
| `/healthz` 503 | The views are missing or behind: check `alerts-bi-admin db status` (admin runbook) and that `SQL_DATABASE` is the admin database |
| Every page `Forbidden` from inside the allowlist | The router's or node's address is outside `PORTAL_ALLOWED_NETWORKS` (section 3); the pod log shows `portal.client_refused` with the address |
| Connection refused or reset from a reader's machine | The reader's network is outside `PORTAL_ROUTE_ALLOWLIST` |
| Browser: `Application is not available` | No ready pod: `oc get pods -n "$NS" -l app=alerts-bi-portal` and the rows above |
| Route shows `HostAlreadyClaimed` | Another Route holds `PORTAL_ROUTE_HOST`; see section 4 |
| Apply or dry run fails on the Route's `spec.host` (immutable, or `routes/custom-host` forbidden) | `PORTAL_ROUTE_HOST` differs from the live Route's host; an existing Route's host cannot be changed with the `edit`/`admin` roles. Delete `route/alerts-bi-portal` and repeat section 5, as in section 4 |
| Apply fails: `spec.selector: ... field is immutable` | The existing `alerts-bi-portal` Deployment uses other labels. With the service owner's authorization, `oc delete deployment alerts-bi-portal -n "$NS"` (readers see a short outage) and repeat section 5 |
| Pods rejected: `must specify limits.cpu` | The project's quota needs CPU limits. Stop and ask the project owner for a LimitRange with default CPU limits |

## 10. Rules that always apply

- Deploy admin, with its migrations, before the portal of the same release.
- The portal only reads `SQL_DATABASE`, the admin database. It never gets its own database
  setting, Elasticsearch or model credentials, or the admin registry. The non-secret
  `alerts-bi-config` keys it receives besides `SQL_*` and `LOG_*` are ignored. When the admin
  runbook's section 15 sets `LOG_FORWARD_URL`, restart the portal so it also sends its records
  to the log collector (`<prefix>-portal-*` indices).
- Keep both allowlists: the Route's for readers, the application's for the router and the cluster.
- Never run migrations, `db` commands or any writer from the portal image.
- Secrets live only in the cluster: never commit filled value files or paste them anywhere.
