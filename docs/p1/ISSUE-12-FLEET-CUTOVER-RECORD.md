# ISSUE-12-FLEET-CUTOVER-RECORD — cosmai joins `db-net`

- Governing decision: [DP-035](../decisions/DP-035-fleet-egress-and-container-bind.md)
  (owner decision 2026-08-21, GitHub issue #12, `priority: highest`).
- Packet: [TASK-012](../agent-workflow/task-packets/TASK-012-fleet-egress-and-container-bind.md)
  (`ACCEPTED`), attack report [REVIEW-TASK-012](../agent-workflow/reviews/REVIEW-TASK-012.md)
  (`PASS` on re-review).
- Repos touched: `cosmai` (`dev`, merge `e6d170b` of `platform/issue-12-fleet-egress`),
  `stack` (`/home/user1/github_prj/Main/service/stack`, `master` — compose + README).
- Cutover date: 2026-08-23 (UTC 04:48–04:53), executed by the session with the owner's
  explicit permission for the live-system commands.
- Supersedes: [M8-DEPLOY-RECORD](M8-DEPLOY-RECORD.md) (a) D2 (`network_mode: host`).

## Stop window, in the order DP-035 requires

| Step | Command (no secret values) | Result |
|---|---|---|
| new image | `docker compose build cosmai-migrate` (context = `dev` working tree at `e6d170b`) | `Image cosmai Built` |
| stop | `docker compose stop cosmai-api cosmai-worker cosmai-scheduler` | three `Stopped` |
| rows, dry-run | `COSMA_DB_NAME=cosmai … python -m scripts.migrate_fleet_source_rows` | `[측정]` exactly `trendradar` and `tubedepth` printed before/after; every other key (`endpoints`, `credentials`, `limits`, `port`, `scheme`) byte-identical between the two lines; `would migrate 2 row(s)` |
| rows, execute | same + `--execute --confirm-production` | `migrated 2 row(s)` |
| rows, idempotence | same command again | `nothing to do … migrated 0 row(s)` |
| start | `docker compose up -d cosmai-migrate cosmai-api cosmai-worker cosmai-scheduler cosmai-dashboard` | migrate `Exited`, three `Started` |

`[측정]` Before/after for the two rows (dry-run output, verbatim shape):

- `trendradar`: `hosts ["127.0.0.1"]`, `allow_loopback: true` → `hosts ["trend-radar-dashboard"]`,
  `allow_fleet: true`; `port 8000`, `scheme http`, 3 endpoints unchanged.
- `tubedepth`: `hosts ["127.0.0.1"]`, `allow_loopback: true` → `hosts ["tubedepth-api"]`,
  `allow_fleet: true`; `port 8080`, `scheme http`, `credentials [{X-API-Key, COSMA_SRC_TUBEDEPTH_API_KEY}]`
  (a key *name*), `limits {max_pages: 60}`, 2 endpoints unchanged.

## Smoke (issue #12 §7, verification criteria 2 and 3)

| Check | Evidence |
|---|---|
| migrate exits 0 | `docker inspect … .State.ExitCode` → `0`; log `{"event": "migrate.report", "applied": []}` (schema already current) |
| all four on `db-net`, no host network | `docker inspect` `NetworkMode=db-net` for api/worker/scheduler; `docker compose ps`: `cosmai-api 127.0.0.1:8100->8100/tcp`, `cosmai-dashboard 127.0.0.1:8101->80/tcp`, scheduler/worker no ports; `grep -c 'network_mode: host' docker-compose.yml` → 2, **both in comments** (the M8 history), zero on a service |
| api binds container scope, host surface loopback | api log `api.started host 0.0.0.0 port 8100`; `ss -ltnp` → listeners `127.0.0.1:8100`, `127.0.0.1:8101` only (H2 of DP-035 holds) |
| `/health` from the host | `{"status":"ok","database":"reachable","database_name":"cosmai",…}` — DB reached as `shared-postgres:5432` over `db-net` |
| dashboard | `curl -o /dev/null -w '%{http_code}' http://127.0.0.1:8101/` → `200` (H3 holds; bundle unchanged) |
| fleet names resolve inside the container | `trend-radar-dashboard` → `172.18.0.6`, `tubedepth-api` → `172.18.0.8` |
| scheduler → worker, live trend-radar over the fleet hostname | `scheduler.job_created source_id=trendradar` within one interval; worker `addon.collect.run_complete` (`pages_fetched: 2`, `items_emitted: 0` — nothing new since the last pass) then `job.transition … to_state: SUCCEEDED`, three consecutive runs |
| live tubedepth over the fleet hostname | schedule enabled once (`PUT /sources/tubedepth/schedule {"enabled":true,"interval_seconds":60}`), then restored to `enabled:false`. `[측정]` `tubedepth-api`'s own access log: **120** `GET /v1/artifacts…` → `200` from `172.18.0.15` (cosmai-worker's `db-net` address) in the window — the network path works end to end. `[측정]` The job itself ended `FAILED` / `PLATFORM_PERMANENT`: *"this source grants 60 pages per run and the collector asked for 61"* — `PAGE_LIMIT_EXCEEDED`, the collector's known budget-aware-pagination gap recorded before this issue (M4/M7 follow-on list), not a network or policy refusal. Two such failed jobs were created before the schedule was disabled. |
| policy negative control in the live image | inside `cosmai-api`, `check_resolved_addresses` under a fleet profile: `172.18.0.6 → ADMITTED`; `169.254.169.254`, `127.0.0.1`, `0.0.0.0` → `ADDRESS_RANGE_BLOCKED` |
| other services undisturbed | `docker ps`: 9 non-cosmai containers still `Up`; `shared-postgres` was **not** recreated this time (no change to its service definition) |

`[측정]` `/health` job counts after the window: `SUCCEEDED 16278`, `FAILED 6` at first read
(pre-existing 6), plus the two tubedepth budget failures above afterwards.

## Deviations and what this record does not claim

- `[확인 사실]` The tubedepth *collection* did not succeed, for a reason outside this
  issue's scope (page budget vs. collector pagination). What this record claims for
  tubedepth is exactly the network claim issue #12 makes: the adapter reaches
  `tubedepth-api:8080` through `db-net` under the new policy, authenticated, with 200s.
  The budget gap stays on the follow-on list; it is not fixed here.
- `[확인 사실]` Re-disabling the tubedepth schedule left `interval_seconds: 60` where it
  was previously `null` (the schedule API has no "clear interval" form). `enabled: false`
  is the state that matters and is restored.
- The `app`-schema cutover (stack-side track) remains separate; with cosmai on `db-net`
  it is now a database-placement change only, as DP-035 anticipated.
