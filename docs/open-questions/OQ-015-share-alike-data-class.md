# OQ-015 — Where share-alike-encumbered data sits in a three-class taxonomy

- Status: `OPEN`
- Priority: P1 — nothing in P0 publishes, so nothing in P0 triggers it
- Owner: Project team
- Owner decision: `CONFIRMED (Decision Packet)` — [DP-027](../decisions/DP-027-dataset-standard-and-share-alike.md) D4 decided not to answer this in P0 and to record it here instead
- Blocks: the first P1 artifact built on an ODbL source that leaves this organisation
- Related experiments: [`SRC-003`](../../experiments/source-probes/SRC-003-open-beauty-facts.md), open question 3
- Resolution Decision Packet: not created

## Question

`docs/conventions/data-handling.md` classifies every input as `public`, `local`, or
`private`. `[측정]` `SRC-003` found a case none of the three describes: Open Beauty Facts is
**redistributable, but only if everything downstream is published under the same terms**.

Which class does share-alike-encumbered data take, and does the taxonomy need a fourth?

## Why this cannot be decided yet

`[확인 사실]` The three classes answer *may this leave the machine*. ODbL asks a different
question — *what happens to everything derived from it when it does*. ODbL 1.0 §4.4 c and
§4.6 attach the share-alike obligation and the machine-readable-copy offer to the
**Derivative Database**, not to the import; §4.5 c puts internal use outside §4.4 entirely.
So the encumbrance is invisible until publication and total afterwards.

`[추론]` A class cannot be designed from one source. The taxonomy's other three each cover a
family — this would be a fourth defined by a single licence on a single candidate, and
`data-handling.md`'s own classes were derived from several. `[결정]` DP-027 D4: inventing a
fourth class at the end of a phase, on one source, is how a taxonomy acquires a category
nobody can apply.

`[확인 사실]` Nothing in P0 forces the question. P0 publishes no derived artifact, so OBF is
registered `local` — the conservative and reversible reading `naver-real-data/README.md`
already uses for a different reason.

## Scope

### Included

- Whether `public` / `local` / `private` gains a fourth class, gains a **flag orthogonal to
  the class**, or stays as it is with the obligation recorded per source.
- What the platform must refuse or warn about when an encumbered source's data reaches an
  export, a card, or a public surface.
- Whether the obligation is a property of the **source row**, of the **snapshot**, or of the
  **normalized result** — a normalized store mixing an encumbered source with an
  unencumbered one is the case that decides it.

### Excluded

- ODbL interpretation itself. `SRC-003` §"What the licence requires of derived output"
  settled that with citations and is not reopened here.
- Choosing a dataset. [DP-027](../decisions/DP-027-dataset-standard-and-share-alike.md) D2
  did that for P0.

## Hypotheses and falsification

| Hypothesis | Falsification condition |
|---|---|
| H1: The obligation is orthogonal to the three classes and belongs on the source row as a flag, not as a fourth class. | A real source needs an encumbrance that changes whether the data may be *retrieved or processed at all*, which is what the classes decide — in which case it is not orthogonal. |
| H2: The obligation propagates with lineage, so a normalized result inherits the union of its sources' encumbrances. | Two sources' terms are mutually incompatible, so a store mixing them cannot be published under any single licence and the union is not a licence anyone can grant. |
| H3: The platform can refuse an encumbered publication mechanically, from the lineage it already stores. | Deciding whether an output is a "Produced Work" or a "Derivative Database" requires reading the output's meaning, which no stored lineage carries. |

## Alternatives

- **A fourth class, `share_alike`.** Explicit, and wrong if the property is orthogonal —
  a source can be `share_alike` and also carry personal data, and one field cannot say both.
- **A flag on the source row.** `[추론]` The most likely answer under H1, and the cheapest to
  add. It leaves "which of my snapshots are encumbered" as a join rather than a column.
- **Nothing in the platform; a recorded obligation per source.** What P0 does. Honest while
  nothing publishes, and it stops being honest the moment something does.
- **Refuse encumbered sources entirely.** Removes the question and most open data with it.

## Exit condition

A P1 artifact is about to be published from a store containing an encumbered source, and
the platform can say — from what it stores, not from a person's memory — that the artifact
carries an obligation and which one.

## 2026-08-21 addendum — M8 deploy makes the exit condition's premise real

`[확인 사실]` M8 (`docs/p1/M8-DEPLOY-RECORD.md`) put a second PostgREST instance,
`postgrest-cosmai`, in front of the live `cosmai` database on the shared
PostgreSQL server — `PGRST_DB_SCHEMAS=cosmai`, anonymous SELECT on every table
in schema `cosmai` via `postgrest_cosmai_anon`, published on the local network
(`stack/README.md`'s cosmai section, `stack/init/50-cosmai-bootstrap.sh`). The
owner accepted this exposure and its ODbL consequence explicitly as part of the
M8 brief, in the same session this note was recorded.

`[확인 사실]` The live `cosmai` database's `source` table includes
`obf.product.normalize` (an Open Beauty Facts normalizer) alongside sources this
question does not concern; `normalized_result` and any downstream export table
in schema `cosmai` is now reachable by an anonymous `SELECT` through
`postgrest-cosmai`, unconditionally — the grant is schema-wide
(`GRANT SELECT ON ALL TABLES IN SCHEMA cosmai TO postgrest_cosmai_anon`, plus a
matching default-privilege grant for tables created later), not filtered by
source.

`[추론]` This is exactly this question's own Exit condition: "A P1 artifact is
about to be published from a store containing an encumbered source." It is no
longer "about to be" — normalized OBF-derived rows, if any exist in the current
data, are already reachable by anonymous SELECT the moment `postgrest-cosmai`
is up. `[가설]` Whether any row currently in `normalized_result` actually
derives from `obf.product.normalize` is not established by this addendum — a
row count or lineage check would be needed to say so, and this note does not
claim it. What this addendum does establish is that the *question* stops being
hypothetical: OQ-015 was `OPEN` and low-priority ("nothing in P0 publishes, so
nothing in P0 triggers it") precisely because no publication surface existed.
One now does, by owner decision, and DP-027's deferred share-alike obligation
attaches to whatever encumbered-source rows the schema-wide grant actually
reaches.

This addendum does not resolve OQ-015 — no taxonomy decision, flag, or refusal
mechanism is added here, and status stays `OPEN`. It records that the question
is live rather than deferred, and that a Decision Packet answering it (fourth
class, orthogonal flag, or a mechanical refusal per H3) is no longer optional
background work — `postgrest-cosmai` publishes ahead of that decision, which is
the exact gap H3's falsification condition and the "Nothing in the platform; a
recorded obligation per source" alternative both already named as unsafe once
something actually publishes.

## Resolution

Not completed while status is `OPEN`. Resolution requires a Decision Packet.
