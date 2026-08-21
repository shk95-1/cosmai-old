# DP-035 — Fleet egress and container bind: cosmai joins `db-net` properly

- Status: `ACCEPTED_FOR_POC`
- Date: 2026-08-21
- Owners: project owner (shk95)
- Owner confirmation: `CONFIRMED` — the owner authored
  [GitHub issue #12](https://github.com/slopindustries/cosmai/issues/12) on 2026-08-21,
  labeled `priority: highest`, stating "오너 결정(2026-08-21)로 최우선 개선사항" and
  prescribing D1–D3 below by name. The issue is the owner's written answer; this packet is
  its decision record, per `AGENTS.md`'s rule that a conversation is not a record.
- Related Open Questions: none opened. Interaction with roadmap candidate `RC-007`
  ([#11](https://github.com/slopindustries/cosmai/issues/11), dashboard auth) is recorded
  under Tradeoffs — D2 does **not** trigger it, and why is stated there rather than assumed.
- Affected contracts: none under `contracts/`. `addon_api` is deliberately unchanged (see
  D4).
- Affected acceptance tests: `apps/tests/test_outbound_policy.py`,
  `apps/tests/test_outbound_transport.py`, `apps/tests/test_config.py`; the
  `p0-security.md` baseline items `SEC-002`(requirement numbering) / `SEC-005` and the
  scenario-id `SEC-002` (loopback bind) they map to.

## Decision question

M8 deployed `cosmai-migrate`/`-api`/`-worker`/`-scheduler` with `network_mode: host`
(M8-DEPLOY-RECORD (a) D2), for three reasons that form one knot:

1. the outbound address rule's only hole is `allow_loopback`, so fleet targets are only
   reachable as `127.0.0.1`;
2. the registered source rows and the two committed adapter manifests carry that loopback
   literal;
3. `SEC-002` refuses a non-loopback API bind, so a bridge network with port mapping is
   impossible.

Should cosmai's containers join the stack's `db-net` bridge network properly — and if so,
what exactly is relaxed, and what stays blocked?

## Candidates

1. **Keep `network_mode: host`** (M8 status quo). Zero code change; cosmai stays outside
   the fleet's network, DB access goes through the host's published port, and the compose
   file carries a "temporary" exception with no expiry.
2. **One bundle: a second per-source address hole (`allow_fleet`), fleet hostnames in the
   profiles/manifests, and an explicit opt-in container bind** — this packet.
3. **A per-address allowlist in the profile** (e.g. `allowed_addresses: ["172.20.0.5"]`)
   instead of a range flag. Refused: bridge-network addresses are assigned dynamically, so
   the allowlist would rot on every `docker compose up` and the failure mode is a 3 AM
   collection outage, not a policy question.
4. **Terminate the policy at the compose layer only** (trust `db-net` isolation, drop the
   application-side range check for these sources). Refused: it deletes one of the two
   independent layers the outbound guard is built on, for no gain.

## Hypotheses and falsification

| Hypothesis | Falsification condition |
|---|---|
| H1: a per-source `allow_fleet` flag with the same two-layer discipline as `allow_loopback` admits fleet targets without widening anything else | a test shows the flag admitting loopback, link-local (169.254.169.254 included), multicast, reserved, or unspecified addresses; or a committed source outside the two named manifests carrying the flag |
| H2: moving the exposure boundary from process bind to compose port mapping preserves the host-side surface | `ss -ltnp` after cutover shows a cosmai listener on a non-loopback host interface |
| H3: the dashboard needs no change | the browser-served bundle fails to reach the API at `127.0.0.1:8100` after cutover |

## Evidence

- `[확인 사실]` M8-DEPLOY-RECORD (a) D2 records the host-network decision and its reasons;
  its (d) table measures the live source row: `"outbound_profile":{"port": 8000, "hosts":
  ["127.0.0.1"], ...}` for `trendradar`.
- `[확인 사실]` `apps/domain/outbound.py` docstring designs `allow_loopback` as "the one
  hole", guarded two ways (a committed-default scan and a positive refusal control);
  `apps/domain/transport.py` holds the second, DNS-time half. This packet replicates that
  structure rather than inventing a new one.
- `[확인 사실]` Python's `ipaddress` counts `127.0.0.0/8`, `169.254.0.0/16`, and
  `0.0.0.0/8` **inside** `is_private`. A naive `is_private and allow_fleet → pass` would
  therefore unlock loopback, the cloud-metadata address, and the unspecified range in the
  same breath. The implementation must exclude the still-blocked classes explicitly, and
  the tests must prove each exclusion (H1's falsification condition exists because this
  footgun is real, not hypothetical).
- `[확인 사실]` Compose service names (`trend-radar-dashboard`, `tubedepth-api`) are DNS
  aliases on `db-net`; the running containers answer to them regardless of the
  `shared-db-*-1` container names.
- `[추론]` The `app`-schema cutover on the stack side is independent: once cosmai is on
  `db-net`, that cutover is a DB placement change only.

## Decision

`[결정]` Candidate 2, as one bundle, `ACCEPTED_FOR_POC` for P1, effective with the
`platform/issue-12-fleet-egress` merge.

**D1 — a second per-source hole in the outbound address rule, named `allow_fleet`.**
`OutboundProfile` gains `allow_fleet: bool = False`, parsed by `from_row`, default off,
never set by a committed source — with exactly one recorded exception class: the two
adapter manifests this packet names (D3) document the grant their operator-approved source
rows carry (the manifest documents a request; the grant itself lives in the source row,
per DP-008 D4). The flag admits an address that is private **and not** loopback,
link-local, multicast, reserved, or unspecified. `allow_loopback` and `allow_fleet` are
orthogonal: neither opens the other's range. The guard stays two-layer
(belt-and-suspenders): policy (`check_resolved_addresses`) and transport
(`SocketTransport`) each decide independently against the addresses DNS actually returned.
Plain-HTTP approval extends from `allow_loopback` alone to `allow_loopback or
allow_fleet`; the transport-time re-check carries a `plain_http_scope` on
`PreparedRequest` (`"loopback"` | `"fleet"`, decided by `resolve` from the profile flags)
and requires every resolved address to be loopback (loopback scope) or loopback-or-fleet
(fleet scope, same exclusions as the policy half).

**D2 — SEC-002 relaxes from "loopback only" to "container bind on explicit opt-in".**
A new validated setting `COSMA_API_BIND_SCOPE` (`loopback`, the default | `container`)
gates the API bind: only under `container` does `COSMA_API_HOST` accept the unspecified
address (`0.0.0.0`/`::`); under the default, `_loopback_host`'s existing refusal stands
unchanged, with no fallback. **Threat-model note this decision records:** the exposure
boundary moves from the process bind to the compose port mapping. Host-side surface is
unchanged — `cosmai-api` publishes only `127.0.0.1:8100` — but the API becomes reachable,
unauthenticated, by every container on `db-net`. That is a deliberate, recorded widening
of the *intra-fleet* surface, accepted because every `db-net` member is operator-deployed
code from this same fleet; it is **not** host exposure beyond loopback, so `RC-007`
(dashboard auth) is not triggered — but any future decision that adds an untrusted
workload to `db-net`, or publishes the API beyond host loopback, must treat `RC-007` as a
precondition, exactly as `roadmap-candidates.md` already states for the dashboard.

**D3 — DP-031 D3's fixed adapter targets are revised to fleet hostnames.**
`http://127.0.0.1:8000/api/v1` → `http://trend-radar-dashboard:8000/api/v1` (trend-radar),
`http://127.0.0.1:8080` → `http://tubedepth-api:8080` (tubedepth). Everything else in
DP-031 D3 (versions, auth, collection design) stands. The registered source rows'
`outbound_profile` values change accordingly (`hosts`, `allow_loopback` → `allow_fleet`;
`scheme: "http"` stays), by an idempotent migration script executed in the same stop
window as the compose cutover.

**D4 — what does not change.** The SSRF posture: an add-on still names an endpoint, never
a destination; the destination is the source row's grant (DP-008 D4). Link-local
(169.254.169.254 included), multicast, reserved, and unspecified stay blocked under every
flag combination. The transport's rebinding guard (connect only to checked addresses)
stays. The dashboard is untouched (`DEFAULT_API_BASE` is a browser-side address served by
the unchanged host port mapping). The `addon_api` contract is unchanged — `[declares]`
gains no `allow_fleet` key, because the parser ignores unknown keys silently and a
silently ignored declaration is the exact failure `addon_api/manifest.py`'s own docstring
warns about; the manifests document the needed grant in prose instead.

## Rejected alternatives

Candidates 1, 3, 4 above, each with its reason. Additionally rejected: naming the flag
`allow_private` (it would read as a general RFC-1918 unlock, which is not the intent — the
grant is "this source is a fleet member", and the name should say what the operator is
approving).

## Tradeoffs and risks

- Benefits: cosmai joins the fleet's network like every other service; the compose file
  loses its one host-network exception; the `app`-schema cutover reduces to a DB change;
  DB access uses the container-native path.
- Costs: a second hole in the address rule to keep disciplined forever; an intra-fleet
  unauthenticated API surface (recorded above); one coordinated stop window for the
  cutover.
- Failure modes: the `is_private` footgun (H1); a scan/assertion gap letting the flag
  creep into committed sources; the stop window ordering (rows updated before new images
  run would break nothing — old profiles + new code keep working — but new compose +
  old rows cannot reach loopback targets from a bridge network).
- Reversibility: full. Roll back = revert the source rows (script prints before/after
  values) and revert the compose change; the code accepts both profile generations.

## Remaining uncertainty

- Whether `db-net` ever hosts a workload outside this operator's fleet — the assumption
  D2's acceptance rests on. If it does, `RC-007` fires first.
- OQ-015 (share-alike data class) is unaffected but stays live via `postgrest-cosmai`.
- `[확인 사실]` (REVIEW-TASK-012 F3) `allow_fleet`'s grant is "what CPython's
  `ipaddress.is_private` calls private, minus the named exclusions", and that set also
  contains TEST-NET (`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`),
  `198.18.0.0/15`, `2001:db8::/32`, and 6to4 `2002::/16` (which encodes an arbitrary
  IPv4 address). Inside D1's wording, outside its prose intent. Accepted as recorded
  scope rather than narrowed: the flag is a per-source operator grant on two named
  sources whose hostnames resolve through Docker's own DNS, and the two-layer guard
  still refuses every explicitly blocked class. If a fleet source ever resolves into
  one of these ranges unexpectedly, that is the falsification signal for this
  acceptance.

## Required changes

- Project State: add this packet to §4.
- Contract or schema: none (`addon_api` unchanged, D4).
- Acceptance tests: `TestFleetEscapeHatch` (policy), fleet-scope plain-HTTP re-check
  (transport), the `allow_fleet` appearance-allowlist scan with its two named manifest
  exceptions, `COSMA_API_BIND_SCOPE` config tests with positive controls.
- Migration or compatibility: `apps/scripts/` idempotent source-row migration; executed
  in the same stop window as the stack compose cutover; old rows + new code stay valid.
- Implementation handoff: task packet `TASK-012` (docs/agent-workflow/task-packets/),
  stack-repo compose change as a separate commit in that repo, smoke evidence appended to
  `docs/p1/` per issue #12's verification criteria.
- Convention: `docs/conventions/p0-security.md` §Local execution boundary and §Outbound
  amended to name this packet where the loopback-only wording was absolute.
