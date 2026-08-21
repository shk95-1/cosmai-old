# DP-031 — Narrowing the collector topology: light sources collect in-process, heavy ones stay behind adapters

- Status: `ACCEPTED_FOR_POC`
- Date: 2026-08-21
- Owners: Project owner
- Owner confirmation: `CONFIRMED (project owner, 2026-08-21, brainstorming session — docs/superpowers/specs/2026-08-21-p1-reconstruction-design.md)`
- Narrows: [DP-026](DP-026-p0-closure-scope-and-collector-topology.md) D2 (does not supersede it — DP-026's own text is unedited; it gains a one-line forward pointer to this packet in a later task, not this one)
- Related Open Questions: [OQ-010](../open-questions/OQ-010-cursor-stream-read-back.md) — `OPEN`, reopened as directly relevant by the trend-radar adapter's multi-table streams (see Remaining uncertainty)
- Affected contracts: [`PoC Contract 0.1`](../../contracts/experimental/POC-CONTRACT-0.1.md) §1 Acquisition, §6 Source policy and outbound; `CONTRACT-ADDON@1.3`; [DP-012](DP-012-independent-scraper-services.md)'s minimum service response contract
- Affected acceptance tests: none directly; changes what M4 (NAVER collectors, trend-radar and tubedepth adapters) and the M6 scheduler build against

## Decision question

DP-026 D2 recorded, for P0's closure, that "DP-012's topology binds new collectors, not the
existing three" and that collectors added after P0 closes — "which already run as independent
services" — "are integrated as thin REST adapter add-ons under DP-012's read contract." That
text binds unconditionally: every collector P1 adds takes the adapter form. The owner's P1
selection criteria (`plan.md` §1.1, distilled in
[the reconstruction spec](../superpowers/specs/2026-08-21-p1-reconstruction-design.md) §2.1 row
1.1) narrow this: a source judged light enough may be collected in-process; only a heavy,
periodic collection target goes through an external service and an adapter. Does this narrowing
hold, and if so, precisely what does it leave standing from DP-026 D2 and DP-012?

## Candidates

1. Leave DP-026 D2 unconditional: every P1 collector — NAVER included — is rebuilt as an
   external service plus adapter.
2. Narrow DP-026 D2 to a light/heavy split: NAVER's three sources are rebuilt as internal
   direct collectors; trend-radar and tubedepth are integrated as adapters. (`plan.md` §1.1)
3. Reverse DP-026 D2 entirely: no P1 collector goes through an adapter; every source,
   including trend-radar and tubedepth, is called directly in-process.

## Hypotheses and falsification

| Hypothesis | Falsification condition |
|---|---|
| H1: NAVER's three sources can be rebuilt as internal direct collectors without reopening the "merge scraper code" problem DP-012 rejected. | Rebuilding NAVER internally requires importing another service's runtime, database, or first-stage storage, rather than calling the NAVER API directly the way the archived P0 prototype already did. |
| H2: trend-radar 1.0.0 and tubedepth's release surface are live, addressable adapter targets as described. | The endpoints, auth scheme, or version the spec records do not match what the live instances actually serve when independently checked. |
| H3: Narrowing to a light/heavy split does not remove the read-only, REST-only exchange boundary DP-012 and DP-026 D4 built for the services that stay external. | An adapter for trend-radar or tubedepth needs to read a scraper database directly, or accept an arbitrary URL, to function. |

## Experiment

- Scope: no new experiment. This packet reads three already-recorded records — DP-026 D2's
  own text, DP-012's rejected Candidate 3 and accepted Candidate 2, and the reconstruction
  spec's §5 live-instance measurement — and decides what `plan.md` §1.1 changes about them.
- Environment and versions: as recorded in the cited sources; the spec's §5/§11 measurement is
  dated 2026-08-21 against the live trend-radar (1.0.0, `:8000`) and tubedepth (release
  surface, `:8080`) instances.
- Input and fixture identity: DP-026's decision text; DP-012's candidate table and minimum
  service response contract; spec §5.1–§5.3 for the two adapter targets and NAVER; `plan.md`
  §1.1 (owner's raw notes, repository root, untracked).
- Procedure: compare `plan.md` §1.1's owner selection against DP-026 D2's unconditional text,
  identify exactly what changes and what stays, and record the two adapter targets' fixed
  points from the spec's own `[측정]`/`[확인 사실]` lines rather than re-deriving them.
- Known limitations: this packet does not independently re-verify the live trend-radar or
  tubedepth instances; it cites the spec's §5 measurement as recorded there. The spec itself
  notes (§11) that the agent sandbox's loopback isolation refuses both connections from a
  default shell — a verification gap M4's adapter work inherits, not one this packet closes.

## Evidence

`[확인 사실]` DP-026 D2's text is unconditional: "Collectors added from here... are integrated
as thin REST adapter add-ons under DP-012's read contract." It names no exception for a source
judged light.

`[확인 사실]` DP-012 already contains the seam this packet reopens, rather than inventing one.
Its Candidate 3 — "every add-on call the original external source directly" — was rejected as
the delivery boundary only because "the team has already separated scraper operation and
first-stage storage" for the sources DP-012 was deciding about (trend-radar and `yt-scrapper`).
Candidate 3's rejection is not phrased as barring a source for which no such separation exists.

`[확인 사실]` The NAVER collectors were never covered by that same separation. DP-012's closing
paragraph on "the Naver collector owned by the Cosmai delivery/backend team" describes only a
*plan* for an independent Naver collection service plus adapter, and records the direct
`collector.naver.blog` prototype as "evidence and reference code until its P0 disposition is
recorded." DP-026 D2 recorded that disposition as `ARCHIVE_REFERENCE_ONLY`, not as a live
external service. No independent NAVER collection service was ever built.

`[결정]` (`plan.md` §1.1) The owner's selection: "naver api는 가볍다고 판단하여 수집기 내부에서
구현하도록 함. 유튜브 대량처리처럼, 대량의 처리가 예상되지 않는다면 내부 수집기를 직접 구현할
수 있도록 함. 무거운 주기적 수집기는 외부 구현 후 외부 수집기와 api로 데이터 교환." — NAVER is
judged light and moves to an internal direct collector; a source not expected to need
large-scale processing may be built as an internal direct collector; a heavy periodic collector
stays external, exchanging data through an API.

`[측정]` The reconstruction spec (§5.1–§5.2, dated 2026-08-21) records the two adapter targets'
fixed points, cited here as recorded rather than independently re-verified: trend-radar 1.0.0
serves `http://127.0.0.1:8000/api/v1` unauthenticated, with no delta or cursor export — only
exact-match filtering on primary-key columns within a time bucket; tubedepth's live instance
serves the `release/2026-08-21-postgres-cutover` (`5bce7f6`) route surface
(`/v1/artifacts/{digest}`, `/v1/control`, `/v1/jobs/batch`) behind `X-API-Key`, with its version
string (`0.1.0`) unrefreshed against the running release code, and a 30-day artifact retention
window.

`[확인 사실]` The spec §11 records both services as running on 2026-08-21 (`[측정]` trend-radar
`:8000`, tubedepth `:8080`, with PostgreSQL listening on `:5432`/`:5433`) and separately records
(`[확인 사실]`) that "the agent sandbox's loopback isolation refuses both connections from a
default shell" — verification against the live instances needs local network access granted at
M4, not assumed here.

## Decision

`[결정]` **D1 — DP-026 D2 is narrowed, not superseded.** For P1: a source judged light —
expected volume that does not require external, service-owned first-stage storage — is
collected by an internal direct collector inside COSMAI. A source that is a heavy, periodic
collection target continues to run as an independent external service, integrated through a
thin REST adapter add-on under DP-012's read contract. DP-026 D2's text stands as written for
P0's closure; this packet records what P1 does differently, and DP-026 gains a one-line forward
pointer to this packet in a later task so a reader following DP-026 lands here.

`[결정]` **D2 — NAVER's three sources (blog, DataLab search-trend, DataLab shopping-insight) are
rebuilt as internal direct collectors**, calling the NAVER APIs the way the archived prototype
did. P0's three NAVER collectors keep their `ARCHIVE_REFERENCE_ONLY` disposition from DP-026
D2 — they are reference and evidence, not an import dependency; P1 writes new code against the
same source APIs rather than importing the archived add-ons.

`[결정]` **D3 — Two adapter targets are fixed for P1: trend-radar 1.0.0**
(`http://127.0.0.1:8000/api/v1`, unauthenticated, time-bucket-plus-primary-key exact-match
collection) **and tubedepth** (`http://127.0.0.1:8080`, `X-API-Key`, incremental collection over
the artifacts path). tubedepth's reference point is `release/2026-08-21-postgres-cutover` =
`5bce7f6`; **if a new release tag appears during the work, the adapter switches to that tag.**
`plan.md`'s "0.1.0" is the owner's stated error — 1.0.0 was intended, matching trend-radar's own
release; tubedepth's version string is separately unrefreshed against its running release code
(spec §5.2). `[측정]` (as recorded in the spec, 2026-08-21) the live tubedepth instance serves
release-only routes.

`[결정]` **D4 — Data exchange with either adapter target is REST-API-only**; direct reads of a
scraper's database remain refused (DP-012 preserved). Collection scheduling is COSMAI's own: the
P1 scheduler (spec §5.5) creates a collect job on its own interval, and that job reads whatever
the external service's REST export currently holds. This is not a request to the external
service to collect anything new — that direction of write is `RC-006`, registered and not
adopted here.

## Rejected alternatives

- **Candidate 1 (leave DP-026 D2 unconditional).** Rejected: the owner's `plan.md` §1.1 answer
  is explicit that NAVER should not carry an adapter seam it does not need, and DP-012's own
  Candidate 3 rejection already left the door open for a source without a separated external
  service — NAVER is that source.
- **Candidate 3 (reverse DP-026 D2 entirely, no adapters at all).** Rejected: trend-radar and
  tubedepth are already running as independent services with their own first-stage storage,
  which is exactly the condition DP-012's Candidate 2 answered and DP-026 D2 confirmed.
  Discarding the adapter for those two would re-litigate a decision the owner did not revisit —
  `plan.md` §1.1 keeps "heavy periodic collector: external implementation, data exchange via
  API."

## Tradeoffs and risks

- Benefits: NAVER's three collectors drop a network hop and a second storage layer they never
  needed a scraper service for; the topology now matches which sources actually run as
  separated external services, rather than binding every future source to the same shape by
  default.
- Costs: P1 now carries three collector seams instead of DP-026 D3's two — internal direct
  collector, adapter, and (per DP-026 D3) the private-network egress precondition the adapter's
  own outbound guard still needs. DP-026 D3 already named "the add-on surface does not
  shrink — it grows" as the hybrid's cost; this packet adds a third shape to that surface rather
  than removing one. This DP does not itself implement or re-verify the outbound guard for the
  two adapters — that guard's reduced enforcement level is `SR-001`/`SR-004`'s registered
  question, not this packet's.
- Failure modes: "light" and "heavy" are the owner's judgment call (`plan.md` §1.1: "대량의
  처리가 예상되지 않는다면"), not a measured threshold. Nothing in this packet or its evidence
  measures NAVER's actual request volume against its quota — DP-012's own remaining uncertainty
  already named this as unmeasured ("quota consumption was 2 of 25,000/day and 2 of
  50,000/month"). A future NAVER volume increase is not re-evaluated by this decision.
- Reversibility: high for D2 — an internal collector can be replaced by an external-service-plus-
  adapter later without touching Raw or downstream contracts, the same reversibility DP-012
  already recorded for the adapter direction. D3 is bound to whatever tag each service
  publishes; the "switch to a new release tag" clause is written as a standing instruction
  precisely because the target is expected to move during the work.

## Remaining uncertainty

- [OQ-010](../open-questions/OQ-010-cursor-stream-read-back.md) (cursor stream read-back),
  `OPEN`: trend-radar's collector plausibly needs one cursor per time-bucket table
  (`rank_snapshot`, `price_point`, `review_stats`, `review_summary`, `review_topic`), which
  would make it the first add-on that genuinely needs more than one stream. This packet fixes
  the adapter target; it does not resolve OQ-010, whose interim position (single-stream
  binding, refuse at job time otherwise) currently blocks a genuinely multi-stream add-on.
- Whether NAVER's "light" classification holds under P1's actual collection volume is not
  measured here — see Tradeoffs and risks.
- The spec's live-instance measurement is dated 2026-08-21 and is itself recorded as unverified
  from the current sandbox shell (loopback isolation). M4 adapter implementation is where that
  verification actually happens, not this packet.
- `accept_status`'s exercised subject, named as open in DP-026's own Remaining uncertainty, is
  unchanged by this packet: an adapter is still the first add-on plausibly needing it, and
  neither adapter has been written yet.

## Required changes

- Project State: record this packet alongside DP-026 D2 as the current collector-topology
  position for P1; note that DP-026 D2's own text is unedited and this packet is the narrowing
  record.
- Contract or schema: `PoC Contract 0.1` §1 and §6 gain a note in their next revision that an
  add-on's topology (internal direct collector vs. adapter) is a per-source classification, not
  a project-wide default; DP-012's minimum service response contract remains the adapter's read
  shape, unchanged.
- Acceptance tests: none by this packet. Contract tests for both adapters (fixture-based,
  runnable without the live service) and the rebuilt NAVER collectors are M4 implementation work
  (spec §10).
- Migration or compatibility: none.
- Implementation handoff: M4 builds `collector.naver.blog`, one or two NAVER DataLab collectors
  (implementer's choice per spec §5.3), `collector.trendradar.rest`, and `collector.tubedepth.rest`
  against this packet's D2–D4; the private-network egress precondition DP-026 D4 already named
  applies to the two adapters, not to NAVER's direct calls.

## 2026-08-21 addendum — D3's switch-on-release rule fires

`[확인 사실]` yt-scrapper tagged `v1.0.0` on 2026-08-21, eight commits past the `5bce7f6`
baseline this packet recorded (delta: the `watch` CLI, route-level api-reference-truth fixes,
a Docker image and compose). Per D3's own rule — "switch to whatever release tag appears" —
the tubedepth adapter's baseline is **`v1.0.0`** from this date. The owner approved recording
this at M4 planning time (2026-08-21, in session). The artifacts-feed surface the adapter
depends on (`/v1/artifacts?since` → cursor → `/v1/artifacts/{digest}`, `X-API-Key`) is
unchanged between `5bce7f6` and `v1.0.0`; M4's adapter verifies against the live instance.

## 2026-08-21 addendum — D3's fixed targets revised by DP-035 D3

`[결정]` [DP-035](DP-035-fleet-egress-and-container-bind.md) D3 (owner decision, GitHub
issue #12) revises the two literal targets D3 fixed: `http://127.0.0.1:8000/api/v1` →
`http://trend-radar-dashboard:8000/api/v1` and `http://127.0.0.1:8080` →
`http://tubedepth-api:8080` — compose service hostnames on the stack's `db-net` bridge
network, replacing the host-loopback addresses that forced `network_mode: host` in M8.
Everything else in D3 (versions, auth, collection design, the read-only contract) stands.
