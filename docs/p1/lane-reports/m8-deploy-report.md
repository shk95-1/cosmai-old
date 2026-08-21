# M8 deploy report — cosmai through the stack compose

- Repos: `cosmai` (this repo, branch `dev`) and `stack`
  (`/home/user1/github_prj/Main/service/stack`, branch `master`) — two separate git
  histories, two separate commits, neither pushed.
- Full account: [`docs/p1/M8-DEPLOY-RECORD.md`](../../../docs/p1/M8-DEPLOY-RECORD.md)
  (decisions, build details, the full smoke-check table, deviations). This file is the
  short-form report; it does not repeat evidence already tabulated there.

## Status

Complete. All six new stack services are live, migrate exits 0, api/dashboard/postgrest
smoke checks pass, and a full scheduler → worker → live-trend-radar collect cycle ran
successfully against the demo data already on the shared server. No data migration was
performed or in scope.

## Binding decisions honored (detail in the record's §a)

- Database-per-service stands — cosmai keeps its own database `cosmai` on the shared
  server; it was **not** folded into the stack's `app` database/schema model, even though
  the stack's own README had (before this milestone) assumed cosmai would follow that
  conversion. The stack `README.md`/`docker-compose.yml` comments were corrected to say so.
- `cosmai-migrate`/`-api`/`-worker`/`-scheduler` run `network_mode: host`; DB from these
  containers is `127.0.0.1:${SHARED_PG_HOST_PORT:-5434}`.
- `postgrest-cosmai` exposes all of schema `cosmai` to anonymous `SELECT`. A dated addendum
  recording the ODbL consequence was appended to
  [`docs/open-questions/OQ-015-share-alike-data-class.md`](../../../docs/open-questions/OQ-015-share-alike-data-class.md)
  — the question moves from hypothetical to live; it is not resolved by this milestone.

## Per-smoke-check pass/fail

| Check | Result |
|---|---|
| `init/50-cosmai-bootstrap.sh` idempotent (run twice) | PASS |
| Existing `~/.config/cosmai/env` credentials undisturbed by `init/50` | PASS |
| `cosmai-migrate` exits 0 (no-op, schema current) | PASS |
| `cosmai-api` health (`/health`, not `/healthz`) | PASS |
| `cosmai-dashboard` serves and bundle points at `127.0.0.1:8100` | PASS |
| `postgrest-cosmai` anonymous SELECT | PASS |
| `postgrest-cosmai` anonymous write refused (`42501`) | PASS |
| Scheduler creates a due job (schedule row existed, disabled; enabled via `PUT
  /sources/trendradar/schedule`) | PASS |
| Worker completes the job against live trend-radar (900 items, 20 pages) | PASS |
| No port collision on 8100/8101/3002 | PASS |
| No lingering host-run duplicate processes from before this milestone | PASS |
| `shared-postgres` recreate (forced by compose env/volume changes) did not lose data or
  break the other four already-running services | PASS (side effect noted below, not a
  failure) |

## Gates

- `.venv/bin/python -m pytest tests/environment -q` — 87 passed.
- `cd apps && uv run ruff check platform_core/db/__main__.py` — clean.
- `cd apps && uv run mypy --strict platform_core/db/__main__.py` — clean.
- Both images (`apps/Dockerfile`, `apps/Dockerfile.dashboard`) build clean via
  `docker compose build`.

## Concerns (full detail in the record's §f)

1. Bringing up `cosmai-migrate` forced compose to recreate `shared-postgres` (its
   `environment`/`volumes` changed), briefly restarting the shared PostgreSQL container
   while trend-radar/tubedepth were live. Data is bind-mounted, not lost — verified after
   the fact — but this is a real availability cost future changes to `shared-postgres`
   should expect again as long as it stays one container for every service.
2. The stack's README previously assumed cosmai would join the single-`app`-database
   conversion; that assumption was factually wrong and has been corrected in the `stack`
   commit — flagged as cross-repo assumption drift, per this repo's own instruction to
   record rather than route around such gaps.
3. `postgrest-cosmai`'s grant is schema-wide and includes a default-privilege grant, so a
   future migration's new table is exposed by default unless it explicitly revokes.

## Commits

- `cosmai` (branch `dev`): images (`apps/Dockerfile`, `apps/Dockerfile.dashboard`,
  `apps/docker-entrypoint.sh`, `apps/.dockerignore`, `apps/dashboard/nginx.conf`), the new
  migrator entrypoint (`apps/platform_core/db/__main__.py`), the OQ-015 addendum, and the
  deploy record + this report — recorded by hash in the coordinator's final summary.
- `stack` (branch `master`): `docker-compose.yml`, `init/50-cosmai-bootstrap.sh`,
  `env.example`, `README.md` — recorded by hash in the coordinator's final summary. Neither
  repo was pushed.
