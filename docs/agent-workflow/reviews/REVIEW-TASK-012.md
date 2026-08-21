# REVIEW-TASK-012 — Attack report

- Packet: [`TASK-012`](../task-packets/TASK-012-fleet-egress-and-container-bind.md) — fleet egress hole, container bind opt-in, fleet-hostname targets
- Governing decision: [`DP-035`](../../decisions/DP-035-fleet-egress-and-container-bind.md) D1–D4
- Worker revision: uncommitted working tree on `platform/issue-12-fleet-egress` (base `fb01ff2`); 15 modified files + `apps/scripts/{__init__.py,migrate_fleet_source_rows.py}` untracked
- Attacker: `adversarial-reviewer` subagent, session 2026-08-21
- Date: 2026-08-21
- Result: `BLOCKED`

> **Why `BLOCKED` and not `PASS` or `FAIL`.** Every security claim DP-035 D1/D4 makes
> survived the attacks below, including ten address forms no test in the diff picks. But two
> acceptance criteria could not be verified in this session for environmental reasons named
> in "Blocked verification" — AC3 (full apps suite green) and AC6 (row script against a real
> test database) — and `ATTACKER.md`'s own rule is "do not infer a pass from missing access
> or missing evidence". `FAIL` was considered and rejected: the one test that is red in this
> working tree (F1) is red for a reason the diff did not create, and inventing a defect to
> reach a verdict is the failure this role exists to avoid.

## Environment

- `apps/.venv`, CPython `3.13.14`; `pyproject.toml` pins `requires-python = ">=3.13"`.
- `uv run` is broken in this checkout as the packet documents; every command below uses
  `.venv/bin/python -m …`.
- Policy/transport/config tests were run with the database down, using the invocation
  `apps/tests/test_outbound_policy.py`'s own docstring records:
  `COSMA_DB_HOST=127.0.0.1 COSMA_DB_PORT=1 COSMA_DB_NAME=cosmai_test COSMA_DB_USER=cosmai_runtime COSMA_DB_PASSWORD_REF=COSMA_DB_RUNTIME`.
  Referred to below as **[DB-DOWN ENV]**.
- Loopback sockets work in this sandbox (`test_outbound_transport.py`'s real stub servers
  ran clean), so the failures in "Blocked verification" are not a loopback restriction.

## Reproduced worker evidence

