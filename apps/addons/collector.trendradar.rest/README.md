# collector.trendradar.rest

Adapter for trend-radar 1.0.0's read-only, unauthenticated JSON API
(`http://trend-radar-dashboard:8000/api/v1`), fixed as a P1 adapter target by
[DP-031](../../../docs/decisions/DP-031-p1-collector-topology.md) D3, with the address
revised from the loopback literal to the fleet hostname by
[DP-035](../../../docs/decisions/DP-035-fleet-egress-and-container-bind.md) D3 once
cosmai joins the fleet's `db-net` bridge network. Built against the spec's own adapter
design (`docs/superpowers/specs/2026-08-21-p1-reconstruction-design.md` §5.1) and
`service/trend-radar`'s own `docs/api.md` (read-only to this project).

## What it collects

The nine record tables `service/trend-radar` exposes under `GET /api/v1/records/{table}`,
split the way the spec splits them:

- **Hour-bucket** (`rank_snapshot`, `price_point`, `review_stats`, `review_summary`,
  `review_topic`): collected per source (and `board`, for `rank_snapshot`, when
  configured), newest rows first, up to the source's own stored high-water mark.
- **Full-scan / write-once** (`product`, `review`, `review_answer`, `new_product`):
  re-paged in full every run per configured source. Duplicates are expected and are
  resolved at snapshot-seal time by natural-key latest-wins (spec §5.1) — this add-on
  does not deduplicate them itself.

`GET /api/v1/sources` discovers the source list when `sources` is not configured.
`GET /api/v1/runs` is read once per run to skip a table+source with nothing new since
last time — an optimization, not a correctness dependency (see handler.py's docstring
if it is ever unreachable or malformed: the skip is simply not taken).

## Why it never sends `captured_at` as a filter

`[측정]` It 500s on the live instance. Every ISO 8601 encoding tried against
`GET /api/v1/records/{table}?captured_at=...` returned `500 Internal Server Error`,
while `source` and `board` — the table's other primary-key columns — return `200` with
a correctly echoed `filters` object. `service/trend-radar` is read-only to this project
(`AGENTS.md`); this was not investigated further or fixed there. See
`apps/tests/fixtures/public/collector.trendradar.rest/MANIFEST.md` for the exact
attempts. The spec (§5.1) describes exact-match collection on
`source+board(when applicable)+captured_at`; this add-on gets the same practical
result — bounded, incremental, per-bucket collection — by filtering on `source`(+`board`)
only and relying on the API's own `captured_at DESC` ordering plus its own stored
cursor to recognize where it left off, instead of a `captured_at` filter that does not
work.

## Cursor

One declared stream (`buckets`). `context.cursor` holds one JSON object:

```json
{
  "hour_bucket": {"rank_snapshot": {"daisomall": "2026-08-21T02:00:00+00:00"}},
  "full_scan": {"product": {"daisomall": "2026-08-21T02:01:31.693415+00:00"}}
}
```

The spec says "테이블별 마지막 처리 시간 버킷" (cursor: per-table last processed
bucket); this add-on extends that one level to per-table-*per-source*, because
sources advance independently (`docs/api.md`'s own `/health` sample shows different
`last_hour` values per source). That is a local representation choice — it stays
inside the one stream the manifest declares, so it does not reopen
[OQ-010](../../../docs/open-questions/OQ-010-cursor-stream-read-back.md) (whether the
contract should ever hand an add-on more than one cursor stream); DP-031 flagged this
add-on as the one that would plausibly need that, and this is the answer that avoids
needing it.

## Raw mapping

One API response page is one envelope. One row is one `RawItem`. `item_key` is the
table name plus its natural-key columns
(`src/trend_radar/models.py`'s `NATURAL_KEY`, mirrored by `storage/tables.py`'s
primary keys and `docs/api.md`'s `filterable`), joined with `"|"` — the table name is
included because two of the nine tables (`product`, `new_product`) share the same
natural key shape `(source, product_key)`, and `item_key` is only unique within one
source.

## Filters-echo verification (silent-drop defense)

`docs/api.md`: an unrecognized query parameter is silently dropped, not rejected.
Before trusting a page, this add-on compares the response's echoed `filters` against
what it actually requested and raises `AddonPermanent` — refusing the page — on any
mismatch. It only ever requests `source` and `board`, both documented primary-key
columns, so no live mismatch is expected; the check is there for a future trend-radar
release that renames or drops one silently.

## Configuration

| field | default | notes |
|---|---|---|
| `tables` | all nine | comma-separated |
| `sources` | discovered via `/api/v1/sources` | comma-separated |
| `boards` | none (no board filter) | `rank_snapshot` only; one request per (source, board) |
| `page_limit` | 500 | 1–1000, the API's own cap |
| `runs_lookback` | 50 | 1–200, the API's own cap on `/api/v1/runs?limit=` |

## No credential

`needs_credential = false`. `docs/api.md`: "Read-only, no authentication, localhost by
default."

## The operator-approved outbound profile

DP-035 D3's revised target, as the registered source row now needs to actually reach it
(the manifest's `[declares].hosts` above states only what the add-on needs approved —
DP-008 D4 keeps the grant itself on the row):

```json
{
  "hosts": ["trend-radar-dashboard"],
  "port": 8000,
  "scheme": "http",
  "allow_fleet": true,
  "endpoints": { "...": "as declared above" }
}
```

`scheme: "http"` is granted only because `allow_fleet` is also set — the flag
`domain.outbound.resolve` requires before it will admit plain HTTP at all
(`domain.outbound.py`, DP-035 D1); a host outside the fleet's private address range with
`scheme: "http"` is refused both there and again by `domain.transport.SocketTransport`
against the address it actually resolved.

## No normalizer in this batch

RC-005 registers `rank`/`review`-family `record_type`s as a milestone; the spec (§6)
keeps first-pass normalization to the three existing types (blog document, trend
point, obf product). This collector's Raw rows are browseable and exportable as Raw
without one — they are not blocked on RC-005 landing.

## Testing

- `apps/tests/test_collector_trendradar.py`: pagination and bucket-cursor logic,
  filters-echo refusal (a synthetic silently-dropped filter, since the live target
  never actually drops a recognized one), cursor resume, conformance suite, and
  host-loading, all against the fixtures in
  `apps/tests/fixtures/public/collector.trendradar.rest/` (provenance in that
  directory's `MANIFEST.md`).
- A live smoke test against the running `shared-db-trend-radar-dashboard-1` container
  is recorded in this batch's report
  (`.superpowers/sdd/2026-08-21-m2-m7-batch/m4-trendradar-report.md`), including a
  concern about whether the platform's outbound guard can reach it at all — see that
  report before assuming this add-on collects end-to-end through the host today.
