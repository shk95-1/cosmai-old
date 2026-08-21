# TASK-012 — Fleet egress hole, container bind opt-in, and fleet-hostname targets

- Status: `ACCEPTED`
- Phase: P1 (post-v0.1.0, GitHub issue #12)
- Planner: orchestrator session 2026-08-21 (this packet)
- Worker: `mechanical` subagent
- Attacker: `adversarial-reviewer` subagent
- Orchestrator: same session as planner (recorded; the worker/attacker separation is the
  independence that matters here, per `docs/agent-workflow/README.md`)
- Created: 2026-08-21
- Updated: 2026-08-21

## Objective

`allow_fleet` exists as the address rule's second per-source hole with the same two-layer
discipline as `allow_loopback`; the API bind accepts a container scope only by explicit
opt-in; the two adapter manifests name fleet hostnames; an idempotent script can re-point
the registered source rows — and the whole apps test suite proves each of those claims
with positive controls, green.

## Authority and dependencies

- Project State: `docs/project-state.md` §4 (DP-035 entry)
- Accepted decisions: [DP-035](../../decisions/DP-035-fleet-egress-and-container-bind.md)
  (governs this packet), DP-008 D4, DP-031 D3 + its 2026-08-21 DP-035 addendum, DP-032
- Contracts: `addon_api` **unchanged** (DP-035 D4)
- Open Questions: none
- Owner decisions required: none — recorded in DP-035
- Required evidence or environment: `apps/.venv` (note: `uv run pytest` is broken in this
  checkout — stale venv shebangs; use `.venv/bin/python -m pytest`). The agent sandbox may
  block loopback sockets; the transport tests stand up loopback stubs, so if they fail
  with connection errors that reproduce only under the sandbox, rerun outside it and
  record that.

## Scope

### Included

Issue #12 work stages 1–6, repo side only:

1. **Policy** (`apps/domain/outbound.py`): `OutboundProfile.allow_fleet: bool = False`,
   parsed in `from_row`. `check_resolved_addresses` admits an address when
   `profile.allow_fleet` and the address is private **and not** loopback, link-local,
   multicast, reserved, or unspecified. ⚠️ Python's `ipaddress` counts `127.0.0.0/8`,
   `169.254.0.0/16`, and `0.0.0.0/8` **inside `is_private`** — a bare
   `is_private and allow_fleet` pass is the defect this packet exists to not ship. The two
   flags stay orthogonal: `allow_fleet` never admits loopback, `allow_loopback` never
   admits private. Plain-HTTP approval widens from `allow_loopback` alone to
   `allow_loopback or allow_fleet`. Module docstring's M4x Gap 1 narration updated.
2. **Transport** (`apps/domain/transport.py`): `PreparedRequest` gains
   `plain_http_scope: str = "loopback"` (`"loopback" | "fleet"`), set by `resolve` from
   the profile (`"fleet"` iff `profile.allow_fleet`). `_refuse_http_off_loopback`
   generalizes: loopback scope requires every resolved address loopback (unchanged
   behavior); fleet scope requires every resolved address loopback **or** fleet-admissible
   (same exclusions as the policy half). Belt-and-suspenders stays: both layers decide
   independently. Docstrings ("every address `send` resolved must itself be loopback")
   updated.
3. **Tests — policy** (`apps/tests/test_outbound_policy.py`): keep
   `TestLoopbackEscapeHatch` untouched. New `TestFleetEscapeHatch`, mirroring it:
   positive control (flag on → `10.0.0.5`, `172.20.0.7`, `192.168.1.9` pass); flag off →
   same addresses refused `ADDRESS_RANGE_BLOCKED`; flag on does **not** admit `127.0.0.1`,
   `169.254.169.254`, a multicast, a reserved, and `0.0.0.0`; `allow_loopback=True` alone
   does not admit a private address (orthogonality both ways); `from_row` defaults False.
   Scheme tests: http granted with `allow_fleet` alone; `plain_http_scope` comes out
   `"fleet"`/`"loopback"` as the profile says.
4. **Tests — transport** (`apps/tests/test_outbound_transport.py`): extend the
   `allow_loopback`-appearance scan pattern with an `allow_fleet` scan whose permitted set
   is exactly where this packet writes the string, including the two adapter manifests as
   the **named exceptions** DP-035 D1 records — assert the exception list is those two
   paths and no more, with the same positive control style (the scan must find
   `apps/domain/outbound.py`). Fleet-scope plain-HTTP re-check: private addresses cannot
   be stubbed on this machine, so unit-test the address judgment (refusal/None) directly
   with supplied address lists, plus a loopback-scope regression (a private address is
   still refused when scope is `"loopback"` even with `allow_fleet` claimed).
5. **Manifests** (`apps/addons/collector.trendradar.rest/{addon.toml,README.md,handler.py}`,
   `apps/addons/collector.tubedepth.rest/{addon.toml,README.md,handler.py}`):
   `hosts = ["trend-radar-dashboard"]` / `["tubedepth-api"]`; comments/README/docstring
   references to `127.0.0.1:8000` / `127.0.0.1:8080` and DP-031 D3 become the fleet
   hostnames and DP-035 D3. Document in prose (comment) that the operator-approved source
   row must carry `allow_fleet` + `scheme http`; do **not** add an `allow_fleet` key to
   `[declares]` — the parser ignores unknown keys silently and the contract is unchanged
   (DP-035 D4).
6. **Config** (`apps/platform_core/config.py` + `apps/tests/test_config.py`): new setting
   `COSMA_API_BIND_SCOPE`, validated enum `loopback` (default) | `container`. Only under
   `container` may `COSMA_API_HOST` be the unspecified address (`0.0.0.0` or `::`); any
   other non-loopback value is still refused, and under the default scope the existing
   `_loopback_host` refusal is byte-for-byte in force (no fallback). Suggested shape: keep
   `_loopback_host` for the default and use the existing `CrossCheck` mechanism or a
   scope-aware parser — worker's choice, provided the default path's behavior is proven
   unchanged by a test. Record the threat-model move (exposure boundary = compose port
   mapping) in the module header's and `_loopback_host`'s SEC-002 narration. Tests:
   `container` + `0.0.0.0` accepted (positive); default scope + `0.0.0.0` refused
   (positive control); `container` + a routable non-loopback literal (e.g. `10.0.0.5`)
   still refused; an invalid scope value refused.
7. **Row migration script** (`apps/scripts/`): an idempotent Python script (runnable as
   `python -m` or a file run with the apps venv) that connects via
   `platform_core.config.load_config` + `platform_core.db.connection`, and for the
   registered source rows whose `outbound_profile.hosts` is `["127.0.0.1"]` with port
   8000/8080 rewrites `hosts` to the fleet hostname (`trend-radar-dashboard` /
   `tubedepth-api`), replaces `allow_loopback` with `allow_fleet`, keeps `scheme` and
   everything else, and prints each row's profile before and after (M8-record `[측정]`
   style, no secrets). Second run must report nothing to do. **Do not run it against the
   live database in this packet** — a dry-run mode or running only against a test database
   is in scope; the live execution belongs to the cutover stop window.

