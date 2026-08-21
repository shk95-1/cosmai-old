# Project State

- Project: Cosmai
- Version: 0.9
- Updated: 2026-08-21
- Phase: P1 — Clean Reconstruction
- Next gate: P1 charter gate (charter not yet written; until it exists, the accepted
  [P1 reconstruction plan](architecture-synthesis/P1-RECONSTRUCTION-PLAN.md)'s M1–M7
  milestones govern). M1–M7 are now built and under adversarial review repair
  (§1, "P1 M1–M7 status, 2026-08-21"); both closing acts happened on 2026-08-21: the owner
  accepted the repaired M2–M7 batch `GO` in session, and `dev` merged to `main` tagged
  `v0.1.0`.

## Delivery lifecycle

Delivery has two active stages before P1. Work packages inside a stage do not create additional lifecycle stages.

| Stage | Purpose | Entry condition | Required output | Exit condition |
|---|---|---|---|---|
| P0-A — Platform Core Construction and Verification | Build and test the source- and normalization-independent platform foundation. | Project identity, disposable-P0 lifecycle, technology constraints, evidence protocol, and safety baseline are accepted. | Executable platform core, handler-neutral job and failure evidence, platform operator instrumentation, and a reviewed P0-A gate record. | The P0-A Completion Gate records `GO` or an explicitly accepted `CONDITIONAL GO` without claiming acquisition or normalization evidence. |
| P0-B — Domain Integration, Evidence Synthesis, and Disposition | Select sources; define and implement acquisition and normalization; verify the real-data flow; decide what P1 promotes, rebuilds, archives, deletes, or carries unresolved. | P0-A gate is accepted and the bounded P0-B experiment, safety review, and timebox are recorded. | Source decisions, domain contracts, the add-on contract and host, concrete collector/importer/normalizer add-ons, real-data and failure evidence, Architecture Synthesis, disposition register, `PoC Contract 0.1`, and P1 reconstruction plan. | Every P0 Charter exit criterion is answered and the P1 Entry Gate accepts the contract, disposition, and reconstruction plan, or records an explicit blocker. |
| P1 — Clean Reconstruction | Rebuild from accepted contracts and promoted evidence rather than harden P0 code. | P0-B P1 Entry Gate is accepted. | A clean, continuously operable prototype baseline. | Defined by the future P1 charter. |

No stage advances automatically because code appears to work. Update this file and the affected artifact statuses when a gate is accepted.

`[결정]` **The P0-A Completion Gate was accepted `GO` on 2026-08-17** with no conditions, at revision `f83fe3c`. Its record, the evidence it links, and an adversarial review of every `PASS` claim are in [`experiments/integrated-p0/`](../experiments/integrated-p0/PLATFORM-CORE-GATE-2026-08-17.md). P0-A produced no acquisition or normalization evidence and the gate says so in its own words; the nine things it explicitly does not claim are the boundary P0-B inherits.

## 1. Current program goal through P0-B

First build and test a source- and normalization-independent platform core. Then, in P0-B, select one REST source exposed by an independent scraper service and one dataset, define and implement the acquisition and normalization domain, execute realistic integrated failures, and produce evidence-backed R&D opportunity cards for Korean sunscreen and toner topics. Synthesize enough evidence to write `PoC Contract 0.1` and a P1 reconstruction plan.

P0 remains disposable. P1 is reconstructed from accepted contracts and evidence rather than evolved directly from P0 implementation modules.

### Where this stands, 2026-08-19

`[측정]` **Every P0-B work package's deliverables exist, measured against the execution
plan as it stood before [DP-011](decisions/DP-011-p0b-product-and-delivery-scope.md).**
B0–B3 were complete before this date; B1's *records* (`SRC-001`, `SRC-002`, the selection matrix), B4's evidence coverage,
and all four B5 outputs were written on 2026-08-19.

| Package | State |
|---|---|
| B0 add-on layer | complete |

| B1 source exploration and selection | complete — REST real; **dataset real since 2026-08-20** ([DP-027](decisions/DP-027-dataset-standard-and-share-alike.md)), replacing the recorded structural substitution this row carried |
| B2 decision use and domain contracts | complete — folded into [`PoC Contract 0.1`](../contracts/experimental/POC-CONTRACT-0.1.md) by owner decision |
| B3 concrete implementation | complete — 3 collectors, 1 importer, 3 normalizers, dashboard |
| B4 real-data and failure evidence | complete with named gaps — [`B4-SCENARIO-COVERAGE.md`](../experiments/integrated-p0/evidence/B4-SCENARIO-COVERAGE.md) |
| B5 synthesis, disposition, P1 entry | documents written; **acceptance pending** |

