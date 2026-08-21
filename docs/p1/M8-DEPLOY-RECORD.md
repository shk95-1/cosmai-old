# M8-DEPLOY-RECORD — cosmai through the stack compose

- Milestone: M8 (local deployment through `/home/user1/github_prj/Main/service/stack`).
- Repos touched: `cosmai` (this repo, branch `dev` — images and one migrator entrypoint),
  `stack` (`/home/user1/github_prj/Main/service/stack`, branch `master` — compose
  integration, `init/50`, `env.example`, `README.md`; that repo's own conventions govern
  its files, not this one's).
- Date: 2026-08-21.

## (a) Binding decisions (owner-confirmed, this session)

`[결정]` **D1 — database-per-service stands; cosmai is not folded into `app`.**
`stack`'s own `docker-compose.yml`/`README.md` record a 2026-08-21 structural decision to
convert trend-radar and tubedepth from database-per-service to one database (`app`) with a
schema per service, and its README's "다음 서비스 추가 (cosmai)" section (now rewritten —
see the `stack` commit) assumed cosmai would follow that same conversion. That assumption is
overridden here: cosmai keeps its own database `cosmai` (+ `cosmai_test`) on the shared
server, per this repo's own DP-032 D1 ("P1 owns a dedicated database `cosmai` ... it does
not partition a shared database by schema"), reconfirmed by the owner in this session's
brief in near-identical words ("DB policy: database-per-service STANDS ... Do NOT fold
cosmai into the `app` database/schema model"). `[확인 사실]` The live `cosmai` database
already carries real data from M1–M7's demo work; this milestone does not migrate it —
today's data is the production target.

`[결정]` **D2 — cosmai's runtime containers (`api`/`worker`/`scheduler`/`migrate`) use
`network_mode: host`.** cosmai's outbound policy allows plain HTTP only to loopback, and
every currently-registered source's `outbound_profile` already names `127.0.0.1:8000`
(trend-radar) or `127.0.0.1:8080` (tubedepth) — `[측정]` confirmed live: `postgrest-cosmai`'s
anonymous `SELECT` on `source` returned `"outbound_profile":{"port": 8000, "hosts":
["127.0.0.1"], ...}` for `trendradar` unchanged. Host networking reaches those addresses
with zero code or DB-row change; joining `db-net` and re-pointing every profile at
`shared-db-trend-radar-dashboard-1:8000` would have required editing rows this milestone did
not create and does not own. Cost: these four services cannot also join `db-net` (compose
does not allow both `network_mode` and `networks` on one service), and DB access goes
through the host's published `127.0.0.1:${SHARED_PG_HOST_PORT:-5434}` rather than a
container name.

`[결정]` **D3 — PostgREST exposes all of schema `cosmai`, anonymously, and the owner
accepted the ODbL consequence.** `postgrest-cosmai` grants `postgrest_cosmai_anon` `SELECT`
on every table in schema `cosmai` (plus a default-privilege grant so a table created by a
future migration is covered too), mirroring the existing `postgrest`/`init/20`/`init/40`
pattern exactly except that it is a second PostgREST instance against a second database
(one instance can only see the schemas of the database it is connected to). A dated addendum
was appended to [`docs/open-questions/OQ-015-share-alike-data-class.md`](../open-questions/OQ-015-share-alike-data-class.md):
the question ("where does share-alike-encumbered data sit") was `OPEN` and low-priority
because nothing in P0 published; a publication surface now exists by this decision, so the
question is live rather than deferred. The addendum does not resolve OQ-015 — no taxonomy
decision is made here.

## (b) What was built (cosmai repo)

- **`apps/Dockerfile`** — `python:3.13-slim` + `uv` (copied from `ghcr.io/astral-sh/uv:0.5`,
  not pip-installed). Preserves `apps/` as a subdirectory of `/app` (`/app/apps/...`) rather
  than flattening it — the Dockerfile's own comment explains why: `platform_core.secrets
  .secret_store_path` refuses a store that resolves inside `WORKING_TREE_ROOT`
  (`Path(__file__).resolve().parents[2]`); flattening would put that root at `/`, which is
  an ancestor of every absolute path and would make the guard refuse every secret-store
  location including the correct one. Non-root compatible: the stack runs it as
  `user: "1000"` (the tubedepth pattern), so the image `chmod -R a+rX /app`s instead of
  creating a baked-in user. `ENTRYPOINT ["cosmai-entrypoint"]` dispatches on the container
  command via `apps/docker-entrypoint.sh`:
  - `migrate` → `python -m platform_core.db` (new, see below)
  - `api` → `python -m addon_host` (platform + domain surface, not the bare
    `platform_core.api` — the latter must keep serving the source-neutral P0-A gate surface)
  - `worker` → `python -m addon_host.worker`
  - `scheduler` → `python -m scheduler`
- **`apps/platform_core/db/__main__.py`** (new) — no CLI entrypoint existed for
  `platform_core.db.migrate.apply_migrations`; it was only ever called from a pytest fixture.
  This module is the same three calls (`load_config` → `connect(role="migrator")` →
  `apply_migrations`) wired as a one-shot process: configuration-first with a fatal refusal
  (`EXIT_CONFIGURATION_INVALID`, matching every other P1 entrypoint), a classified connect
  failure, and a `{"event": "migrate.report", "applied": [...]}` object on standard output.
  `mypy --strict` and `ruff check` both clean on this file; `tests/environment` (root guard,
  87 tests) unaffected and still green.
- **`apps/Dockerfile.dashboard`** — `node:22-slim` build stage (`npm ci && npm run build`) →
  `nginx:alpine`. No `VITE_API_BASE` build argument is passed: `dashboard/src/api/client.ts`'s
  `DEFAULT_API_BASE` is already `http://127.0.0.1:8100` (M-X2's fix, matching
  `platform_core.config`'s own `COSMA_API_PORT` default) — exactly where `cosmai-api` binds
  under host networking. This is the "mechanism requiring least change" the brief asked for:
  zero build args, zero runtime config injection. `[측정]` confirmed: the built bundle
  contains the literal string `127.0.0.1:8100`.
- **`apps/dashboard/nginx.conf`** (new) — an SPA fallback (`try_files $uri $uri/ /index.html`)
  for `react-router-dom`'s `BrowserRouter` (`src/App.tsx`); the stock `nginx:alpine` config
  404s a direct load of any nested route without it.
- **`apps/.dockerignore`** — excludes `.venv/`, `__pycache__/`, `.pytest_cache/`,
  `.mypy_cache/`, `.ruff_cache/`, `dashboard/node_modules/`, `dashboard/dist/`. One file, not
  one per Dockerfile: both images share build context `apps/`.

`[측정]` Both images build clean (`docker build`/`docker compose build`, no warnings beyond
oxlint's pre-existing dependency deprecation notices from `npm ci`, unrelated to this work).

## (c) What was built (stack repo — see that repo's own commit for its full diff)

- `docker-compose.yml`: `x-cosmai-environment` anchor; `shared-postgres`'s `environment`
  gained `COSMAI_MIGRATOR_PASSWORD`/`COSMAI_RUNTIME_PASSWORD`/`POSTGREST_COSMAI_PASSWORD`
  and its `volumes` gained the `init/50` mount; six new services (`cosmai-migrate`,
  `cosmai-api`, `cosmai-worker`, `cosmai-scheduler` on `network_mode: host`;
  `cosmai-dashboard`, `postgrest-cosmai` on `db-net`). `cosmai-worker` gets
  `stop_grace_period: 45s` — `platform_core.worker`'s shutdown is cooperative, bounded by
  `COSMA_LEASE_SECONDS` (default 30s), so 45s leaves margin without inheriting tubedepth's
  120s (a different handler, a different bound).
- `init/50-cosmai-bootstrap.sh` (new): mirrors `init/20`/`init/40`'s idempotent
  `CREATE ROLE ... WHERE NOT EXISTS ... \gexec` shape, with one deliberate deviation
  documented in the script itself — `cosmai_owner`/`cosmai_migrator`/`cosmai_runtime`'s
  passwords are set **only** at the moment `CREATE ROLE` actually fires, never by an
  unconditional `ALTER ROLE ... PASSWORD` on every run (unlike `init/20`'s
  `postgrest_authenticator`, which has no consumer outside this compose project).
  `cosmai_owner`/`migrator`/`runtime` already carry live credentials in
  `~/.config/cosmai/env`, outside this repo; reissuing them on every re-run would silently
  invalidate that file. `postgrest_cosmai_authenticator`/`postgrest_cosmai_anon` (new roles,
  no outside consumer) follow the `init/20` pattern unchanged.
- `../postgrest/postgrest-cosmai.env` (new, sibling directory, untracked — same place the
  existing `postgrest.env` lives, outside any git repo): `PGRST_DB_SCHEMAS=cosmai`,
  `PGRST_DB_ANON_ROLE=postgrest_cosmai_anon`.
- `env.example`, `README.md`: new key names, the six-row table addition, and a rewritten
  "cosmai" section replacing the old "다음 서비스 추가 (cosmai)" placeholder — it now
  explains the database-per-service divergence, the host-network rationale, the PostgREST
  exposure decision, and the one-role-family password exception, each with a pointer back
  here for detail.

## (d) Live bring-up and smoke evidence

All commands run against the live stack (`docker compose`, project `shared-db`,
`/home/user1/github_prj/Main/service/stack`). No secret value appears below.

| Check | Command | Result |
|---|---|---|
| `init/50` idempotent | ran twice via `docker exec shared-postgres bash /docker-entrypoint-initdb.d/50-cosmai-bootstrap.sh` | both runs exit 0; second run's `CREATE ROLE`/`CREATE SCHEMA` lines are `NOTICE: already exists, skipping` |
| existing cosmai credentials undisturbed | `cosmai:test migrate` run before and after `init/50` | both succeed identically (`{"event": "migrate.report", "applied": []}`) — same `~/.config/cosmai/env` |
| `cosmai-migrate` exits 0 | `docker compose up -d cosmai-migrate`, then `docker inspect ... .State.ExitCode` | `0`; schema already current (`"applied": []}` — no-op, as expected) |
| `cosmai-api` healthz | `curl http://127.0.0.1:8100/health` | `{"status":"ok","database":"reachable","database_name":"cosmai",...}` (route is `/health`, not `/healthz` — `platform_core.api.app`'s actual route name) |
| `cosmai-dashboard` serves, points at 8100 | `curl -o /dev/null -w '%{http_code}' http://127.0.0.1:8101/` → `200`; built bundle inspected for `127.0.0.1:8100` | 200; string present |
| `postgrest-cosmai` anonymous SELECT | `curl http://127.0.0.1:3002/source?limit=1` | 7 source rows readable (`trendradar`, `naver.blog`, ... — one returned) |
| `postgrest-cosmai` write refused | `curl -X POST http://127.0.0.1:3002/source -d '{"source_id":"nope",...}'` | `{"code":"42501","message":"permission denied for table source"}` |
| scheduler creates a due job | `PUT /sources/trendradar/schedule {"enabled":true}` (the demo row existed, `enabled=false`; enabled it through the API rather than a direct DB write) then watched logs | `scheduler.job_created` for `addon:collector.trendradar.rest` within one poll interval |
| worker completes it against live trend-radar | `docker logs cosmai-worker` | `addon.collect.run_complete` (`items_emitted: 900, pages_fetched: 20`) then `job.transition ... to_state: SUCCEEDED` — `jobs_by_state.SUCCEEDED` on `/health` rose from 8 to 10 across the two collect passes exercised in this milestone |
| no port collision | `ss -ltnp` on 8100/8101/3002 | exactly one listener each, all `127.0.0.1` except `3002` (deliberately `0.0.0.0`, same exposure class as the existing `postgrest`) |
| no lingering host-run duplicates | `pgrep -fa 'platform_core\|addon_host\|scheduler'` | exactly one `addon_host`, one `addon_host.worker`, one `scheduler` process — the three containers, nothing from M7 |
| `shared-postgres` recreate side effect | compose recreated `shared-postgres` (env/volume changes forced it) — checked all pre-existing containers afterward | `docker ps`: `trend-radar-collector`, `trend-radar-dashboard`, `tubedepth-api`(healthy), `tubedepth-worker`, `tubedepth-watch`, `data-portal`, `postgrest` all still `Up`; `shared-postgres` log shows a clean shutdown/restart against the existing bind-mounted data directory, not a reinitialization (`"Skipping initialization"`) |

## (e) Gates

- `.venv/bin/python -m pytest tests/environment -q` — 87 passed (run before and after the
  `apps/` changes in this milestone; unaffected by them).
- `cd apps && uv run ruff check platform_core/db/__main__.py` — clean.
- `cd apps && uv run mypy --strict platform_core/db/__main__.py` — clean.
- `docker build`/`docker compose build` for both images — clean.

## (f) Deviations and concerns

- `[측정]` Bringing up `cosmai-migrate` for the first time forced compose to **recreate**
  `shared-postgres` (its `environment`/`volumes` changed). This briefly restarted the shared
  PostgreSQL container while `trend-radar-collector`/`tubedepth-worker`/etc. were live. Data
  is bind-mounted (`${SERVICE_DATA_DIR}/postgres` → `/var/lib/postgresql`), not a Docker
  volume tied to the old container, so nothing was lost — confirmed by the post-recreate
  `docker ps` and log check in row (d)'s last line — but this is a real, if brief,
  availability cost to the other services that a future infrastructure change to
  `shared-postgres` should expect again as long as it stays one container serving every
  service.
- The stack's `README.md` documented, before this milestone, an assumption that cosmai
  would join the single-`app`-database conversion ("다음 서비스 추가 (cosmai): 서비스
  추가 = `app` database 에 schema 하나 추가. database 는 만들지 않는다"). That assumption
  is now factually wrong and was rewritten as part of this milestone's `stack` commit — see
  (a) D1. Flagged here because it is exactly the kind of cross-repo assumption drift this
  repo's own `AGENTS.md` asks to be recorded rather than routed around silently.
- `postgrest-cosmai`'s schema-wide anonymous grant means any table added to schema `cosmai`
  by a future migration is exposed by default (the default-privilege grant is deliberate,
  matching `init/40`'s tubedepth pattern) — a future migration that adds a table meant to
  stay unlisted (an authentication or credential-adjacent table, the way `tubedepth.api_keys`
  is excluded today) needs an explicit `REVOKE` in that migration or a follow-up to
  `init/50`, not a silent assumption that new tables start hidden.
- No data migration was performed or was in scope — D1 states this explicitly. The 10/6
  succeeded/failed job counts referenced in row (d) include this milestone's own two
  additional collect passes on top of the pre-existing demo data; no row count comparison
  against a prior state was needed because nothing was moved.