### Excluded

- DP-035/DP-031/p0-security/project-state document edits (already on this branch).
- The stack repo (`service/stack`) — compose changes are a separate commit there.
- Executing the row migration against the live `cosmai` database.
- Dashboard changes of any kind (DP-035: the dashboard is unaffected). Rendering
  `allow_fleet` in the operator profile view is a recorded non-goal here.
- `addon_api` contract changes.

### Allowed files

- `apps/domain/outbound.py`, `apps/domain/transport.py`
- `apps/platform_core/config.py`
- `apps/tests/test_outbound_policy.py`, `apps/tests/test_outbound_transport.py`,
  `apps/tests/test_config.py`
- `apps/addons/collector.trendradar.rest/` and `apps/addons/collector.tubedepth.rest/`
  (`addon.toml`, `README.md`, `handler.py` — reference text only in `handler.py`)
- `apps/scripts/` (new script file)

### Forbidden files and material

- private evaluation inputs, answers, and scoring code
- credentials, cookies, private datasets, and raw conversations
- the live `cosmai` database's rows (read-only inspection allowed; no writes)
- everything not in Allowed files — in particular `apps/dashboard/`, `apps/addon_api/`,
  `docs/` (this packet's docs are already written), `experiments/`

## Acceptance criteria

1. Every behavior in Included 1–6 has a test, and every absence claim has a positive
   control beside it (a flag-off refusal next to every flag-on pass; a scan that finds a
   known file).
2. `169.254.169.254`, `127.0.0.1`, `224.0.0.1`, `240.0.0.1`, and `0.0.0.0` are each
   refused with `allow_fleet=True` — asserted individually.
3. The full apps suite is green: `cd apps && .venv/bin/python -m pytest tests -q`.
4. `tests/environment` (repo root) is green:
   `.venv/bin/python -m pytest tests/environment -q`.
5. `cd apps && uv run ruff check <changed .py files>` and
   `uv run mypy --strict domain/outbound.py domain/transport.py platform_core/config.py`
   (plus the new script) are clean.
6. The row script's idempotence is demonstrated (two runs, second is a no-op) against a
   test database or documented dry-run, with before/after output captured in the handoff.
7. No file outside Allowed files is changed (`git status` in the handoff).

## Verification

```sh
cd /home/user1/github_prj/Main/service/cosmai
git status --short
cd apps
.venv/bin/python -m pytest tests -q
uv run ruff check domain/outbound.py domain/transport.py platform_core/config.py scripts/
uv run mypy --strict domain/outbound.py domain/transport.py platform_core/config.py
cd ..
.venv/bin/python -m pytest tests/environment -q
```

## Stopping conditions

- Stop if an unanswered consequential direction affects the implementation.
- Stop if an accepted decision or contract conflicts with this packet.
- Stop if required permission, environment, or safe test data is unavailable.
- Stop if honoring the packet would require touching `addon_api` or the dashboard.

## Worker handoff

- Changed files:
  - `apps/domain/outbound.py` — `OutboundProfile.allow_fleet: bool = False` (+ `from_row`
    parsing); `is_fleet_admissible()` (new, exported); `check_resolved_addresses` admits
    a private/non-loopback/non-link-local/non-multicast/non-reserved/non-unspecified
    address under `allow_fleet`; `resolve`'s scheme grant widens to
    `allow_loopback or allow_fleet`; `PreparedRequest.plain_http_scope: str = "loopback"`,
    set by `resolve` to `"fleet"` iff `profile.allow_fleet`; module/docstring narration
    updated (M4x Gap 1, "Fleet and the footgun").
  - `apps/domain/transport.py` — imports `is_fleet_admissible`;
    `_refuse_http_off_loopback` reads `request.plain_http_scope` (loopback scope:
    every address must be loopback, unchanged; fleet scope: loopback OR
    fleet-admissible); docstrings updated throughout (module, `SocketTransport`,
    `_connect`).
  - `apps/platform_core/config.py` — `PlatformConfig.api_bind_scope: str` (new field);
    `_loopback_host` renamed/split into `_api_host_literal` (unconditional
    literal-IP-or-refuse) + new `CrossCheck` `_api_bind_is_permitted_for_scope`
    (loopback always permitted; unspecified address permitted only under
    `container` scope; everything else refused in every scope); new `_bind_scope`
    parser + `_BIND_SCOPES`; new `Setting("COSMA_API_BIND_SCOPE", ...,
    default="loopback")`; module docstring's SEC-002 bullet and a new "What DP-035 D2
    changes" paragraph record the threat-model move (exposure boundary = compose port
    mapping, not the host bind).
  - `apps/tests/test_outbound_policy.py` — new `TestFleetEscapeHatch` (10 tests:
    positive control for 10.0.0.5/172.20.0.7/192.168.1.9; flag-off refusal control;
    127.0.0.1/169.254.169.254/224.0.0.1/240.0.0.1/0.0.0.0 each refused individually
    under `allow_fleet=True`; both orthogonality directions; `from_row` default;
    `from_row` can state it); `TestScheme` gains
    `test_http_is_refused_without_allow_loopback_or_allow_fleet`,
    `test_http_is_granted_once_allow_fleet_is_set_instead`,
    `test_plain_http_scope_is_loopback_by_default`,
    `test_plain_http_scope_is_fleet_when_allow_fleet_is_set`.
  - `apps/tests/test_outbound_transport.py` — new `TestFleetIsOnlyReachableByFlag`
    (mirrors `TestLoopbackIsOnlyReachableByFlag`'s scan; permitted set asserted by
    equality — `apps/domain/outbound.py`, `apps/domain/transport.py`,
    `apps/tests/test_outbound_policy.py`, `apps/tests/test_outbound_transport.py`,
    the two named `addon.toml` manifests, and `apps/scripts/migrate_fleet_source_rows.py`
    — plus the file-type-reach control); the pre-existing `allow_loopback` scan's
    `permitted` set gained one entry (`apps/scripts/migrate_fleet_source_rows.py`,
    which legitimately reads the old key while migrating a row); new
    `TestFleetScopePlainHttpReCheck` (7 tests, calling `_refuse_http_off_loopback`
    directly with supplied address lists — no stub, since a private address cannot
    be stood up as a reachable listener on this machine): fleet-admissible and
    loopback both permitted under `"fleet"` scope; 169.254.169.254/224.0.0.1/
    240.0.0.1/0.0.0.0 each refused even under `"fleet"` scope; the loopback-scope
    regression (a private address refused under `"loopback"` scope regardless of
    what a profile "claims"); loopback-scope positive control; non-IP-string refusal.
  - `apps/tests/test_config.py` — new section "DP-035 D2: COSMA_API_BIND_SCOPE and
    the container-bind opt-in" (9 tests): default scope is `"loopback"`; default
    scope still refuses `0.0.0.0` (the packet's named positive control, on top of the
    pre-existing parametrized case that already covered it); `container` accepts
    both `0.0.0.0` and `::`; `container` still refuses `10.0.0.5`; `container` still
    accepts loopback; 5 invalid-scope-value cases refused (`Container`, `LOOPBACK`,
    `public`, `""`, `"0"`); an invalid scope is refused even alongside an otherwise
    valid host.
  - `apps/addons/collector.trendradar.rest/{addon.toml,README.md,handler.py}` —
    `[declares].hosts` → `["trend-radar-dashboard"]`; header/docstring/README address
    references become the fleet hostname with DP-031 D3 → DP-035 D3 citations where
    the *address* is what changed (DP-031 D3's topology/version citations elsewhere
    left alone); `[declares]` gained a prose comment documenting the required
    `allow_fleet = true` + `scheme = "http"` grant (not a `[declares]` key, per
    DP-035 D4); README gained a short "operator-approved outbound profile" section
    mirroring tubedepth's.
  - `apps/addons/collector.tubedepth.rest/{addon.toml,README.md,handler.py}` — same
    treatment; the README's JSON profile example and its surrounding prose now show
    `"hosts": ["tubedepth-api"]` / `"allow_fleet": true`; the "Live verification" and
    "Live smoke" `[측정]` sections (dated 2026-08-21, describing what was actually
    measured through the host network before this cutover) were deliberately **not**
    rewritten — see "Limitations" below.
  - `apps/scripts/migrate_fleet_source_rows.py` (new) — idempotent row-rewrite script;
    `fleet_hostname_for`/`migrated_profile` are the pure idempotence logic,
    `migrate()` prints before/after per matching row and writes only under
    `--execute`, `main()` refuses `--execute` against `COSMA_DB_NAME=cosmai` unless
    `--confirm-production` is also given.
  - `apps/scripts/__init__.py` (new) — makes the script reachable as
    `python -m scripts.migrate_fleet_source_rows` from the `apps/` venv, the same
    invocation shape `platform_core.worker`/`scheduler` use. Not named in the
    packet's "Allowed files" line item-by-item; judged in scope as the minimal
    packaging the named new script file needs to be runnable as `python -m` (the
    packet's own item 7 offers that as one of two acceptable invocation shapes) — see
    "Newly discovered questions" below.

- Commands and results (all run from `/home/user1/github_prj/Main/service/cosmai`
  unless noted; `uv run` is broken in this checkout as documented — `Could not
  acquire lock … Read-only file system` against `~/.cache/uv` — so every command
  below uses `.venv/bin/python -m` instead):
  - `cd apps && .venv/bin/python -m ruff check .` → **All checks passed!** (whole
    tree, not just the changed files).
  - `cd apps && .venv/bin/python -m mypy --strict .` → **Success: no issues found in
    107 source files** (whole tree; `addons/` is excluded by `pyproject.toml`'s own
    rule, unrelated to this task).
  - `cd apps && COSMA_DB_HOST=127.0.0.1 COSMA_DB_PORT=1 COSMA_DB_NAME=cosmai_test
    COSMA_DB_USER=cosmai_runtime COSMA_DB_PASSWORD_REF=COSMA_DB_RUNTIME
    .venv/bin/python -m pytest tests/test_outbound_policy.py -q` → **129 passed**
    (was 115 before this task per that file's own `TestThisModuleActuallyRunsWith
    TheDatabaseDown` docstring; +11 `TestFleetEscapeHatch` +3 `TestScheme` = +14 →
    129). Port `1` (nothing listens there) with a syntactically valid `COSMA_DB_*`
    environment is the exact invocation that file's own docstring records as its
    DB-down proof, reused here for the same reason: `_reset_schema`'s fixture
    *dependency* on `platform_config` always calls `load_config()` even when the
    session doesn't need a real connection, so `COSMA_DB_*` must be syntactically
    present even though nothing is ever dialled.
  - Same environment, `.venv/bin/python -m pytest tests/test_outbound_transport.py
    -q` → **38 passed** (real TLS/plain-HTTP stub servers stood up locally; no
    sandbox loopback-socket issue was hit — these ran clean on the first try, no
    `dangerouslyDisableSandbox` needed).
  - Same environment, `.venv/bin/python -m pytest tests/test_config.py -q` →
    **59 passed**.
  - `cd apps && .venv/bin/python -m pytest tests -q` (same environment) →
    **1168 errors, 0 passed** (before this counts collection). Every single error is
    the identical root cause — `platform_core.secrets.CredentialNotResolved:
    COSMA_SECRET_SOURCE is not set` (verified: `grep`-ing the full log for error
    class names after stripping ANSI codes returns exactly one match, this one) —
    from tests whose fixtures need a real connection (`_SESSION_NEEDS_DATABASE=True`
    once the full suite is selected) to a shared postgres this sandbox cannot reach
    (`127.0.0.1:5434` — checked directly with `/dev/tcp`, connection refused) and no
    local secret store configured. This is a pre-existing environment limitation the
    task briefing named in advance, not a regression from this task's changes — see
    "Limitations" below.
  - `.venv/bin/python -m pytest tests/environment -q` (repo root) → **87 passed**.
  - Row-migration idempotence, demonstrated without a reachable database (see
    "Limitations"): ran the script's own `fleet_hostname_for`/`migrated_profile`
    functions directly against a hand-built trend-radar-shaped and a
    tubedepth-shaped loopback profile. Run 1 output:
    `{'hosts': ['trend-radar-dashboard'], 'port': 8000, 'scheme': 'http',
    'endpoints': {...}, 'allow_fleet': True}` (loopback in → fleet hostname out,
    `allow_loopback` gone, `allow_fleet: True` present); feeding that same
    dict back into `fleet_hostname_for` for a simulated "run 2" returned `None` —
    the exact "nothing to do" condition `migrate()` reports when no row matches.
    Same result for the tubedepth-shaped profile (port 8080 →
    `tubedepth-api`/`allow_fleet`). A row shaped like neither fixed target
    (`{"hosts": ["api.example.com"], "port": 443}`) was left unmatched on both
    checks, confirming the rewrite is scoped to exactly the two fixed loopback
    shapes.
  - Production-database guard, demonstrated without any network I/O: monkeypatched
    `scripts.migrate_fleet_source_rows.connect` to raise `AssertionError` if ever
    called, then ran `main(["--execute"])` with `COSMA_DB_NAME=cosmai` and no
    `--confirm-production`. Result: exit code `1`, stderr `"refusing to write:
    COSMA_DB_NAME is 'cosmai' and --confirm-production was not given …"`, and the
    monkeypatched `connect` was never invoked — proving the guard runs strictly
    before any database connection is attempted, not merely before a write. (A
    first attempt to run this case for real via subprocess, `COSMA_DB_NAME=cosmai
    … python -m scripts.migrate_fleet_source_rows --execute`, was refused by this
    session's auto-mode command classifier before it ran at all — a correct,
    independent backstop given the command named the production database, even
    though it would have failed at `connect()` regardless since `127.0.0.1:5434` is
    unreachable here.)
  - `git status --short` → every changed/new path is inside the packet's Allowed
    files (`apps/addons/collector.{trendradar,tubedepth}.rest/{addon.toml,README.md,
    handler.py}`, `apps/domain/{outbound,transport}.py`, `apps/platform_core/config.py`,
    `apps/tests/{test_outbound_policy,test_outbound_transport,test_config}.py`,
    `apps/scripts/{__init__.py,migrate_fleet_source_rows.py}`, plus this packet file's
    own Status/handoff edit). The three docs files showing as modified
    (`docs/conventions/p0-security.md`, `docs/decisions/DP-031-p1-collector-topology.md`,
    `docs/project-state.md`) and the untracked `docs/decisions/DP-035-*.md` predate
    this work session (the packet's own "Excluded" line: "already on this branch") —
    not touched by this worker.

- Evidence locations: inline in this section above (no separate evidence file was
  created; the packet's Verification block commands and their real output are
  reproduced verbatim above rather than summarized).

- Limitations and remaining risks:
  - **The full `apps` suite could not be run green in this sandbox** — it needs a
    reachable shared postgres (`127.0.0.1:5434`, confirmed unreachable) and a
    configured local secret store (`COSMA_SECRET_SOURCE`), neither available here.
    The three test files this task actually changed, plus `tests/environment`, all
    ran green (see Commands above); the attacker or a later run with real DB access
    should re-run `cd apps && .venv/bin/python -m pytest tests -q` for full-suite
    confirmation.
  - **The row-migration script's `connect()`-based path (`migrate()` run through a
    real cursor, `main()`'s commit/rollback) was never exercised against an actual
    database** — same root cause. What was verified instead: (a) the exact
    idempotence logic (`fleet_hostname_for`/`migrated_profile`) the per-row loop
    calls, directly; (b) the production-name safety guard, with `connect` stubbed to
    prove it is never reached. Acceptance criterion 6 ("two runs [...] against a test
    database or documented dry-run") is satisfied by the dry-run/no-DB
    characterization above plus the always-print-before/after design, but not by an
    actual `psycopg` round trip — the attacker should re-run the script for real
    (`cd apps && .venv/bin/python -m scripts.migrate_fleet_source_rows` with
    `COSMA_DB_NAME` pointed at a real `cosmai_test`, then with `--execute`, then
    again to see "nothing to do") once a reachable test database is available, and
    treat this as the one genuinely unverified acceptance criterion.
  - **`collector.tubedepth.rest/README.md`'s dated `[측정]` "Live verification" and
    "Live smoke" sections were deliberately left unchanged**, even though they
    contain `127.0.0.1:8080` and `allow_loopback`: they are historical records of
    what was actually measured on 2026-08-21 through the host network, before this
    cutover. Rewriting them to say `tubedepth-api:8080`/`allow_fleet` would
    misrepresent evidence that was never taken against the fleet hostname. This is a
    judgment call within the packet's "comments/README/docstring references [...]
    become the fleet hostnames" instruction — I read that instruction as covering
    forward-looking target-address documentation, not backdated measurement
    records, and flag it here for the attacker/orchestrator to confirm or overrule.
  - `apps/scripts/__init__.py` was added even though the packet's "Allowed files"
    line names only "`apps/scripts/` (new script file)" in the singular — judged as
    the minimal packaging needed to satisfy the packet's own "runnable as `python -m`"
    option (the alternative, a bare-file `sys.path` hack to reach `apps/`'s modules
    from `apps/scripts/`, seemed like the worse mechanical choice). Flagging this as
    a place the attacker should check whether it counts as scope creep.
  - The migration script's safety rail (`--confirm-production`) and its
    `role="runtime"` connection are this worker's implementation choices, not named
    by the packet: DP-035 D3 assumes `cosmai_runtime`'s existing `UPDATE` grant on
    `cosmai.source` (verified by reading `apps/db/provision_db.sql`'s default
    privileges — no `migrator`/`SET ROLE cosmai_owner` needed for a DML update on an
    existing row) and I added the production-name refusal as defense-in-depth beyond
    what the packet required, matching this module's own house style
    (SEC-001/SEC-002's "refuse by rule rather than merely default safely").

- Newly discovered questions or blockers: none that need an owner decision — the
  two items above (the `__init__.py` addition and the tubedepth README's historical
  sections) are implementation judgment calls flagged for attacker review, not
  consequential-direction ambiguities under `AGENTS.md`'s decision-boundary rule.

## Orchestrator verification note (2026-08-21)

`[측정]` The worker could not reach the shared postgres from the sandbox; the
orchestrator re-ran the full suite outside the sandbox with the live test database:
`COSMA_SECRET_SOURCE=$HOME/.config/cosmai/env COSMA_DB_HOST=127.0.0.1
COSMA_DB_PORT=5434 COSMA_DB_NAME=cosmai_test COSMA_DB_USER=cosmai_runtime
.venv/bin/python -m pytest tests -q` → **1167 passed, 1 skipped** (63.95s). A first
attempt with `COSMA_DB_USER=cosmai_migrator` produced 338 permission errors — the
migrator is `NOINHERIT` and runtime connections must be `cosmai_runtime`; recorded so the
next session does not repeat it.

## Rework (2026-08-21, post-REVIEW-TASK-012)

Addressed R1–R5 from the coordinator's rework message, mapping to
[REVIEW-TASK-012](../reviews/REVIEW-TASK-012.md) F1/F2/F4/F5/F6. No change requested for
F3/F7/F8 (orchestrator disposition) or AC3/AC6's blocked-verification framing beyond what
re-running with real access now shows.

- Changed files (on top of the original diff):
  - `apps/tests/test_outbound_transport.py` — **R1/F1**: `.claude` added to both scans'
    `SKIPPED_PARTS` (the pre-existing `allow_loopback` scan and this task's `allow_fleet`
    scan), with the comment explaining why: the harness's `EnterWorktree` scratch
    checkouts under `.claude/worktrees/` are not this repository's own authored content,
    the same reason `.worktrees` was already skipped, and REVIEW-TASK-012 F1 measured one
    turning the un-narrowed scan red mid-review. Both scans' `permitted` sets also gained
    two entries each — `apps/scripts/migrate_fleet_source_rows.py` and the new
    `apps/tests/test_migrate_fleet_source_rows.py` — because both files legitimately name
    `allow_loopback`/`allow_fleet` (the migration script reads one and writes the other;
    its test fixtures do the same), which the scans correctly caught once written and
    needed registering rather than filtering out.
  - `apps/domain/outbound.py` — **R2/F2**: `is_fleet_admissible`'s docstring now states,
    with `[확인 사실]`/`[결정]` labels, that no CPython 3.13 address is both `is_private`
    and `is_multicast` (so the `is_multicast` exclusion is presently unreachable — the one
    mutation REVIEW-TASK-012's twelve did not kill), and that it is kept anyway as
    defence-in-depth against `ipaddress` semantics drift, the same shape this module
    already carries for `is_reserved`'s own subsumed-by-`is_private` case. No behavior
    change.
  - `apps/tests/test_outbound_policy.py` — **R3/F5**: `TestFleetEscapeHatch` gained three
    tests: `test_the_flag_admits_an_ipv4_mapped_fleet_address` (`::ffff:10.0.0.5` admitted
    with `allow_fleet=True`), `test_the_flag_does_not_admit_ipv4_mapped_blocked_addresses`
    (`::ffff:169.254.169.254` and `::ffff:127.0.0.1` each refused with the flag on, via
    `pytest.mark.parametrize`), and
    `test_the_ipv4_mapped_blocked_addresses_are_refused_with_the_flag_off_too` (the
    positive control: the same two addresses refused with no flag at all). These pin the
    CPython 3.13 `ipv4_mapped`-delegation behavior REVIEW-TASK-012 F5 measured the
    existing refusals rest on but nothing in the diff tested.
  - `apps/scripts/migrate_fleet_source_rows.py` — **R4/F6**: `FLEET_HOSTNAME_BY_PORT`
    (keyed on port alone) replaced by `FLEET_TARGETS: Mapping[str, tuple[int, str]]`
    keyed on `source_id` (`"trendradar"` → `(8000, "trend-radar-dashboard")`,
    `"tubedepth"` → `(8080, "tubedepth-api")`); `fleet_hostname_for` now takes `source_id`
    and requires both the source_id match and the shape match. New
    `shape_matches_a_known_port` helper recognises a same-shaped stranger (matching
    port/hosts, foreign source_id) so `migrate()` can name it in a printed note instead of
    passing over it in silence or (the F6(b) case) crashing with `AttributeError` on a
    non-object `outbound_profile` — `migrate()` now checks `isinstance(raw_profile,
    Mapping)` before touching it and prints a skip note for either malformed-profile or
    foreign-source_id-with-matching-shape rows. Module docstring gained a "Keyed on
    (source_id, shape)" paragraph naming F6 by number.
  - `apps/tests/test_migrate_fleet_source_rows.py` (new) — **R5/F4**: 26 tests, zero of
    which need a database except the last two. `TestFleetHostnameFor` (8): match on both
    named source_ids, non-match on wrong port/wrong host/already-migrated/foreign
    source_id with matching shape (F6)/unregistered source_id, and the positive control
    that `FLEET_TARGETS` names exactly `trendradar`/`tubedepth`. `TestShapeMatchesAKnownPort`
    (3). `TestMigratedProfile` (5): hosts repointed, `allow_loopback` removed,
    `allow_fleet` granted, every other key preserved verbatim, input not mutated.
    `TestMigrateNotesAndSkips` (8, against a hand-built stub connection/cursor — no
    database): a matching row is migrated and the `update` issued; a dry run matches but
    issues no `update`; a foreign-source_id-with-matching-shape row is skipped with a
    printed note (F6, asserted via `capsys`) and a genuinely unrelated row produces no
    note at all (the control); a non-object and a scalar `outbound_profile` are skipped
    rather than raising; a mixed batch of all four shapes migrates only the one genuine
    match; an empty row set reports "nothing to do". `TestMigrateAgainstARealDatabase`
    (2): `domain_store.register_source` inserts a trendradar-shaped row plus one unrelated
    row, `migrate()` runs twice over `domain_store.connection` — first run changes exactly
    1, second run changes 0, the unrelated row's `outbound_profile` reads back
    byte-identical both times, and the migrated row's own after-state is stable across the
    second run; a third test confirms a dry run against the real database changes nothing
    (`allow_loopback` still `True`, `hosts` still `["127.0.0.1"]` afterward).

- Commands and results (same `uv run`-is-broken caveat as before; every command below
  uses `.venv/bin/python -m`):
  - `cd apps && .venv/bin/python -m ruff check .` (whole tree) → **All checks passed!**
  - `cd apps && .venv/bin/python -m mypy --strict .` (whole tree) → **Success: no issues
    found in 108 source files** (was 107 before the rework's new test file).
  - **The shared postgres and secret store were reachable this session**, unlike the
    first pass — `~/.config/cosmai/env` and `127.0.0.1:5434` were both blocked by this
    sandbox's default restrictions (confirmed: `Path(...).is_file()` returned `False` and
    a raw `/dev/tcp` probe was refused), so every DB-touching command below was run with
    `dangerouslyDisableSandbox: true`, the documented escape hatch for a confirmed
    sandbox-caused restriction — DB-free commands (ruff, mypy, `tests/environment`, the
    non-DB slice of the new test file) ran sandboxed as usual.
  - `cd apps && COSMA_SECRET_SOURCE=$HOME/.config/cosmai/env COSMA_DB_HOST=127.0.0.1
    COSMA_DB_PORT=5434 COSMA_DB_NAME=cosmai_test COSMA_DB_USER=cosmai_runtime
    .venv/bin/python -m pytest tests/test_outbound_policy.py tests/test_outbound_transport.py
    tests/test_config.py tests/test_migrate_fleet_source_rows.py -q` (sandbox disabled) →
    **257 passed** (134 + 38 + 59 + 26). Individually: `test_outbound_policy.py` **134
    passed** (129 + 3 IPv4-mapped tests, one of which is itself a single non-parametrized
    test so the net add from R3 is 3 test functions covering 5 cases); both scans in
    `test_outbound_transport.py` pass with `.claude` skipped and the two new files
    registered as permitted exceptions; `test_config.py` **59 passed** (unchanged by this
    rework); `test_migrate_fleet_source_rows.py` **26 passed** (24 DB-free + 2 real-DB).
  - `.venv/bin/python -m pytest tests/environment -q` (repo root, sandboxed, no DB needed)
    → **87 passed**.
  - `cd apps && COSMA_SECRET_SOURCE=$HOME/.config/cosmai/env COSMA_DB_HOST=127.0.0.1
    COSMA_DB_PORT=5434 COSMA_DB_NAME=cosmai_test COSMA_DB_USER=cosmai_runtime
    .venv/bin/python -m pytest tests -q -rs` (sandbox disabled) → **1198 passed, 1
    skipped** (63.3s). The one skip is pre-existing and unrelated to this task
    (`tests/test_addon_duplicated_helpers.py:122`, a self-documented conditional skip
    about `collector.naver.datalab` being the only add-on that currently declares
    `_day_after`). **This closes REVIEW-TASK-012's AC3 blocked-verification item and F1**
    (the tree is green with the harness's own scratch worktree present, unlike the
    orchestrator's earlier `1167 passed` note taken before this rework).
  - `git status --short` → every changed/new path is inside the packet's Allowed files,
    now including `apps/tests/test_migrate_fleet_source_rows.py` (added by the
    orchestrator for this rework). `docs/agent-workflow/reviews/REVIEW-TASK-012.md` is
    untracked and is the attacker's own report, not touched by this worker.

- Evidence locations: inline above; no separate evidence file.

- Limitations and remaining risks:
  - **AC6 is now closed with a real round trip**, not merely a stub — see
    `TestMigrateAgainstARealDatabase` above and REVIEW-TASK-012 F4's own suggested repair,
    which this follows almost verbatim (fake-cursor tests for the decision logic, one
    real-database test for the round trip itself). REVIEW-TASK-012's "Required follow-up"
    item 1 ("re-run AC3 and AC6 with the shared postgres up") is now done from this
    session directly rather than deferred to a future one.
  - REVIEW-TASK-012 F3 (the address-class wording gap — TEST-NET, `198.18.0.0/15`,
    `2001:db8::/32`, `2002::/16` are all `allow_fleet`-admissible because they are
    `is_private` in CPython's `ipaddress` and DP-035 D1's prose says "the fleet's own
    bridge network" without excluding them by name) is unchanged — the coordinator's
    rework message named this as orchestrator-handled (docs/disposition), not a worker
    repair item.
  - F7 (fleet scope admits loopback over plain HTTP even without `allow_loopback` — an
    informational finding the reviewer explicitly requested no action on, since the
    composite `SocketTransport.send` still refuses via `check_resolved_addresses` first)
    and F8 (`bool(profile.get("allow_fleet", False))` treats any truthy JSON value,
    including the string `"false"`, as `True` — informational, and identical to
    `allow_loopback`'s pre-existing behavior) are both unchanged, per the coordinator's
    "no change for F3/F7/F8" instruction.
  - **[정정, O3]** The two source_ids `FLEET_TARGETS` now hard-codes (`trendradar`,
    `tubedepth`) are taken from the coordinator's rework message. `trendradar` is
    confirmed directly by `docs/p1/M8-DEPLOY-RECORD.md` itself (not by
    REVIEW-TASK-012, which does not read that file). Both values — `trendradar` and
    `tubedepth` — were separately confirmed live via PostgREST `GET /source` on
    `127.0.0.1:3002`, once by the orchestrator and independently by the attacker's
    re-review; neither is this worker's own inference from the addon-id naming
    convention, and the pairing is no longer an open assumption. If a future live row
    ever used a different source_id, this script would still skip it with a printed
    "shape matches but source_id is not registered" note rather than migrating it
    silently — the fail-safe direction F6 asked for, kept as a safety margin even
    though the current pairing is confirmed rather than merely plausible.

- Newly discovered questions or blockers: none. The `tubedepth`/`trendradar` source_id
  pairing, flagged as an open assumption in the previous rework pass, is resolved per
  O3 above — confirmed live by two independent parties rather than left for a third to
  check.

**Micro-rework closed, 2026-08-21 (attacker re-review verdict PASS, two Low findings):**
O1 — `test_outbound_transport.py`'s two appearance scans now skip only
`.claude/worktrees/` (a new `SKIPPED_PREFIXES` check, matched against relative-path
prefixes) instead of all of `.claude`, so `.claude/settings.json` stays scanned; verified
both scan classes green (5 passed), the fleet scan turning RED on a planted
`allow_fleet = true` in `.claude/settings.json`, and the plant fully reverted
(`git diff`/`sha256sum` clean). O3 — the Limitations paragraph's mis-citations fixed:
`trendradar` cites `docs/p1/M8-DEPLOY-RECORD.md` directly rather than REVIEW-TASK-012,
and both source_ids are recorded as confirmed live via PostgREST `GET /source` (orchestrator
and attacker, independently), not inferred. `ruff check .`/`mypy --strict .` (whole `apps`
tree) both clean; `test_outbound_transport.py` **38 passed**; `test_outbound_policy.py`
untouched this pass.

## Review

- Attack report: [REVIEW-TASK-012](../reviews/REVIEW-TASK-012.md)
- Result: `PASS`
- Orchestrator disposition: accepted 2026-08-21. First attack returned `BLOCKED` (8
  findings); rework repaired F1/F4/F5/F6, recorded F2 as documented defence-in-depth,
  F3 as accepted scope in DP-035's Remaining uncertainty, F7/F8 as consistent-by-design;
  the re-review returned `PASS` and its O1/O3 were closed in a final micro-rework (O2 is
  recorded as unfalsifiable-by-construction and left). Orchestrator's own final run:
  `apps` suite 1198 passed / 1 skipped against the live `cosmai_test`,
  `tests/environment` 87 passed. Residue the acceptance knowingly carries: the two
  `TestMigrateAgainstARealDatabase` tests are worker- and orchestrator-attested (they ran
  in the full suite), not attacker-executed — the attacker verified the same decision
  logic by other means against the real row shapes.