`[확인 사실]` The [execution plan's starting measurement](p0-execution-plan.md#starting-measurement)
records the same packages as *not started*, because it measured what was **committed** at
`c0a266d` while this section measured the working tree of the same day. Its fourth column
carries what has since become history, and where that history still falls short of the
plan's criterion. Read the two together; neither is wrong alone.

`[확인 사실]` **[DP-011](decisions/DP-011-p0b-product-and-delivery-scope.md) and
[DP-012](decisions/DP-012-independent-scraper-services.md) were accepted the same day, on a
branch this work could not see.** They name a product scope — an evidence-backed R&D
opportunity card for sunscreen and toner, on a 2026-08-26 delivery boundary — and an
acquisition topology in which scraper runtimes and first-stage storage stay outside COSMAI.
The table above does not claim any of it, and neither does the work below.

| DP-011 / DP-012 scope | State | Where it goes |
|---|---|---|
| Opportunity card as the decision unit | not started | P1 first milestone ([DP-026](decisions/DP-026-p0-closure-scope-and-collector-topology.md) D1) |
| Sunscreen and toner canonicalization | not started | P1 first milestone |
| Deterministic trend baseline and classes | not started | P1 first milestone |
| Scraper-service REST adapter add-on | not started — the three collectors call the source directly | P1, and only for collectors added from here ([DP-026](decisions/DP-026-p0-closure-scope-and-collector-topology.md) D2) |

`[결정]` **P0 therefore closes against [`p0-charter.md`](p0-charter.md), not against DP-011.**
The charter's P0-B exit criteria contain no card, no trend class, and no product category;
DP-011 added those on top of it. The P1 Entry Gate measures the charter.

`[확인 사실]` **Two acts remain and neither is a document.** The P0 archive tag does not
exist, and the P1 Entry Gate has not been held. Both are the project owner's:
`AGENTS.md` makes commits, pushes, and tags things that happen when asked, and a gate that
accepted itself would not be a gate.

`[확인 사실]` 2026-08-21: the gate record is being prepared on `p1/entry-gate` from the
owner's recorded selection criteria; acceptance remains the owner's act.

`[결정]` **Both acts happened on 2026-08-21.** The P1 Entry Gate was held and accepted
`GO` by the project owner — the record, its adversarial review (`FAIL`, then four repair
rounds each independently re-verified), and what a `GO` knowingly accepts are in
[`P1-ENTRY-GATE-2026-08-21.md`](architecture-synthesis/P1-ENTRY-GATE-2026-08-21.md). The
`p0-archive` tag was approved at `00fdd0e`, the last pure-P0 commit, and created at merge.
Consequences: `apps/` is open for P1 reconstruction, and `SEC-006`'s waiver
([DP-023](decisions/DP-023-sec-006-waived-for-p0.md)) has expired — replaced not by
satisfaction but by [DP-034](decisions/DP-034-p1-credential-entry.md) D3's explicit,
still-unimplemented deferral (`SR-005`).

`[결정]` Until that gate is held, P0-B is **complete as work against the charter, not
started against DP-011's added product scope, and unaccepted as a stage**. The distinction
matters: `apps/` stays empty, and `SEC-006`'s waiver
([DP-023](decisions/DP-023-sec-006-waived-for-p0.md)) has not yet expired.

### P1 M1–M7 status, 2026-08-21

`[측정]` **M1–M7 are all built.** Following the P1 Entry Gate `GO` above, the seven
milestones the accepted [P1 reconstruction plan](architecture-synthesis/P1-RECONSTRUCTION-PLAN.md)
names have each run and produced a record:

| Milestone | Record | Scope |
|---|---|---|
| M1 | [`p1/M1-RECORD.md`](p1/M1-RECORD.md) | Platform core: config, jobs, secrets, connection, observability |
| M2 | [`p1/M2-RECORD.md`](p1/M2-RECORD.md) | Domain surface: sources, raw, snapshots, credentials |
| M3 | [`p1/M3-RECORD.md`](p1/M3-RECORD.md) | Add-on layer: contract, host, capability binding |
| M4 | [`p1/M4-RECORD.md`](p1/M4-RECORD.md) | Eight add-ons (5 lanes) plus the two platform gaps they named and closed |
| M5 | [`p1/M5-RECORD.md`](p1/M5-RECORD.md) | Operator dashboard (six screens) |
| M6 | [`p1/M6-RECORD.md`](p1/M6-RECORD.md) | Scheduler and streaming export |
| M7 | [`p1/M7-DEMO-RECORD.md`](p1/M7-DEMO-RECORD.md) | Sweep and end-to-end demo against the live database |

`[측정]` **Two independent adversarial reviews have run against this batch.**
[`REVIEW-M1.md`](agent-workflow/reviews/REVIEW-M1.md) reviewed M1 alone (`FAIL`, 3
blocking + 11 minor at the time; M2 onward proceeded from the repaired tree).
[`REVIEW-M2-M7.md`](agent-workflow/reviews/REVIEW-M2-M7.md) reviewed the whole M2–M7
batch (`FAIL`, 12 blocking + ~40 minor) and is the review this fix wave
([`p1/lane-reports/m7-fixwave-report.md`](p1/lane-reports/m7-fixwave-report.md), the
tracked copy — not the gitignored `.superpowers/sdd/` original) answers, finding by
finding.

`[확인 사실]` **Two acts remain before `main` and a `v0.1.0` tag, and neither is a
document.** Both are the project owner's, the same division `AGENTS.md` states for
every gate: the owner reviews the repaired tree and this fix wave's own report, then
(1) accepts `GO` on the M2–M7 batch (or returns it for further rework), and (2)
authorizes the merge to `main` and the `v0.1.0` tag. Neither has happened as of this
section's own date.

## 2. P0 product decision and long-term goal

`ACCEPTED_FOR_POC` in [DP-011](decisions/DP-011-p0b-product-and-delivery-scope.md).

Cosmai helps a cosmetics-company R&D or product-planning reviewer decide whether a canonical sunscreen- or toner-related topic deserves review, monitoring, evidence expansion, or rejection. The first decision unit is an evidence-backed R&D opportunity card, not a consumer recommendation, formula recommendation, sales forecast, or autonomous approval.

The delivery is backend- and ingestion-first. Source quality takes priority over source count; product, ingredient, topic, and evidence identity must be canonical and traceable. Deterministic trend classes precede any optional LLM explanation. Long-term product semantics and learned prediction targets remain open beyond P0.

## 2.1 Delivery control

- `[결정]` Functional freeze: **2026-08-26**.
- `[결정]` Independent verification, corrections, and handoff: **2026-08-27**.
- `[결정]` Required flow: one selected independent scraper REST service through a COSMAI adapter and one selected dataset through Raw, deduplication, sealed snapshot, canonical normalization, deterministic trend classification, evidence card, and operator inspection.
- `[결정]` Stretch only after the required flow passes: a second live channel and an evidence-citing LLM explanation renderer.
- `[결정]` Not in this delivery: AutoML, deep learning, sales prediction, broad cosmetics coverage, or access to an unapproved storefront.

The dated owners, stop rules, and acceptance evidence are in the [P0 Execution Plan](p0-execution-plan.md#delivery-window-2026-08-19-to-2026-08-27).

## 3. Artifact states

### Open Questions

Open Questions use `OPEN`, `EXPLORING`, `RESOLVED`, `DEFERRED`, and `SUPERSEDED`. Definitions and transition rules are in [Open Questions](open-questions/README.md).

### Decisions and contracts

```text
DRAFT
→ ACCEPTED_FOR_POC
→ CONTRACTED
→ STABLE
→ SUPERSEDED
```

- `DRAFT`: proposed but not accepted as a project constraint.
- `ACCEPTED_FOR_POC`: selected for P0 or P1 scope, not a permanent product commitment.
- `CONTRACTED`: versioned interface or data meaning with compatibility obligations.
- `STABLE`: repeatedly validated and not currently under challenge.
- `SUPERSEDED`: replaced by a recorded decision and migration path where required.

### Experiments

Experiments use `PLANNED`, `RUNNING`, `COMPLETED`, `INCONCLUSIVE`, and `ABORTED`. Definitions are in [Experiment Template](../experiments/EXPERIMENT-TEMPLATE.md).

Claim-level evidence labels such as `[확인 사실]` and `[가설]` are different from these decision states. Their definitions and usage rules are in [Evidence Labels](conventions/evidence-labels.md).

## 4. Accepted for P0

### Project and lifecycle

- `[결정]` Project and GitHub organization name: **Cosmai**.
- `[결정]` P0 is a disposable Architecture Discovery Prototype.
- `[결정]` P1 will be reconstructed after P0-B accepts Architecture Synthesis, `PoC Contract 0.1`, artifact disposition, and a P1 reconstruction plan.
- `[결정]` The repository is a monorepo for backend, dashboard, contracts, experiments, and tests.
- `[결정]` [DP-005](decisions/DP-005-two-part-pre-p1-execution.md) divides all pre-P1 delivery into P0-A and P0-B.
- `[결정]` [DP-008](decisions/DP-008-addon-architecture.md) makes collectors, importers, and normalizers in-repository add-ons behind a contract, superseding DP-005's P0-B order steps 4–6 and DP-006's module layout.
- `[결정]` [DP-010](decisions/DP-010-durable-work-in-the-completion-transaction.md) lets a handler enlist work into the transaction that completes its attempt, closing the gap the P0-A gate recorded first. It restates DP-008 D1's principle: `platform_core` stays **source-neutral**, not frozen.
- `[결정]` [DP-012](decisions/DP-012-independent-scraper-services.md) keeps scraper runtimes and first-stage storage outside COSMAI. COSMAI integrates their versioned export endpoints through in-repository collector adapter add-ons.
- `[결정]` [DP-018](decisions/DP-018-credential-parts-and-attachment.md) makes a credential a set of named parts, each a secret-store key name filling one **protected** header, declared in the source's operator-approved outbound profile. Resolves OQ-009 for P0-B.
- `[결정]` [DP-019](decisions/DP-019-normalized-schema-0-1-and-results.md) fixes `Normalized Schema 0.1`, the `normalized_result` table, and what a snapshot selects. It also records the **provisional decision use** §2 requires before a concrete normalizer exists.
- `[결정]` [DP-020](decisions/DP-020-request-method-and-body.md) puts the request method on the approved profile and the request body with the add-on, and bumps `addon_api` to contract 1.1. Two of the three selected NAVER endpoints are `POST` with a JSON body and were unreachable without it.
- `[결정]` [DP-021](decisions/DP-021-schema-0-2-trend-points.md) makes Schema 0.2 a discriminated union on `record_type` so a document and a trend point can share one table.
- `[결정]` [DP-025](decisions/DP-025-two-branch-record-reconciliation.md) reconciles the two decision records that grew from `c0a266d` without seeing each other: the published numbers stand, the P0-B packets moved to DP-018–DP-024 and OQ-013–OQ-014, OQ-014 closes into DP-012 carrying its measurement as falsification input, and the P0-B completion claim states the plan it is measured against.
- `[결정]` [DP-026](decisions/DP-026-p0-closure-scope-and-collector-topology.md) closes P0 against `p0-charter.md` rather than DP-011, moving DP-011's product scope to P1's first milestone; keeps the three NAVER collectors calling their source directly as `ARCHIVE_REFERENCE_ONLY`, which is the P0 disposition DP-012 was waiting for; and binds DP-012's independent-service-plus-adapter topology to collectors added from here. The result is a hybrid, and P1 carries both seams.
- `[결정]` [DP-027](decisions/DP-027-dataset-standard-and-share-alike.md) reads the charter's "one dataset" as category-independent — sunscreen and toner entered through DP-011, which DP-026 moved to P1 — and selects Open Beauty Facts as P0's dataset source at `CONDITIONAL GO`. `[측정]` Zero Korean sunscreen and zero Korean toner rows, so **P0 gains no product-relevant dataset evidence**, and ODbL's share-alike attaches on first publication as an obligation P1 inherits.
- `[결정]` [DP-028](decisions/DP-028-schema-0-3-product-records.md) adds `product` to the schema's
  discriminated union as `Normalized Schema 0.3`, because DP-027's selected dataset produces rows
  that fit neither contracted type — the case [DP-021](decisions/DP-021-schema-0-2-trend-points.md)'s
  own falsification table named. Additive: 0.2 records stay valid, no existing normalizer bumps, no
  migration. The body carries identity, name, brand tags, an observation time, and whether ingredient
  text was supplied; it decides nothing about the product, which stays P1's under DP-026.
  `[확인 사실]` Decided and **not yet implemented** — no add-on emits a `product` record.
- `[결정]` [DP-029](decisions/DP-029-p1-snapshot-identity.md) fixes P1 snapshot identity: a
  snapshot is materialized at seal (D1), a same-`item_key` tie is broken by a monotonic
  `raw_item.seq` (D2), and a manifest orders members by bytewise `item_key` comparison
  independent of collation (D3); the erasure obligation stays undesigned and is routed to
  `SR-003` (D4). Resolves [OQ-004](open-questions/OQ-004-snapshot-boundary.md); D2 and D3 are
  the repairs §5's materialized-snapshot hypothesis paragraph records as open gaps.
- `[결정]` [DP-030](decisions/DP-030-p1-normalization-scope.md) scopes P1 normalization:
  excludes byte-identical determinism from the contract, keeping normalization-time metadata
  instead (D1); makes per-record fault tolerance — missing-value substitution plus a
  `normalize_error` note — a contract requirement (D2); drops rule-based quality judgment,
  not carrying `normalizer.rule.baseline` forward (D3) — the decision §5's rule-baseline
  hypothesis paragraph now points to; inherits `Normalized Schema 0.3`, routing new
  `record_type`s to [`RC-005`](roadmap-candidates.md) (D4) — the decision §5's schema
  hypothesis paragraph now points to; and does not require the host to guarantee member order
  (D5).
- `[결정]` [DP-031](decisions/DP-031-p1-collector-topology.md) narrows
  [DP-026](decisions/DP-026-p0-closure-scope-and-collector-topology.md) D2 for P1 without
  superseding it: NAVER's three sources are rebuilt as internal direct collectors (D2), while
  trend-radar and tubedepth stay behind thin REST adapters under DP-012's read contract (D3),
  with all exchange REST-API-only and collection scheduling owned by COSMAI's own scheduler
  (D4).
- `[결정]` [DP-032](decisions/DP-032-p1-database-placement.md) places P1 on the shared
  PostgreSQL server as its own dedicated database `cosmai`, not a schema partition, restating
  the shared-server operating rules at the database-ownership level (D1); drafts a
  16-connection budget (D2); keeps psycopg3 direct plus a copied-and-adapted SQL-file migrator
  over an ORM (D3); and moves DB credentials into the secret file as `COSMA_DB_*` keys (D4),
  recording the decision that addresses the authenticated-access gap
  [DP-006](decisions/DP-006-p0a-platform-foundation.md) D2 named for P0-B/P1 to challenge —
  the evidence itself (a working authenticated connection, negative tests) is M1 provisioning
  and testing work, not produced by this packet. (`[확인 사실]` corrected 2026-08-21 — an
  earlier revision of this line said "closing," which claimed evidence this packet does not
  produce.) `COSMA_DB_*` is a second key family outside `secret-setup.md`'s
  `COSMA_SRC_<SOURCE_ID>_<PURPOSE>` naming rule, held for a connection pool's lifetime rather
  than a single request's — see DP-032 D4 for the recorded analysis of what that does and does
  not satisfy of `secret-setup.md` invariant 2.
- `[결정]` [DP-033](decisions/DP-033-p1-operator-surface.md) widens the P1 operator surface to
  six dashboard screens (D1); reverses P0-B's Raw-payload refusal for the local operator on
  the data-browser screen (D2); fixes scope-filtered, streaming Raw and normalized-result
  downloads (D3); adopts MUI, React Router, and TanStack Query, declined for P0-A by DP-006 D6
  (D4); and puts collection on a schedule while normalization stays operator-triggered, with an
  optional schedule (D5) (`[확인 사실]` corrected 2026-08-21 — an earlier revision of this line
  said "not normalization," which read as an outright exclusion the decision does not make) — the
  same scheduler-creates-`collect`-job mechanism
  [DP-031](decisions/DP-031-p1-collector-topology.md) D4 already fixes for the two adapters.
  Partially answers
  [OQ-005](open-questions/OQ-005-operations-contract.md) (screen set, export shape) and leaves
  [OQ-008](open-questions/OQ-008-operator-reexecution-authority.md) explicitly open.
- `[결정]` [DP-034](decisions/DP-034-p1-credential-entry.md) lets the collector-domain
  dashboard screen write a credential once through a write-only path, never re-displayed or
  logged (D1); scopes that relaxation to exactly one input request's write path, leaving
  `secret-setup.md`'s other invariants unchanged (D2); and moves `SEC-006`, redirect defense,
  and enforcement-level items into
  [`security-recommendations.md`](conventions/security-recommendations.md) as an independent
  P1-scope decision, formally ending [DP-023](decisions/DP-023-sec-006-waived-for-p0.md)'s
  waiver at this gate rather than extending it (D3). Narrows
  [OQ-007](open-questions/OQ-007-credential-scope.md)'s dashboard/API write side;
  worker-side credential-resolution scope stays open.
- `[결정]` [DP-035](decisions/DP-035-fleet-egress-and-container-bind.md) joins cosmai's
  containers to the stack's `db-net` bridge network as one bundle (owner decision
  2026-08-21, GitHub issue #12, highest priority): a second per-source address-rule hole
  `allow_fleet` with the same two-layer discipline as `allow_loopback` (D1); SEC-002's
  bind guard relaxed to an explicit `COSMA_API_BIND_SCOPE=container` opt-in, the exposure
  boundary moving to the compose port mapping while the host surface stays loopback (D2);
  DP-031 D3's fixed adapter targets revised from loopback literals to fleet hostnames
  (`trend-radar-dashboard:8000`, `tubedepth-api:8080`) (D3). Link-local, multicast,
  reserved, and unspecified stay blocked under every flag; the SSRF posture (add-on names
  an endpoint, the source row's grant decides the destination) is unchanged (D4).

### Technology constraints

- `[결정]` Backend language: Python.
- `[결정]` Primary database: PostgreSQL.
- `[결정]` Dashboard: React and TypeScript.
- `[결정]` P0-B must support both REST API collection and existing dataset import.

Framework and library selections such as FastAPI, SQLAlchemy, Alembic, HTTPX, React Router, TanStack Query, and MUI are strong P0 defaults. Two different questions follow from that and the answer differs:

- **Adopting one is optional.** A default is a starting point, not an obligation, and AGENTS.md still applies: an abstraction that reduces no named uncertainty should not be introduced. Declining a default requires a recorded reason, not contrary evidence — there is nothing to have evidence about until something is in use.
- **Replacing one already in use requires contrary evidence**, because work has been built on it and the cost of changing is real.

`[결정]` This distinction was added on 2026-08-17 by [DP-006](decisions/DP-006-p0a-platform-foundation.md). The original sentence said only that these defaults "remain replaceable if an experiment produces contrary evidence", which read strictly would have required P0-A to adopt every one of them before it could decline any. DP-006 declined five, and the ambiguity was flagged there rather than resolved silently. The reviewer accepted the adoption-versus-replacement reading and asked for this clarification so that P0-B does not meet the same question again with FastAPI and HTTPX.

### P0-A boundary

P0-A implements only source- and normalization-independent platform behavior:

- PostgreSQL runtime, migrations, and source-neutral transaction foundations;
- handler-neutral jobs, workers, API lifecycle, and safe shutdown;
- generic claim, lease, retry, terminal-state, interruption, and recovery behavior;
- a source-neutral operator dashboard, logs, metrics, correlation, and safe retry;
- redaction, loopback binding, secret-store location guards, synthetic handlers, and platform failure injection.

P0-A does not explore or select sources and does not implement acquisition, Raw, snapshot, or normalization contracts, ports, test doubles, persistence, domain UI, or acceptance claims.

### P0-B boundary

P0-B owns all source and normalization work. [DP-008](decisions/DP-008-addon-architecture.md) splits it into two tracks that run in parallel and then converge:

```text
add-on track                          source track
(no source or decision semantics)     (blocked by OQ-001 and OQ-002)

add-on contract, host, and            bounded candidate exploration
  version gate                          and rights review
→ source registry, cursor, Raw,       → REST source and dataset selection
    and snapshot tables               → provisional decision use
→ platform outbound guard
→ conformance suite, template,
    and generator
→ add-on operator surfaces
                        ↓                         ↓
        acquisition, Raw, snapshot, normalization, operations,
          source-policy, and credential contracts
        → independent scraper service and collector adapter, importer, and normalizer add-on implementations
        → component, real-data, failure, replay, concurrency, and operator verification
        → Architecture Synthesis and artifact disposition
        → PoC Contract 0.1 and P1 reconstruction plan
        → P1 Entry Gate
```

`[추론]` The add-on track carries no source or decision semantics, so neither OQ-001 nor OQ-002 blocks it. What OQ-002 blocks is the content of the normalizer's rules, not the protocol they are written against.

Source probes are measurements inside P0-B. They are not integrated service adapters or importer implementations and cannot satisfy those obligations retroactively.

### Add-on architecture

`[결정]` Collectors, importers, and normalizers are in-repository add-ons behind a contract, accepted in [DP-008](decisions/DP-008-addon-architecture.md). A new source adds a directory, not platform code.

- `[결정]` One package format and manifest; capabilities granted by `kind`. A collector receives a platform-composed `fetch`, an importer receives a platform-opened input, a normalizer receives a hash-verified snapshot.
- `[결정]` An add-on never receives a credential, never composes a URL, and never holds a database handle. Every outbound obligation in the [P0 Security Baseline](conventions/p0-security.md) stays on the platform.
- `[결정]` Add-ons depend on the contract package alone. `platform_core` gains no dependency on the add-on layer, and a dependency-direction test enforces both directions.
- `[결정]` Four version axes carry defined failures: contract, add-on, config schema, and normalizer output contract.
- `[결정]` In-process add-ons are trusted code. Isolation is contractual and test-enforced, not enforced by the operating system.
- `[결정]` Source-specific scraper code, scheduling, and first-stage storage may run as independent REST services under [DP-012](decisions/DP-012-independent-scraper-services.md). COSMAI keeps only a thin collector adapter, never imports the scraper project, and never reads its database directly.
- `[결정]` The service database and COSMAI transaction are independent. Replayable `batch_id`, stable `record_id`, and cursor semantics replace a distributed transaction; COSMAI still commits Raw, its cursor, and accepted job completion atomically.

### Data and workflow principles

The following accepted principles become executable domain behavior in P0-B, not P0-A:

- `[결정]` Imported external datasets remain untrusted Raw data.
- `[결정]` Raw data preserves original payload and provenance and is logically append-only.
- `[결정]` Collection and normalization are independently controlled job domains.
- `[결정]` Normalization is started explicitly by an operator-created run or an optional schedule; collection does not implicitly trigger it.
- `[결정]` A normalization run consumes a sealed, materialized, hash-verifiable input snapshot.
- `[결정]` Normalized results are versioned and coexist; they are not updated in place as the single truth.
- `[결정]` P0 includes at least one deterministic rule-based normalizer.
- `[결정]` Dashboard control, logs, metrics, and debugging evidence are part of P0 instrumentation.

### Project memory and agent workflow

- `[결정]` [DP-013](decisions/DP-013-agent-workflow-and-project-memory.md) makes repository documents, rather than session memory, the project record.
- `[결정]` Consequential directions require an explicit owner question and a recorded answer before implementation.
- `[결정]` Agent work is separated into orchestrator, planner, worker, and attacker responsibilities and handed off through bounded task packets and review reports.
- `[결정]` The full agent flow applies by the threshold recorded in [Agent Operating Model](agent-workflow/README.md), not to every change.
- `[결정]` [DP-014](decisions/DP-014-agent-memory-scope-and-area-exception.md) fixes what project memory covers: this repository is where a project fact belongs, and the convention does not regulate a private memory store. It also accepts that documents changing the project's operating method belong to no development area.
- `[확인 사실]` **One** part of that model is enforced: `tests/environment/test_agent_packet_record.py` rejects an `ACCEPTED` packet with no resolvable attack report. The rest is convention and is listed as such rather than implied. An earlier revision of this line also claimed `adversarial-reviewer` cannot write; that was false — its frontmatter denies three edit tools but not `Bash`. [REVIEW-TASK-001](agent-workflow/reviews/REVIEW-TASK-001.md) F1 measured the write.

`[결정]` **Findings that P0 recorded rather than repaired are registered in**
[`P1-INHERITED-DEFECTS.md`](architecture-synthesis/P1-INHERITED-DEFECTS.md). `[확인 사실]` **It is
not one of the four artifacts the P1 Entry Gate is defined to accept**, and whether it becomes a
fifth is the owner's decision, not one this file may make. An earlier revision of this sentence
said the gate consumes it, which asserted a process nobody accepted. `[확인 사실]` It exists because an adversarial review of this section's own
consolidation measured that ten findings had been "routed to the gate" while no such document
existed — including a platform defect where one malformed row aborts a normalize run.

## 5. Architecture hypotheses

These are not contracts.

- `[가설]` A source- and normalization-independent platform core can expose useful execution, recovery, operator, and safety evidence before P0-B introduces the domain pipeline.
- `[가설]` PostgreSQL job tables with at-least-once processing and idempotent platform effects are sufficient for P0 concurrency.
- `[가설]` A shared Raw envelope plus source-specific payload can represent both REST responses and dataset rows without loss. `[측정]` **Supported for the shapes tested, 2026-08-19.** One `raw_envelope` carried a REST response and a local file through the same completion transaction; `endpoint_ref` and `status` became nullable and `input_ref` joined them ([DP-024](decisions/DP-024-local-input-registry.md)) — a column becoming optional, not a second table. `[측정]` **A real producer's third shape passed the same envelope on 2026-08-20.** Open Beauty Facts product rows — barcode-keyed JSON objects from a nightly delta export — went through one `raw_envelope` and 121 `raw_item` rows with payloads byte-identical to the source lines, adding no column and no table. So the envelope now carries a REST response, a DataLab trend point, and a crowd-contributed product row. `[확인 사실]` The sentence this replaces said the dataset half was self-authored; that was true until TASK-007 and is no longer.
- `[가설]` A materialized snapshot plus manifest and hashes is sufficient for replay despite later Raw-store changes or migration. `[측정]` **Both halves tested by 2026-08-20, and the hypothesis holds in a narrower form than it claims.** Tampering is detected and named. Raw-store evolution *was* exercised: TASK-005 built an experiment that discriminates — an additive migration, a later collection superseding a sealed key, and a purge of every Raw row, with the sealed snapshot replaying byte-identically at all four steps while a re-query design diverges at step three and returns nothing at step four. `[확인 사실]` The sentence this replaces said the evolution half had no evidence; that was true on 2026-08-19 and is no longer. `[확인 사실]` It reached that state through a `FAIL` and a rework: TASK-003's first attempt did not discriminate, and TASK-005 is the experiment that does.
  `[측정]` **Narrower, because against the reference design [OQ-004](open-questions/OQ-004-snapshot-boundary.md) actually names** — references to append-only Raw rows, fixed at seal — only the purge separates the two. `[측정]` And a further gap the same question now carries: which member wins when two observations of one key are sealed together is decided by `emitted_at`, which is a **transaction** timestamp, so "the later import wins" holds per import and not per row. Forcing a tie drops the decision to a `uuid4`, and two of three keys then selected the older payload.
- `[가설]` One small `Normalized Schema 0.x` can express useful common meaning across the first two sources. `[측정]` **Refuted in its strong form on 2026-08-19.** Against a blog document and a DataLab trend point the only overlap is identity, time, and provenance — the fields any record needs to *be* a record — and there is no common domain meaning between "someone wrote this" and "people searched this much". [DP-021](decisions/DP-021-schema-0-2-trend-points.md) adopts the weaker form: one schema carries a common **envelope** and a per-type body. The Architecture Synthesis should carry the refutation rather than restate the hypothesis.
  `[측정]` **A third source strengthened the refutation on 2026-08-20 rather than rescuing the strong form.** An Open Beauty Facts product row shares with a blog document and a trend point exactly what the other two share with each other — identity, time, provenance — and nothing else, so [DP-028](decisions/DP-028-schema-0-3-product-records.md) answered it the way DP-021 answered the second source: a third union member, not a wider common body. `[추론]` Two record shapes could be coincidence; three is a pattern — with the caveat that two of the three come from one provider, so what is varied here is record *shape*, not provider. A P1 design assuming a common flat normalized table is still designing against it.
- `[가설]` A rule baseline can expose schema and quality problems before ML or LLM providers are introduced. `[측정]` **Built and tested on 2026-08-20, on fixtures rather than on real data, and the distinction is load-bearing.** `normalizer.rule.baseline@0.1` judges: ten deterministic rules that name which rule fired, which field, what was expected, and what was there. Every rule is killed by at least one mutation. `[확인 사실]` **Three** independent attacks ran against it, and **two of the three returned `FAIL`** — on claims made about the rules, never on the rules themselves. `[측정]` The first applied 38 mutations and killed all 26 that were aimed at rule behaviour; **the survivors were outside rule behaviour and are what its `FAIL` was about**, and its own report publishes no survivor total, so none is stated here. The second killed 11 more and ran 16,000 differential comparisons with zero divergence; the third ran 4,000 more, also zero. `[확인 사실]` An earlier revision of this sentence reported a survivor count that was the killed count inverted, and credited the second attack's 16,000 comparisons to the third. `[확인 사실]` Those are three different kinds of measurement and are not summed here — a killed mutant and an unchanged comparison say opposite things, and one total would hide which was which.
  `[측정]` **Five of the ten cannot fire on anything the NAVER collectors produce**, because those collectors already refuse the inputs those rules exist to catch. `[추론]` That is the first line working, not a dead rule — but it means the hypothesis is answered by fixture evidence, and the owner accepted that rather than adding a rule so something would fire on real data.
  `[측정]` **What the baseline exposed was a schema and record problem, not a data-quality one**: `clean: true` could be emitted for a record a rule never evaluated. Three review rounds established that `_coverage` cannot catch it — coverage is computed by subtraction — and the record now says so instead of claiming a control. `[확인 사실]` The sentence this replaces said no quality baseline was built; that was true on 2026-08-19 and is no longer.

The first two hypotheses can begin in P0-A. Acquisition and normalization hypotheses are tested only in P0-B.

## 6. Open questions

| ID | Status | Stage | Question | Blocks |
|---|---|---|---|---|
| [OQ-001](open-questions/OQ-001-source-capability.md) | `OPEN` | P0-B | Which REST and dataset sources are usable and representative? | Source contract, fixtures, P0-B ingestion |
| [OQ-002](open-questions/OQ-002-project-decision-contract.md) | `RESOLVED` | P0-B | Which decision should the final product improve? | Resolved for P0 by DP-011; long-term learned targets remain outside P0 |
| [OQ-003](open-questions/OQ-003-normalization-protocol.md) | `OPEN` | P0-B | What are Schema 0.x and the normalizer provider protocol? | P0-B normalization |
| [OQ-004](open-questions/OQ-004-snapshot-boundary.md) | `RESOLVED` | P0-B | What exactly must a sealed snapshot materialize? | Resolved for P1 by DP-029; measurements preserved as rationale |
| [OQ-005](open-questions/OQ-005-operations-contract.md) | `OPEN` | P0-A/P0-B | Which platform and domain actions and evidence must the dashboard expose? | Dashboard acceptance contract |
| [OQ-006](open-questions/OQ-006-job-concurrency.md) | `OPEN` | P0-A/P0-B | Is the PostgreSQL job model sufficient under platform and domain failures? | Worker, retry, and transaction contract |
| [OQ-007](open-questions/OQ-007-credential-scope.md) | `OPEN` | P0-A/P0-B | What does the platform protect before a source exists, and which real credentials may a domain worker resolve? | Secret guard and source credential contract |
| [OQ-008](open-questions/OQ-008-operator-reexecution-authority.md) | `OPEN` | P0-B | May an operator re-execute work that already succeeded, and what distinguishes that from retrying a failure? | Operator action set in `PoC Contract 0.1` |
| [OQ-009](open-questions/OQ-009-credential-shape.md) | `RESOLVED` | P0-B | How is a source's credential declared, and where does each part of it go? | Resolved for P0-B by [DP-018](decisions/DP-018-credential-parts-and-attachment.md) on one source's evidence; H1's query-parameter and signed-request cases stay open |
| [OQ-010](open-questions/OQ-010-cursor-stream-read-back.md) | `OPEN` | P0-B | Which cursor does an add-on read back when it writes several streams? | Multi-stream collectors and importers, conformance resume scenario |
| [OQ-011](open-questions/OQ-011-agent-memory-and-area-boundary.md) | `RESOLVED` | P0-B | Do the two rules the operating-model adoption wrote without asking — the private-memory rule and the development-area exception — bind? | Resolved 2026-08-19 by DP-014: the memory rule narrowed to the repository half, the area exception accepted |
| [OQ-013](open-questions/OQ-013-addon-responsibility-boundary.md) | `OPEN` | P0-B | What is an add-on responsible for, and what holds a judgment no other layer can check? | Repair shape for mutation review B5; any fourth collector; the P1 add-on contract |
| [OQ-014](open-questions/OQ-014-externalized-acquisition.md) | `RESOLVED` | P0-B | Should acquisition leave this service and be read over REST from a service that accumulates it? | Answered by [DP-012](decisions/DP-012-independent-scraper-services.md), accepted the same day on another branch. OQ-014's measurement is carried into DP-012 as falsification input |
| [OQ-015](open-questions/OQ-015-share-alike-data-class.md) | `OPEN` | P1 | Where does share-alike-encumbered data sit in a three-class taxonomy? | The first P1 artifact published from a store holding an ODbL source; opened by [DP-027](decisions/DP-027-dataset-standard-and-share-alike.md) D4 |

Stage expresses evidence routing, not long-term business importance.

## 7. Local implementation choices

Implementation may choose these without a Decision Packet when behavior and accepted constraints do not change:

- function, class, module, and component names;
- helper and internal folder decomposition inside an experiment;
- equivalent parsing or iteration algorithms;
- minor dashboard layout and styling;
- polling intervals within documented operational bounds;
- test helper libraries.

## 8. Specification frontier

P0-A may specify only platform invariants such as generic ownership, lease recovery, observable state, redaction, loopback exposure, and secret-store location guards.

P0-A must not freeze source identity, provider fields, Raw semantics, snapshot selection, normalized semantics, source-specific retry policy, or concrete credential authorization. P0-B may propose those as experimental contracts after source evidence exists. Production topology, scale infrastructure, final product analytics, and `Normalized Schema 1.0` remain outside P0.

## 9. Candidate services

Services beyond the current P0-B scope are recorded in the [service register](service-register.md)
as `[가설]` candidates rather than as a roadmap. `[추론]` Naming a future service and a
milestone for it would answer [OQ-002](open-questions/OQ-002-project-decision-contract.md)
by implication, because choosing what to build is choosing which decision to improve.
The register records what each candidate would consume, produce, and require instead.

## 10. Historical context

The reasoning path from the initial ingestion idea to the disposable P0 lifecycle is recorded in [HIST-001](history/HIST-001-initial-concept-to-p0.md). DP-004 is retained as a superseded decision record.

History documents are non-authoritative. Current requirements come from this Project State, active accepted Decision Packets, and versioned contracts.