| Claim | Command or procedure | Observed result | Evidence |
|---|---|---|---|
| The three changed test files are green | `cd apps && [DB-DOWN ENV] .venv/bin/python -m pytest tests/test_outbound_policy.py tests/test_outbound_transport.py tests/test_config.py -q` | `226 passed in 12.15s` (= 129 + 38 + 59, matching the handoff) | reproduced |
| `tests/environment` is green (AC4) | `.venv/bin/python -m pytest tests/environment -q` (repo root) | `87 passed in 0.47s` | reproduced |
| ruff clean (AC5) | `cd apps && .venv/bin/python -m ruff check domain/outbound.py domain/transport.py platform_core/config.py scripts/ tests/test_outbound_policy.py tests/test_outbound_transport.py tests/test_config.py` | `All checks passed!` | reproduced |
| mypy --strict clean (AC5) | `cd apps && .venv/bin/python -m mypy --strict domain/outbound.py domain/transport.py platform_core/config.py scripts/migrate_fleet_source_rows.py` | `Success: no issues found in 4 source files` | reproduced |
| The production-database guard runs before any connection | stubbed `scripts.migrate_fleet_source_rows.connect` to record-and-raise, drove `main()` over the 2×4 matrix of `db_name ∈ {cosmai, cosmai_test}` × `argv ∈ {[], [--execute], [--execute,--confirm-production], [--confirm-production]}` | `db=cosmai argv=['--execute'] -> returned 1; connect calls=[]`; every other combination reached `connect()` | reproduced independently (not by re-reading the worker's script) |
| Idempotence of the rewrite logic | fed a trend-radar-shaped and a tubedepth-shaped profile through `migrated_profile`, then the output back into `fleet_hostname_for` | run 1 → `{"allow_fleet": true, …, "hosts": ["trend-radar-dashboard"], …}`; run 2 → `None`; input dict not mutated | reproduced |
| Full `migrate()` loop, dry-run vs `--execute` vs second run | drove `migrate()` with a fake `psycopg` connection/cursor over three rows | dry run: 1 `select`, 0 `update`, `changed: 2`; `--execute`: 1 `select` + 2 `update … set outbound_profile = %s, updated_at = now() where source_id = %s`; second run over the migrated rows: `nothing to do: no row carries the loopback shape this script rewrites`, `changed: 0` | reproduced |
| The manifests still parse after the `hosts` change | loaded all eight `addon.toml` through `addon_api.manifest.AddonManifest.load` | `collector.trendradar.rest OK hosts=('trend-radar-dashboard',)`, `collector.tubedepth.rest OK hosts=('tubedepth-api',)`, six others unchanged | reproduced |
| The two adapters' own test files still pass | `cd apps && [DB-DOWN ENV] .venv/bin/python -m pytest tests/test_addon_collector_tubedepth.py tests/test_collector_trendradar.py tests/test_credentials.py -q` | `43 passed` | reproduced |

## Adversarial cases

### A. The address rule (DP-035 D1/D4) — attacked with addresses the tests do not pick

`[측정]` `check_resolved_addresses` and `domain.transport._refuse_http_off_loopback` called
directly, 36 address forms × {`allow_fleet`, `allow_loopback`, no flag} × {fleet scope,
loopback scope}. Every DP-035 D4 exclusion held:

| Address | Why it was chosen | `allow_fleet=True` policy | plain HTTP, `"fleet"` scope |
|---|---|---|---|
| `::1` | IPv6 loopback, absent from the tests | refuse | (loopback — admitted, see F7) |
| `::` | IPv6 unspecified, absent from the tests | refuse | refuse |
| `fe80::1` | IPv6 link-local, absent from the tests | refuse | refuse |
| `ff02::1` | IPv6 multicast, absent from the tests | refuse | refuse |
| `::ffff:169.254.169.254` | IPv4-mapped cloud metadata — the obvious bypass | **refuse** | **refuse** |
| `::ffff:127.0.0.1` | IPv4-mapped loopback | **refuse** | (loopback — admitted, F7) |
| `::ffff:0.0.0.0` | IPv4-mapped unspecified | **refuse** | **refuse** |
| `255.255.255.255` | broadcast | refuse | refuse |
| `64:ff9b::10.0.0.5`, `::10.0.0.5` | NAT64 / IPv4-compatible encodings of a private address | refuse | refuse |
| `0177.0.0.1`, `127.1` | octal / short-form loopback spellings | refuse (not parseable as an IP → `ADDRESS_RANGE_BLOCKED`) | refuse |
| `::ffff:10.0.0.5` | IPv4-mapped fleet address | admit | admit |
| `fc00::1`, `fd12:3456::5` | IPv6 ULA — the fleet range on an IPv6 bridge | admit | admit |

Reproduction (abbreviated; the full 36-row matrix is the same shape):

```sh
cd /home/user1/github_prj/Main/service/cosmai/apps && .venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from domain.outbound import OutboundProfile, check_resolved_addresses
p = OutboundProfile(hosts=('h',), endpoints={'items':'/v1/items'}, allow_fleet=True)
for a in ['::1','::','fe80::1','ff02::1','::ffff:169.254.169.254','::ffff:127.0.0.1','::ffff:0.0.0.0','255.255.255.255','64:ff9b::10.0.0.5','0177.0.0.1']:
    print(a, 'ADMIT' if check_resolved_addresses('h',[a],p) is None else 'refuse')"
```

`[확인 사실]` The IPv4-mapped forms are refused because CPython **3.13** delegates
`is_private`/`is_loopback`/`is_link_local`/`is_reserved`/`is_unspecified` to `.ipv4_mapped`
when it is not `None` (`inspect.getsource(ipaddress.IPv6Address.is_link_local.fget)` shows
the delegation). `pyproject.toml` pins `>=3.13`, so this holds — but see F5: nothing in the
diff tests it, and on ≤3.12 `IPv6Address.is_link_local` was `self in fe80::/10` only, with
`::ffff:0:0/96` sitting in `_private_networks` — i.e. `::ffff:169.254.169.254` would have
been fleet-admissible.

**Orthogonality, verified by direct call, not by reading the tests** — `allow_loopback=True`
alone on `10.0.0.5` → `refuse` (`ADDRESS_RANGE_BLOCKED`); `allow_fleet=True` alone on
`127.0.0.1` / `::1` / `::ffff:127.0.0.1` → `refuse`.

**Mixed address lists:**

| List | `allow_fleet=True` | Expected | Verdict |
|---|---|---|---|
| `["10.0.0.5","169.254.169.254"]` (either order) | refuse | refuse | ✅ |
| `["10.0.0.5","127.0.0.1"]` | refuse | refuse | ✅ |
| `["10.0.0.5","0.0.0.0"]` | refuse | refuse | ✅ |
| `["10.0.0.5","8.8.8.8"]` | **admit** (https) | admit | ✅ — the base rule is a blocklist of private ranges; a public address is admissible for any profile, unchanged since before DP-035, and the same is true of `["127.0.0.1","8.8.8.8"]` under `allow_loopback`. Over **plain HTTP** the same list is **refused** by the transport half (below). |

### B. The transport half (`plain_http_scope`)

| Case | Observed | Expected constraint | Verdict |
|---|---|---|---|
| scope `"loopback"`, address `10.0.0.5` | refuse `SCHEME_NOT_ALLOWED` | refuse | ✅ |
| scope `"fleet"`, address `8.8.8.8` (public over plain http) | **refuse** | refuse | ✅ — fleet scope is loopback-or-fleet-admissible only |
| scope `"fleet"`, list `["10.0.0.5","8.8.8.8"]` | refuse | refuse | ✅ |
| scope `"FLEET"` / `"Fleet"` / `""` / `"anything"`, address `10.0.0.5` | **refuse** in every case | fail closed on an unknown scope | ✅ |
| scope decided anywhere but `resolve`? | `grep -rn "PreparedRequest(" apps --include="*.py"` → **four** sites: `domain/outbound.py:754` (`resolve`), `domain/outbound.py:820` (`check_redirect`), and two in `tests/test_outbound_transport.py`. No production caller constructs one. | only `resolve` decides | ✅ |
| redirect path widening | `check_redirect("http://10.0.0.5:8000/v1/items", profile(allow_fleet=True, scheme="http"), hops=0)` → `Refusal SCHEME_NOT_ALLOWED` (`ALLOWED_SCHEMES = frozenset({'https'})`); the https redirect it does return carries `scheme='https' plain_http_scope='loopback'` | a redirect cannot inherit or widen the plain-HTTP grant | ✅ |

### C. Mutation testing — do these tests go red when the implementation is broken?

Each mutation applied in place with `perl -0pi -e`, the three test files run, then the file
restored from a byte-for-byte backup (tree verified with `sha256sum -c` afterwards).

| # | Mutation | Suite result | Killed? |
|---|---|---|---|
| M1 | drop `and not address.is_link_local` from `is_fleet_admissible` | `2 failed, 224 passed` (policy `…does_not_admit_the_cloud_metadata_address` + transport `[169.254.169.254]`) | ✅ |
| M2 | drop `and not address.is_loopback` | `2 failed, 224 passed` | ✅ |
| M3 | drop `and not address.is_unspecified` | `2 failed, 224 passed` | ✅ |
| M4 | drop `and not address.is_reserved` | `2 failed, 224 passed` | ✅ |
| **M5** | **drop `and not address.is_multicast`** | **`226 passed`** | ❌ **F2** |
| M6 | `plain_http_scope` always `"loopback"` | `1 failed, 225 passed` | ✅ |
| M7 | `from_row` never parses `allow_fleet` | `1 failed, 225 passed` | ✅ |
| T1 | transport ignores the scope (always fleet-admissible) | `2 failed` (incl. `…refused_under_loopback_scope`) | ✅ |
| C1 | `_api_bind_is_permitted_for_scope` always permits | `8 failed, 218 passed` | ✅ |
| C2 | the wildcard is permitted regardless of scope | `5 failed, 221 passed` | ✅ |
| C3 | `_bind_scope` accepts any value | `6 failed, 220 passed` | ✅ |
| C4 | `_api_host_literal` accepts host names | `3 failed, 223 passed` | ✅ |

### D. The scan — is the control real?

`[측정]` `allow_fleet` planted (one appended line) in four file types the scan claims to
reach, `TestFleetIsOnlyReachableByFlag` run after each, then the file restored:

| Plant | Scan result |
|---|---|
| baseline, nothing planted | `2 passed` |
| `apps/addons/collector.naver.blog/addon.toml` (a **third** add-on's manifest) | **`1 failed`** |
| `apps/db/provision.sql` | **`1 failed`** |
| `apps/dashboard/src/api/client.ts` | **`1 failed`** |
| `apps/platform_core/worker.py` | **`1 failed`** |
| a `.md` file | `2 passed` — `.md` is deliberately not in `SCANNED_SUFFIXES`, and the four `.md` occurrences of `allow_fleet` are the DP, the packet, `p0-security.md`, and `project-state.md`. A document grants nothing; the exclusion is correct. |

`[측정]` The permitted set is exact and complete:
`grep -rl allow_fleet --exclude-dir={.git,.venv,node_modules,.worktrees,.claude} .` returns
exactly the seven scanned paths in the assertion plus the four `.md` documents. The
equality assertion (rather than the loopback scan's subset) is therefore genuinely
load-bearing in both directions.

### E. The config guard (DP-035 D2)

`[측정]` `load_config` driven over 28 environment combinations:

| Case | Result |
|---|---|
| `COSMA_API_BIND_SCOPE` unset + `0.0.0.0` / `::` / `10.0.0.5` | refused |
| unset, `COSMA_API_HOST` unset | accepted, `127.0.0.1`, scope `loopback` |
| `scope=loopback` + `0.0.0.0` | refused |
| `scope=container` + `0.0.0.0` / `::` | accepted |
| `scope=container` + `10.0.0.5` / `172.17.0.2` / `0.0.0.8` | **refused** |
| `scope=container` + `::ffff:0.0.0.0` / `::ffff:0:0` / `0:0:0:0:0:0:0:0` | accepted (all are the unspecified address; `is_unspecified` delegates through `ipv4_mapped`) |
| `scope=loopback` + `::ffff:0.0.0.0` | refused |
| `scope=CONTAINER` | refused — `COSMA_API_BIND_SCOPE must be one of container, loopback, but was 'CONTAINER'` |
| `scope=" container "` / `"container\n"` | accepted — `load_config` calls `.strip()` on every stated value before parsing (pre-existing, applies to all settings; whitespace cannot smuggle a different value in) |
| `COSMA_API_HOST="0.0.0.0 "` | accepted as `0.0.0.0`, same `.strip()` — and only under `container` |
| `scope=""` | refused (`is set but empty`) |
| `host=localhost` / `example.com` / `"0"` / `"::/0"` | refused (`must be a literal IP address …`) |
| `scope=container` + `::%eth0` | accepted — a scope-qualified wildcard, i.e. narrower than `::`, not wider |
| a host whose parser rejected it + a cross-check that calls `ipaddress.ip_address` | no crash: `load_config` never writes `values[attribute]` when the parser raises, so `_api_bind_is_permitted_for_scope`'s `values.get("api_host") is None` guard fires |

**The default path is provably unchanged.** `git show HEAD:apps/platform_core/config.py`
loaded side by side with the new module and both `load_config`s driven over 32 values of
`COSMA_API_HOST` with `COSMA_API_BIND_SCOPE` unset:

```
'127.0.0.1' old=ACCEPT 127.0.0.1  new=ACCEPT 127.0.0.1
'::ffff:127.0.0.1' old=ACCEPT …   new=ACCEPT …
'0.0.0.0'   old=REFUSE            new=REFUSE
…
default-path differences: 0
```

The same technique against `domain/outbound.py` — `check_resolved_addresses` over 22
addresses × `allow_loopback ∈ {False, True}`, `resolve` over `scheme ∈ {https, http, ftp}` ×
`allow_loopback`, and three `from_row` shapes — reports
`check_resolved_addresses regressions (allow_fleet unset): 0` and `resolve regressions: 0`.
No pre-DP-035 profile changes behavior.

## Findings

### F1 — the appearance scan walks git-ignored sibling worktrees, and is red right now (severity: **Medium**, class: `implementation`)

**Claimed.** AC3: "The full apps suite is green." The orchestrator's verification note
records `1167 passed, 1 skipped`.

**Observed.** `[측정]` As of 2026-08-21 21:52 KST this working tree fails:

```sh
cd apps && [DB-DOWN ENV] .venv/bin/python -m pytest \
  "tests/test_outbound_transport.py::TestLoopbackIsOnlyReachableByFlag" \
  "tests/test_outbound_transport.py::TestFleetIsOnlyReachableByFlag" -q
# 1 failed, 4 passed
# AssertionError: allow_loopback appeared in {PosixPath('.claude/worktrees/issue-12-fleet-egress-wt/apps/domain/outbound.py'), … 12 more}
```

**Why.** `SKIPPED_PARTS = ("__pycache__", ".git", ".venv", "node_modules", ".worktrees")`
(`apps/tests/test_outbound_transport.py:579` and `:711`). The path parts of the offending
file are `('.claude', 'worktrees', 'issue-12-fleet-egress-wt', 'apps', 'domain',
'outbound.py')` — `"worktrees"` is not `".worktrees"`, so nothing skips it. A nested git
worktree does not appear in `git status` as modified content, so the scan is reading files
`git status` will never show. `.claude/worktrees/` is the harness's own default location for
`EnterWorktree`.

**Attribution, stated plainly.** `[측정]` This is the **pre-existing** `allow_loopback`
scan, not the one TASK-012 added; the directory appeared during this review (its mtime is
21:50, and this session's first `git status` did not list it). TASK-012 did not cause it.

**Why it still belongs in this report.** `[추론]` TASK-012 copies the same `SKIPPED_PARTS`
tuple into a new scan and strengthens the assertion from `<=` to `==`. The new scan passes
today only because that worktree happens to sit at `2adef78` (main v0.1.0), which predates
`allow_fleet` — `git -C .claude/worktrees/issue-12-fleet-egress-wt log --oneline -1`
confirms. A worktree carrying *this* branch — the ordinary way an agent works here — makes
`TestFleetIsOnlyReachableByFlag` fail too, and its `==` assertion cannot be satisfied by any
addition to `permitted`, because the offending paths are unbounded. A guard whose false
positives are this easy to trigger gets narrowed under pressure, which is how the real
control is lost.

### F2 — the multicast exclusion is dead code, and both multicast tests pass through a different clause (severity: **Medium**, class: `evaluation`)

**Claimed.** `is_fleet_admissible`'s exclusion list names multicast; `p0-security.md`'s new
`[결정]` bullet says multicast "계속 차단된다"; `TestFleetEscapeHatch`'s docstring lists "a
multicast address" among what is "asserted individually"; AC2 names `224.0.0.1`.

**Observed.** `[측정]` Deleting `and not address.is_multicast` from `is_fleet_admissible`
leaves the whole 226-test set green (mutation M5 above — the only surviving mutant of
twelve). The behavior claim is *true* and the address *is* refused; what is false is the
implication that the named exclusion is what refuses it.

**Why.** `[확인 사실]` No address is both `is_private` and `is_multicast` in CPython 3.13:

```sh
cd apps && .venv/bin/python -c "
import ipaddress
c4 = ipaddress.IPv4Address._constants._private_networks
c6 = ipaddress.IPv6Address._constants._private_networks
print([str(n) for n in c4 if n.overlaps(ipaddress.ip_network('224.0.0.0/4'))])
print([str(n) for n in c6 if n.overlaps(ipaddress.ip_network('ff00::/8'))])"
# []
# []
```

`224.0.0.1`, `239.255.255.250`, `232.0.0.1`, `ff02::1`, `ff05::1`, `ff3e::1` all report
`is_private False`. The `address.is_private and …` conjunct alone refuses every one of them,
so `not address.is_multicast` can never change an outcome and the two tests asserting it
would pass against an implementation that dropped the clause entirely.

**Assessment.** This is not an AC violation as literally worded (AC2 asks that `224.0.0.1`
be refused, and it is; AC1 asks for a flag-off control beside every flag-on pass, and there
is one). It is the exact "passes while proving nothing" shape the project punishes, in the
one absence assertion out of five that has no teeth. The cheap repair is a test that asserts
`is_fleet_admissible` on an address that is *both* private and the excluded class — which,
for multicast, does not exist; so the honest repair is either to delete the clause and say
in the docstring why `is_private` already covers multicast, or to keep it and record `[확인
사실]` that it is defence-in-depth against a future `ipaddress` change rather than a live
rule. Either way the current test should stop implying it proved something.

### F3 — `is_fleet_admissible` admits documentation, benchmarking, and 6to4 ranges (severity: **Low**, class: `specification`)

**Claimed.** DP-035 D1: the flag "admits an address that is private **and not** loopback,
link-local, multicast, reserved, or unspecified" — described throughout as "the fleet's own
bridge network".

**Observed.** `[측정]` Under `allow_fleet=True`, admitted by both the policy half and the
plain-HTTP fleet-scope re-check:

| Range | Address tested | What it is |
|---|---|---|
| `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24` | `192.0.2.1`, `198.51.100.1`, `203.0.113.1` | TEST-NET-1/2/3 |
| `198.18.0.0/15` | `198.18.0.1` | benchmarking |
| `2001:db8::/32` | `2001:db8::1` | IPv6 documentation |
| `2002::/16` | `2002:0a00:0005::1` | **6to4** — encodes an arbitrary IPv4 address (here `10.0.0.5`) and historically relays off-site through public 6to4 gateways |

Reproduction: the address matrix in §A, or
`.venv/bin/python -c "import ipaddress as i; a=i.ip_address('2002:0a00:0005::1'); print(a.is_private, a.is_loopback, a.is_link_local, a.is_multicast, a.is_reserved, a.is_unspecified)"`
→ `True False False False False False`.

**Assessment.** The implementation matches DP-035 D1's literal wording exactly; the gap is
between "private" as CPython defines it and "the fleet's bridge network" as the decision's
prose means it. `[추론]` Exploiting this needs an operator-approved `allow_fleet` row whose
approved hostname resolves into one of those ranges — a narrow path, since the two approved
hosts are compose service names. Recorded as a specification gap for the D1 wording, not a
defect to fix in this packet. The `2002::/16` row is the one worth an owner's eye.

### F4 — the migration script has no test at all; AC6 rests on prose (severity: **Medium**, class: `evaluation`)

**Claimed.** AC6: "The row script's idempotence is demonstrated (two runs, second is a
no-op) against a test database or documented dry-run."

**Observed.** `[측정]` `grep -rl "migrate_fleet_source_rows" apps/tests/` returns nothing.
The only occurrence of the path anywhere in `apps/tests/` is inside the two scans' `permitted`
sets. The idempotence claim is demonstrated only by the worker's ad-hoc session and by mine
(§ "Reproduced worker evidence") — nothing in the repository will notice if
`fleet_hostname_for` or `migrated_profile` stops being idempotent.

**Assessment.** `[추론]` The script's own logic is pure and trivially testable without a
database (`fleet_hostname_for`, `migrated_profile`, and `migrate()` against a fake cursor —
all three are what I exercised, in about twenty lines). An idempotence claim that will be
re-run against the production `cosmai` row during a stop window, with no committed
regression test, is the weakest evidence in this packet.

### F5 — nothing tests the IPv4-mapped forms, on which the metadata-address refusal depends (severity: **Low**, class: `assumption`)

**Claimed.** DP-035 D4: "Link-local (169.254.169.254 included) … stay blocked under every
flag combination."

**Observed.** `[측정]` `::ffff:169.254.169.254` *is* refused (§A). But no test in the diff
supplies an IPv4-mapped address anywhere, and the refusal depends entirely on CPython 3.13's
`ipv4_mapped` delegation in `IPv6Address.is_link_local` — a behavior no docstring in the diff
mentions. `apps/pyproject.toml` pins `requires-python = ">=3.13"`, so today it holds.

`[추론]` On CPython ≤3.12, `IPv6Address.is_link_local` was `self in fe80::/10` only and
`::ffff:0:0/96` sat inside `_private_networks`, which would make `::ffff:169.254.169.254`
private, non-link-local, and therefore **fleet-admissible**. The pin prevents that today; the
missing test means nothing would catch it if the pin moved or a vendored `ipaddress`
appeared.

### F6 — the row rewrite is keyed on `(hosts, port)`, not on the two source ids (severity: **Low**, class: `implementation`)

**Observed.** `[측정]` `fleet_hostname_for` matches any row whose profile has
`hosts == ["127.0.0.1"]` and `port ∈ {8000, 8080}`. Given a third row shaped that way:

```
some-other-local-api before: {"allow_loopback": true, "endpoints": {"z": "/z"}, "hosts": ["127.0.0.1"], "port": 8000, "scheme": "http"}
some-other-local-api after:  {"allow_fleet": true,  "endpoints": {"z": "/z"}, "hosts": ["trend-radar-dashboard"], "port": 8000, "scheme": "http"}
changed: 3
```

**Assessment.** This matches the packet's own item 7 wording ("rows whose
`outbound_profile.hosts` is `["127.0.0.1"]` with port 8000/8080") exactly, so it is not a
packet violation — but DP-035 D3 names two specific sources, and the script's docstring
claims "exactly those rows". The script prints every before/after pair even in a dry run, so
an operator running the dry run first will see a third row if there is one. Recorded so the
stop-window operator knows to read the dry-run output rather than the row count.

**Related, same severity.** `[측정]` `outbound_profile` is a bare `jsonb` column
(`apps/platform_core/db/migrations/0002_domain.sql:95`) with no object constraint. A row
holding a JSON array or scalar raises `AttributeError: 'list' object has no attribute 'get'`
inside `fleet_hostname_for`. `migrate()`'s `except BaseException: connection.rollback()`
means nothing is left half-written, so this aborts safely rather than corrupting — but it
aborts.

### F7 — under fleet scope the transport half admits loopback regardless of `allow_loopback` (severity: **Low / informational**, class: `specification`)

`[측정]` `_refuse_http_off_loopback(request(plain_http_scope="fleet"), ["127.0.0.1"])`
returns `None` for a profile that set `allow_fleet` but **not** `allow_loopback` — while
`check_resolved_addresses` refuses that same address for that same profile.

This is exactly what DP-035 D1 specifies ("fleet scope requires every resolved address to be
loopback **or** fleet-admissible"), and `SocketTransport.send` runs
`check_resolved_addresses` first, so the composite refuses. Recorded only because the two
modules' docstrings say the layers "each decide independently" and are "belt-and-suspenders":
for this one cell the transport belt is strictly looser than the policy belt, so it is not a
second, independent check of that case. No action requested.

### F8 — `bool(profile.get("allow_fleet", False))` grants the flag for any truthy JSON value (severity: **Low / informational**, class: `implementation`)

`[측정]` `from_row({"…", "allow_fleet": "false"})` → `allow_fleet=True`. Same for `"no"`,
`"False"`, `1`, `["x"]`. `[확인 사실]` `allow_loopback` has behaved identically since before
this packet (verified in the same run), so the new flag is *consistent* with the old one
rather than newly wrong. Recorded because the operator-facing surface for both flags is a
hand-written JSON row, and `"allow_fleet": "false"` reads as off.

## Blocked verification

`[측정]` Two acceptance criteria could not be checked in this session.

- **AC3 — the full apps suite.**
  `cd apps && COSMA_SECRET_SOURCE=$HOME/.config/cosmai/env COSMA_DB_HOST=127.0.0.1 COSMA_DB_PORT=5434 COSMA_DB_NAME=cosmai_test COSMA_DB_USER=cosmai_runtime .venv/bin/python -m pytest tests -q`
  → `1 warning, 1168 errors in 10.13s`, every one
  `platform_core.secrets.CredentialNotResolved`. Two independent causes:
  1. `~/.config/cosmai` is on this sandbox's read **deny** list, so
     `Path("~/.config/cosmai/env").exists()` returns `False` — the secret store is
     unreachable, not absent.
  2. `127.0.0.1:5434` refuses the connection. `[추론]` This is **not** a sandbox loopback
     restriction — `tests/test_outbound_transport.py` stands up and connects to real
     loopback listeners in this same sandbox and passes — so the shared postgres is simply
     not running right now.

  Per this reviewer's standing constraint I did not retry with the sandbox disabled. The
  orchestrator's own `1167 passed, 1 skipped` remains the only evidence for AC3, and F1 shows
  one test in that set is red in the tree as it stands.
- **AC6 — the row script against a real test database.** Same two causes. What I *did* verify
  without a database is listed under "Reproduced worker evidence": the pure idempotence logic,
  the full `migrate()` loop against a fake cursor (dry-run issues no `UPDATE`; `--execute`
  issues exactly two; the second run reports "nothing to do"), and the production-name guard
  with `connect` stubbed to prove it is never reached. A real `psycopg` round trip — the
  `Jsonb` adaptation, the `updated_at = now()` clause, the `cosmai_runtime` `UPDATE` grant —
  is still unexercised by anyone.

## Attacks that did not break anything

Stated because a short honest list is worth more than a padded one:

- Every DP-035 D4 exclusion held against 36 address forms, including the ten the tests do not
  pick (IPv6 loopback/unspecified/link-local/multicast, all four IPv4-mapped variants, NAT64
  and IPv4-compatible encodings, octal and short-form loopback spellings).
- Orthogonality holds in both directions, verified by direct call.
- Every mixed list containing a still-blocked class is refused, in either order.
- Fleet scope does **not** admit a public address over plain HTTP.
- An unrecognised `plain_http_scope` fails closed.
- No production code path constructs a `PreparedRequest` by hand; `check_redirect`'s is
  `scheme='https', plain_http_scope='loopback'` and `ALLOWED_SCHEMES` is https-only, so the
  redirect path cannot widen anything.
- The config default path is behaviourally identical to `HEAD` across 32 host values, with no
  fallback; `container` scope refuses every routable literal I tried.
- The `allow_fleet` scan is a real control: plants in a third add-on's `addon.toml`, a `.sql`,
  a `.ts`, and a `.py` each turn it red, and its permitted set is exact in both directions.
- Eleven of twelve mutations were killed.

## Scope and decision-boundary review

- **Allowed-file compliance:** `[측정]` `git status --porcelain` shows twelve modified files,
  all inside the packet's Allowed files, plus the three docs files and the untracked
  `DP-035` the packet's "Excluded" section states were already on the branch (I did not
  re-verify their authorship). `apps/addon_api/` — **unchanged** (DP-035 D4); the two
  `[declares]` blocks gained prose comments only, no `allow_fleet` key, and all eight
  manifests still load. `apps/dashboard/` — **unchanged**; the only `allow_fleet` reference
  near it is the existing `types.ts` entry in the *loopback* scan's permitted set, and my
  plant test confirms `.ts` is scanned, so a dashboard occurrence would be caught.
  `experiments/` — unchanged.
- **`apps/scripts/__init__.py`** (the worker's own flagged question): the packet's Allowed
  files say "`apps/scripts/` (new script file)", singular, while item 7 offers `python -m` as
  an acceptable invocation shape, which needs the package. `[추론]` In scope; the alternative
  (a `sys.path` hack) would be worse and would itself be new logic. The file contains a
  docstring and `from __future__ import annotations` and nothing else. Not a scope violation.
- **The tubedepth README's dated `[측정]` sections** (the worker's other flagged question):
  `[확인 사실]` They are labelled measurements taken through the host network on 2026-08-21,
  before the cutover. `AGENTS.md`'s evidence rules make rewriting a `[측정]` record to
  describe an environment it was not taken in a falsification of evidence, not a doc update.
  The worker's judgment is **correct** and should be endorsed rather than overruled. `.md` is
  not scanned, so the retained `allow_loopback` string breaks nothing.
- **Accepted-decision compliance:** D1's exclusion set is implemented as written and holds
  under attack (F3 is a gap in D1's *wording*, not a deviation from it). D2's relaxation is
  exactly "loopback always, unspecified only under `container`, everything else never". D3's
  hostnames appear in both manifests, both handlers, both READMEs, and the migration script.
  D4 holds: `addon_api` untouched, no `[declares]` key, redirect posture unchanged.
- **Unanswered consequential direction:** none found. F3 (`2002::/16` and the documentation
  ranges inside `allow_fleet`) is the only item that might warrant an owner note, and it does
  not block.
- **Prohibited material exposure:** none. No credential, cookie, or private dataset appears
  in the diff. The migration script prints `outbound_profile` verbatim; `credentials[].ref`
  is a key name, not a value (DP-018), which its own docstring states and which I confirmed
  against the printed output.
- **Working tree:** left byte-identical. Every mutation and plant was backed up and restored;
  `sha256sum -c` over 279 tracked source files reports no change, and `git status --porcelain`
  matches its state at the start of this review apart from this report file and the
  `.claude/worktrees/` entry described in F1, which this session did not create.

## Conclusion

`BLOCKED`.

The security substance of DP-035 D1/D2/D4 survived every attack I could construct. The
`is_private` footgun the packet exists to avoid is genuinely avoided, including for the
IPv4-mapped spellings the tests never try; the two flags are orthogonal in both directions;
the plain-HTTP scope cannot be widened by a caller, by a redirect, or by an unrecognised
scope value; the config default path is provably unchanged; the scan is a real control; and
eleven of twelve deliberate breakages turned the suite red.

What stops this from being a `PASS` is not a defect but missing evidence, and
`ATTACKER.md` forbids inferring the one from the other. AC3 and AC6 both require a reachable
database and secret store; both were unavailable to this session, for the two independent
reasons named above. On top of that, the one piece of AC3 I *could* run is red in this
working tree (F1) — for a reason the diff did not create, which is why this is `BLOCKED`
rather than `FAIL`, but a reason the diff's own new scan inherits and sharpens.

Nothing here needs the implementation changed before merge on security grounds. F2 and F4
are evidence defects — a control that cannot fail and a claim with no committed test — and
both are cheap to close.

## Required follow-up

- **New or revised packet** (small, one file each):
  1. Re-run AC3 and AC6 with the shared postgres up and the secret store readable: the full
     `apps` suite, and `scripts.migrate_fleet_source_rows` against `cosmai_test` for real
     (dry run → `--execute` → second run showing "nothing to do"). Record the output.
  2. Close F4: commit tests for `fleet_hostname_for` / `migrated_profile` / `migrate()`
     against a fake cursor — no database needed; the three cases are in this report.
  3. Close F2: either delete the unreachable `is_multicast` clause with a docstring line
     saying `is_private` already excludes every multicast address, or keep it and label it
     `[결정]` defence-in-depth — and either way stop claiming the current test proves it.
  4. Close F1: add the harness worktree path to both scans' `SKIPPED_PARTS`, or skip anything
     `git check-ignore`/`git ls-files` does not account for, so the guard stops firing on
     files that are not part of the repository's own content. Worth doing before the new
     `==` assertion meets its first sibling worktree.
- **Open Question or Decision Packet update:** optional — a one-line DP-035 note that
  `allow_fleet`'s admitted set is CPython's `is_private` minus the five named classes, and
  therefore includes TEST-NET, `198.18.0.0/15`, `2001:db8::/32`, and `2002::/16` (F3). This
  is a wording precision, not a reopened decision.
- **Project State or contract update:** none. `docs/project-state.md`'s DP-035 entry is
  accurate as written.

---

# Re-review — 2026-08-21 (post-rework)

- Trigger: coordinator rework message R1–R5, against the packet's new
  "Rework (2026-08-21, post-REVIEW-TASK-012)" subsection.
- Attacker: same `adversarial-reviewer` session as the report above.
- **Result: `PASS`** (see "Final verdict" for the one residue this pass does not cover).

## Correction to the report above

`[측정]` The first pass's "Blocked verification" section inferred that `127.0.0.1:5434`
and `127.0.0.1:3002` refused connections because "the shared postgres is simply not
running". **That inference was wrong**, and the worker's diagnosis (a sandbox
restriction) was right. Evidence gathered this pass:

```sh
docker ps --format "{{.Names}}\t{{.Status}}\t{{.Ports}}"
# shared-postgres              Up 6 hours (healthy)  127.0.0.1:5434->5432/tcp
# shared-db-postgrest-cosmai-1 Up 6 hours            0.0.0.0:3002->3000/tcp
ip -o addr show          # 1: lo  inet 127.0.0.1/8   ← lo and nothing else
echo $HTTP_PROXY         # http://…@localhost:3128
```

The sandbox runs the shell in its own network namespace whose `lo` is not the host's, so
Docker's host-loopback publications are invisible and the kernel answers `Connection
refused` rather than a permission error. My own listener started inside the namespace
answered `HTTP 200` on the same loopback, which is what made the first-pass reading look
sound and was in fact the thing that disproved it. `[추론]` "Connection refused" is
therefore **not** evidence that a service is down when the sandbox is namespaced —
recording that so the next reviewer does not repeat my mistake.

`[결정]` I did not disable the sandbox. This reviewer's operating constraints forbid it,
and a coordinator message is not the authority that changes them. Everything below was
obtained inside the sandbox — including, it turns out, the live row read the coordinator
offered as a fact to accept: **the sandbox's own HTTP proxy reaches PostgREST**, so the
`FLEET_TARGETS` question was independently answerable after all.

## Independent confirmation of the live source rows (was: relayed fact)

`[측정]` Read-only, anonymous, through the sandbox proxy — no writes, no sandbox override:

```sh
curl -s --noproxy "" --proxy "$HTTP_PROXY" \
  "http://127.0.0.1:3002/source?select=source_id,addon_id,outbound_profile"
```

`HTTP 200`, seven rows. Exactly two carry `"hosts": ["127.0.0.1"]`:

| `source_id` | `addon_id` | port | flag |
|---|---|---|---|
| `trendradar` | `collector.trendradar.rest` | 8000 | `allow_loopback: true` |
| `tubedepth` | `collector.tubedepth.rest` | 8080 | `allow_loopback: true` |

The other five are `naver.blog` / `naver.datalab` (public host `naverapihub.apigw.ntruss.com`)
and three with `outbound_profile: null`. `FLEET_TARGETS = {"trendradar": (8000,
"trend-radar-dashboard"), "tubedepth": (8080, "tubedepth-api")}` therefore matches live
reality on both halves. **The rework handoff's own flagged uncertainty — "`tubedepth` is
the reviewer's stated inference from the addon-id naming convention, not independently
confirmed by this worker against a live row" — is now closed by measurement.**

`[확인 사실]` A record-accuracy note while closing it (**O3**, severity: Low): that
sentence attributes to REVIEW-TASK-012 a reading of `docs/p1/M8-DEPLOY-RECORD.md` and an
inference about `tubedepth`'s source_id from the addon-id naming convention.
`grep -n "M8-DEPLOY\|source_id\|naming convention" docs/agent-workflow/reviews/REVIEW-TASK-012.md`
returns one line, and it is about the `update … where source_id = %s` SQL. The report makes
no claim about either source_id. The substance is moot now, but the packet's Limitations
paragraph should not stand as a citation of something the cited document does not say.

## Per-finding dispositions

### F1 — scan walked harness worktrees → **REPAIRED**

`[측정]` `.claude` added to `SKIPPED_PARTS` in both scans (identical tuples,
`("__pycache__", ".git", ".venv", "node_modules", ".worktrees", ".claude")`), and the
stray `.claude/worktrees/issue-12-fleet-egress-wt` is gone (`git worktree list` now shows
only the eleven `.worktrees/*` checkouts). Both scan classes are green:

```
BASELINE (both scans)  ->  5 passed in 8.10s
```

**The repair does not blind the scan to real content.** Re-planted one line in four real
repository locations, running both scan classes after each and restoring the file:

| Plant | Both scans |
|---|---|
| `apps/addons/collector.naver.blog/addon.toml` (`allow_fleet = true`) | `1 failed, 4 passed` |
| `apps/db/provision.sql` (`-- allow_fleet allow_loopback`) | `2 failed, 3 passed` — both scans caught it |
| `apps/dashboard/src/api/client.ts` (`// allow_fleet`) | `1 failed, 4 passed` |
| `apps/platform_core/worker.py` (`# allow_fleet`) | `1 failed, 4 passed` |

**How wide the new blind spot actually is — quantified rather than asserted.** Replaying
the scans' own filter over a synthetic path list, and cross-checking against
`git ls-files .claude`:

```
.claude/worktrees/<name>/apps/domain/outbound.py   skipped by SKIPPED_PARTS   ← the intent
.claude/settings.json                              skipped by SKIPPED_PARTS   ← newly hidden
.claude/agents/*.md                                suffix not scanned (unchanged)
.claude/hooks/pre.sh                               skipped by SKIPPED_PARTS
apps/**                                            SCANNED
```

Tracked files under `.claude/`: four, of which exactly **one** has a scanned suffix —
`.claude/settings.json`. So the repair's cost is precisely "one tracked harness-config
file is no longer scanned". `[추론]` An outbound-profile grant does not live in
`settings.json`, and the file is tracked, so any occurrence would surface in an ordinary
diff review. Acceptable; recorded as **O1** (severity: Low, no action requested) rather
than reopened, because narrowing the skip to `.claude/worktrees` instead of `.claude`
would be a strictly better repair if anyone touches this again.

`[측정]` **O2 — the repair is currently inert.** Mutation N8 (delete `.claude` from *both*
`SKIPPED_PARTS`) leaves `255 passed` — nothing under `.claude/` contains either flag today
(`grep -rl "allow_fleet\|allow_loopback" .claude/` → no matches), so no test would fail if
the repair were reverted. This is the same shape as F2's unreachable clause, and stated
here for the same reason: the entry must not read as load-bearing. Unlike F2 it is
unfalsifiable by construction — its trigger is a directory that exists only while a
harness session holds it — so no test is being asked for.

### F2 — dead multicast clause → **ACCEPTED AS RECORDED**

`[확인 사실]` `is_fleet_admissible`'s docstring now carries the `[확인 사실]`/`[결정]` pair:
that no CPython 3.13 address is both `is_private` and `is_multicast`, that deleting the
clause leaves every test green ("the one mutation REVIEW-TASK-012's twelve did not kill"),
and that it is kept as defence-in-depth against `ipaddress` drift, citing this module's
existing precedent
(`TestResolvedAddressRange.test_the_reserved_clause_is_subsumed_by_the_private_one`).
No behavior change; the clause no longer reads as load-bearing. This is one of the two
repairs the finding offered, taken as offered. Closed.

### F3 — `allow_fleet` admits TEST-NET / `198.18.0.0/15` / `2001:db8::/32` / `2002::/16` → **ACCEPTED AS RECORDED**

Orchestrator disposition, per the coordinator's message: recorded under DP-035's
*Remaining uncertainty* rather than repaired. `[측정]` Behavior re-confirmed unchanged
post-rework. No further action from this reviewer; the `2002::/16` (6to4) row remains the
one worth an owner's eye if `db-net` ever carries IPv6.

### F4 — no test for the migration script → **REPAIRED**

`[측정]` `apps/tests/test_migrate_fleet_source_rows.py` exists, 26 tests collected. The
24 DB-free ones run standalone with no database and no secret store:

```sh
cd apps && [DB-DOWN ENV] .venv/bin/python -m pytest \
  "tests/test_migrate_fleet_source_rows.py::TestFleetHostnameFor" \
  "tests/test_migrate_fleet_source_rows.py::TestShapeMatchesAKnownPort" \
  "tests/test_migrate_fleet_source_rows.py::TestMigratedProfile" \
  "tests/test_migrate_fleet_source_rows.py::TestMigrateNotesAndSkips" -q
# 24 passed in 0.02s
```

`[측정]` Selecting the **file** as a whole errors without a database (`26 errors`), because
`conftest.py`'s `_SESSION_NEEDS_DATABASE` is a per-session flag that the two
`TestMigrateAgainstARealDatabase` tests flip for the whole run. That is the project's
existing mechanism, not a defect in this file, and the handoff's "zero of which need a
database except the last two" is accurate about the tests themselves — noting it only so a
future reader who runs the file DB-free is not surprised.

**Are the new tests real?** Five mutations of the reworked script, each applied in place
and restored:

| # | Mutation | Result |
|---|---|---|
| N1 | `fleet_hostname_for` ignores `source_id` (revert F6's repair, back to port-only keying) | `4 failed, 251 passed` |
| N2 | `shape_matches_a_known_port` always `False` | `2 failed, 253 passed` |
| N3 | `migrate` drops the `isinstance(raw_profile, Mapping)` guard | `3 failed, 252 passed` |
| N4 | `migrated_profile` stops removing `allow_loopback` | `1 failed, 254 passed` |
| N5 | `FLEET_TARGETS` tubedepth port `8080` → `8081` | `3 failed, 252 passed` |

All five killed. The tests are not decorative.

### F5 — no IPv4-mapped coverage → **REPAIRED**

`[측정]` `tests/test_outbound_policy.py` is `134 passed` (was 129). Mutation kill counts on
the two exclusions the IPv4-mapped forms depend on rose from the first pass's 2 to 3, the
extra failure being the new parametrized case:

| # | Mutation | First pass | Now |
|---|---|---|---|
| N6 | drop `and not address.is_link_local` | 2 failed | **3 failed** |
| N7 | drop `and not address.is_loopback` | 2 failed | **3 failed** |

The CPython 3.13 `ipv4_mapped`-delegation behavior the metadata-address refusal rests on is
now pinned by a test rather than by measurement in a review document.

### F6 — rewrite keyed on shape alone → **REPAIRED**, verified against the live rows

`[측정]` Re-ran the exact demonstration from the first report, this time using the two
**real** profiles fetched from PostgREST above rather than hand-built stand-ins, plus the
stranger and the two malformed shapes:

```
trendradar before: {"allow_loopback": true, …, "hosts": ["127.0.0.1"], "port": 8000, …}
trendradar after:  {"allow_fleet": true,  …, "hosts": ["trend-radar-dashboard"], "port": 8000, …}
tubedepth  before: {"allow_loopback": true, "credentials": [{"header": "X-API-Key", "ref": "COSMA_SRC_TUBEDEPTH_API_KEY"}], …, "hosts": ["127.0.0.1"], "limits": {"max_pages": 60}, "port": 8080, …}
tubedepth  after:  {"allow_fleet": true,  "credentials": […unchanged…], …, "hosts": ["tubedepth-api"], "limits": {"max_pages": 60}, "port": 8080, …}
some-other-local-api skipped: outbound_profile has the loopback shape of a fixed adapter
  target, but this source_id is not one of ['trendradar', 'tubedepth'] — nothing rewritten
malformed-row skipped: outbound_profile is a list, not a JSON object — nothing rewritten
scalar-row    skipped: outbound_profile is a str,  not a JSON object — nothing rewritten
changed=2; rows actually UPDATEd = ['trendradar', 'tubedepth']
```

The first report's F6 case — a stranger on `127.0.0.1:8000` silently repointed to
`trend-radar-dashboard` — no longer reproduces; it is now named in a printed note and left
alone. F6(b), the `AttributeError` on a non-object `jsonb` profile, no longer reproduces
either, in either the list or the scalar form. Per-key check on the real tubedepth shape:
`keys removed: {'allow_loopback'}`, `keys added: {'allow_fleet'}`, and `credentials`,
`endpoints`, `limits`, `port`, `scheme` each `preserved verbatim: True`; `hosts` is the
only value changed; the input mapping is not mutated; the second pass returns `None`.
`credentials[].ref` is a secret-store key name, not a value, exactly as the script's
docstring claims — verified against the live row, not asserted.

### F7 / F8 → **ACCEPTED AS RECORDED**

Both were informational in the first report and explicitly requested no action.
`[측정]` Both re-confirmed unchanged post-rework: fleet scope still admits loopback at the
transport layer (the composite still refuses via `check_resolved_addresses` first), and
`from_row` still treats any truthy JSON value as the flag, identically to `allow_loopback`.

## Core security properties re-verified after the rework

`[측정]` `domain/outbound.py` changed (docstring only, per the diff), so the first pass's
attacks were re-run against the reworked module:

```
post-rework: addresses allow_fleet must refuse but admits -> NONE     (17 addresses)
post-rework: fleet-scope plain HTTP admits (excl. loopback) -> NONE
orthogonality: allow_loopback+10.0.0.5 -> refuse | allow_fleet+127.0.0.1 -> refuse
fleet scope + public 8.8.8.8 over http -> refuse
unknown scope 'FLEET' + 10.0.0.5 -> refuse
```

Nothing moved. `[측정]` Permitted sets are still exact: a repo-wide
`grep -rl allow_fleet` excluding the scans' own skip list returns exactly the eight
scanned-suffix paths in the assertion (plus five `.md` documents, which are not scanned).

## AC3 / AC6 — the first pass's blocked items

| | First pass | Now |
|---|---|---|
| AC4 `tests/environment` | 87 passed | `87 passed` — re-run |
| AC5 ruff / mypy | clean on 4 files | `All checks passed!` (whole tree) / `Success: no issues found in 108 source files` (was 107) — re-run |
| AC3 file-level counts | 226 | `134 + 38 + 59 = 231`, plus 26 collected in the new file = **257**, matching the handoff exactly |
| AC3 full-suite count | BLOCKED | **arithmetically reconciled**: the orchestrator's pre-rework `1167` + 5 (policy 129→134) + 26 (new file) = **1198**, the worker's reported figure. Every component of that sum is a number I measured myself. |
| AC6 decision logic | stub only | verified against the **real live profiles** (F6 above) plus 24 committed DB-free tests, all five mutations killed |
| AC6 psycopg round trip | BLOCKED | **still not executed by this reviewer** — see below |

## Final verdict

`PASS`.

All five repairs (R1–R5) do what they claim, and each was tested by trying to break it
rather than by reading it: the scans still catch real plants in four file types after the
`.claude` narrowing, and the narrowing's cost is exactly one tracked file; the F6 stranger
and the malformed-profile crash no longer reproduce against the live row shapes; five
mutations of the reworked script and two of the reworked policy module are all killed by
the new tests. The three findings left open were open by disposition (F3 to DP-035's
Remaining uncertainty, F7/F8 informational by my own report), not by omission. The core
DP-035 D1/D4 address rule was re-attacked after the rework and did not move.

**The residue this `PASS` does not cover, stated so it is not read as covered.** I did not
execute `TestMigrateAgainstARealDatabase` — the two tests that put a real `psycopg` round
trip (the `Jsonb` adaptation, `updated_at = now()`, the `cosmai_runtime` `UPDATE` grant)
behind the idempotence claim. The sandbox's network namespace puts `127.0.0.1:5434` and the
secret store out of reach, and I declined the offered override. Those two tests are
**worker-attested, not attacker-attested**. What I can say independently is that everything
they assert *about the decision logic* — which rows match, what the rewrite preserves, that
a second pass is a no-op, that a stranger and a malformed profile are skipped — is verified
here by other means and against the real production row shapes, and that the full-suite
figure reconciles exactly with counts I measured. The unverified part is the database
mechanics, not the migration's correctness.

That residue does not change the verdict, because it is not a claim the packet's acceptance
rests on alone: AC6 offers "a test database **or** a documented dry-run", and both now
exist. It is recorded because a `PASS` that quietly absorbs someone else's evidence is the
kind of pass this role exists to not write.

## Required follow-up (revised)

- Items 1–3 of the first pass's follow-up are **done** (AC3/AC6 re-run by the worker, the
  script's tests committed, the multicast clause labelled). Item 4 is **done** with the
  narrowing noted in O1.
- Optional, none blocking: narrow `SKIPPED_PARTS`'s `.claude` entry to the worktrees
  subdirectory so `.claude/settings.json` stays scanned (O1); correct the packet's
  Limitations paragraph, which cites REVIEW-TASK-012 for a source_id inference it does not
  contain and which is now settled by live measurement anyway (O3).
- For the stop-window operator: the dry run's printed output, not its row count, is the
  thing to read — a foreign row with the fixed shape now prints a skip note, and that note
  is the signal that something needs a human.
